import enum
from enum import Enum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List, Optional

import pytest
from pydantic import BaseModel

from mountaineer.actions import passthrough, sideeffect
from mountaineer.app import AppController
from mountaineer.client_builder.builder import APIBuilder
from mountaineer.client_builder.parser import (
    ControllerWrapper,
    EnumWrapper,
    ModelWrapper,
    SelfReference,
)
from mountaineer.controller import ControllerBase
from mountaineer.render import RenderBase


# Test Models and Controllers
class Status(enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"


class Address(BaseModel):
    street: str
    city: str
    country: str


class User(BaseModel):
    id: int
    name: str
    status: Status
    addresses: List[Address]
    primary_address: Optional[Address] = None


class BaseRender(RenderBase):
    version: str
    env: str


class UserRender(BaseRender):
    current_user: User


class AdminRender(UserRender):
    all_users: List[User]
    pending_count: int


class ActionResponse(BaseModel):
    success: bool
    message: str


class UserActionResponse(ActionResponse):
    user: User


class BaseController(ControllerBase):
    @sideeffect
    async def get_version(self) -> ActionResponse:
        return ActionResponse(success=True, message="1.0.0")


class UserManagementMixin(ControllerBase):
    @sideeffect
    async def update_user(self, user_id: int, status: Status) -> UserActionResponse:
        return UserActionResponse(
            success=True,
            message="Updated",
            user=User(id=user_id, name="Test", status=status, addresses=[]),
        )


class AdminController(BaseController, UserManagementMixin):
    url = "/admin/"
    view_path = "/admin/page.tsx"

    def render(self) -> AdminRender:
        return AdminRender(
            version="1.0.0",
            env="test",
            current_user=User(
                id=1,
                name="Admin",
                status=Status.ACTIVE,
                addresses=[
                    Address(street="123 Main St", city="City", country="Country")
                ],
            ),
            all_users=[],
            pending_count=0,
        )

    @passthrough
    async def get_pending_users(self) -> User:
        return User(id=2, name="User", status=Status.PENDING, addresses=[])

    @sideeffect
    async def approve_user(self, user_id: int) -> UserActionResponse:
        return UserActionResponse(
            success=True,
            message="Approved",
            user=User(id=user_id, name="Test", status=Status.ACTIVE, addresses=[]),
        )


class UserController(BaseController):
    url = "/user/"
    view_path = "/user/other.tsx"

    def render(self) -> UserRender:
        return UserRender(
            version="1.0.0",
            env="test",
            current_user=User(id=2, name="User", status=Status.ACTIVE, addresses=[]),
        )

    @sideeffect
    async def update_profile(self, name: str, address: Address) -> UserActionResponse:
        return UserActionResponse(
            success=True,
            message="Updated",
            user=User(id=2, name=name, status=Status.ACTIVE, addresses=[address]),
        )


# Fixtures
@pytest.fixture(scope="function")
def simple_app_controller():
    with TemporaryDirectory() as temp_dir_name:
        temp_view_path = Path(temp_dir_name)
        (temp_view_path / "admin").mkdir()
        (temp_view_path / "user").mkdir()
        app_controller = AppController(view_root=temp_view_path)
        yield app_controller


@pytest.fixture
def builder(simple_app_controller: AppController):
    return APIBuilder(simple_app_controller)


@pytest.fixture
def setup_controllers(builder: APIBuilder):
    admin_controller = AdminController()
    user_controller = UserController()
    builder.app.register(admin_controller)
    builder.app.register(user_controller)
    builder._parse_all_controllers()
    return builder


# Tests for Controller Parsing
def test_controller_parsing(setup_controllers):
    builder = setup_controllers

    assert len(builder.parsed_controllers) == 2
    admin_parsed = builder.parsed_controllers["AdminController"]
    user_parsed = builder.parsed_controllers["UserController"]

    # Admin controller checks
    assert not admin_parsed.is_layout
    assert admin_parsed.url_prefix == "/internal/api/admin_controller"
    assert sorted(
        [action.name for action in admin_parsed.wrapper.actions.values()]
    ) == [
        "approve_user",
        "get_pending_users",  # This is now a passthrough action
    ]
    assert admin_parsed.wrapper.render is not None

    # User controller checks
    assert not user_parsed.is_layout
    assert user_parsed.url_prefix == "/internal/api/user_controller"
    assert [action.name for action in user_parsed.wrapper.actions.values()] == [
        "update_profile"
    ]
    assert user_parsed.wrapper.render is not None


# Tests for TypeScript Interface Generation
def test_typescript_interfaces(setup_controllers):
    builder = setup_controllers
    builder._generate_model_definitions()

    code_dir = builder.view_root.get_managed_code_dir()
    controllers_content = (code_dir / "controllers.ts").read_text()

    # Check for enum and interface definitions
    assert "export enum Status " in controllers_content
    assert "export interface Address " in controllers_content
    assert "export interface User " in controllers_content
    assert "export interface BaseRender " in controllers_content
    assert "export interface UserRender extends BaseRender" in controllers_content
    assert "export interface AdminRender extends UserRender" in controllers_content
    assert "export interface ActionResponse " in controllers_content
    assert (
        "export interface UserActionResponse extends ActionResponse"
        in controllers_content
    )

    # Check for type definitions
    assert "status: Status;" in controllers_content
    assert "addresses: Array<Address>;" in controllers_content
    assert "primary_address?: Address;" in controllers_content
    assert "all_users: Array<User>;" in controllers_content


# Tests for Action Generation
def test_action_generation(setup_controllers):
    builder = setup_controllers
    builder._generate_action_definitions()

    # Admin actions
    admin_dir = builder.parsed_controllers[
        "AdminController"
    ].view_path.get_managed_code_dir()
    admin_actions = (admin_dir / "actions.ts").read_text()

    assert "export const get_version" in admin_actions
    assert "export const update_user" in admin_actions
    assert "export const get_pending_users" in admin_actions
    assert "export const approve_user" in admin_actions
    assert "Promise<GetVersionResponse>" in admin_actions
    assert "Promise<UpdateUserResponse>" in admin_actions
    assert "Promise<GetPendingUsersResponse>" in admin_actions

    # User actions
    user_dir = builder.parsed_controllers[
        "UserController"
    ].view_path.get_managed_code_dir()
    user_actions = (user_dir / "actions.ts").read_text()

    assert "export const get_version" in user_actions
    assert "export const update_profile" in user_actions
    assert "Promise<UpdateProfileResponse>" in user_actions


# Tests for Server Hook Generation
def test_server_hook_generation(setup_controllers):
    builder = setup_controllers
    builder._generate_view_servers()

    # Admin server hooks
    admin_dir = builder.parsed_controllers[
        "AdminController"
    ].view_path.get_managed_code_dir()
    admin_server = (admin_dir / "useServer.ts").read_text()

    assert "extends AdminRender, AdminController" in admin_server
    assert "linkGenerator: typeof LinkGenerator" in admin_server
    assert "get_version: applySideEffect(get_version" in admin_server
    assert "update_user: applySideEffect(update_user" in admin_server
    assert "get_pending_users" in admin_server  # Should be present but not wrapped
    assert "approve_user: applySideEffect(approve_user" in admin_server

    # User server hooks
    user_dir = builder.parsed_controllers[
        "UserController"
    ].view_path.get_managed_code_dir()
    user_server = (user_dir / "useServer.ts").read_text()

    assert "extends UserRender, UserController" in user_server
    assert "linkGenerator: typeof LinkGenerator" in user_server
    assert "get_version: applySideEffect(get_version" in user_server
    assert "update_profile: applySideEffect(update_profile" in user_server


# Test for File Generation
def test_file_generation(setup_controllers):
    builder = setup_controllers

    # Generate all files
    builder._generate_model_definitions()
    builder._generate_action_definitions()
    builder._generate_link_shortcuts()
    builder._generate_view_servers()
    builder._generate_index_files()

    # Check admin controller files
    admin_dir = builder.parsed_controllers[
        "AdminController"
    ].view_path.get_managed_code_dir()
    assert (admin_dir / "actions.ts").exists()
    assert (admin_dir / "useServer.ts").exists()
    assert (admin_dir / "links.ts").exists()

    # Check user controller files
    user_dir = builder.parsed_controllers[
        "UserController"
    ].view_path.get_managed_code_dir()
    assert (user_dir / "actions.ts").exists()
    assert (user_dir / "useServer.ts").exists()
    assert (user_dir / "links.ts").exists()


# Test classes to simulate different modules
class SampleModel1(BaseModel):
    field: str


class SampleModel2(BaseModel):
    field: str


class SampleEnum1(Enum):
    A = "a"


class SampleEnum2(Enum):
    A = "a"


class SampleController1(ControllerBase):
    pass


class SampleController2(ControllerBase):
    pass


def test_assign_unique_names(setup_controllers):
    builder = setup_controllers

    # Set up conflicting names across different modules
    # Simulate models from different modules with the same name
    sample_model1 = SampleModel1
    sample_model1.__module__ = "app.models.user"
    sample_model2 = SampleModel2
    sample_model2.__module__ = "app.models.admin"

    # Simulate enums from different modules with the same name
    sample_enum1 = SampleEnum1
    sample_enum1.__module__ = "app.enums.status"
    sample_enum2 = SampleEnum2
    sample_enum2.__module__ = "app.enums.type"

    # Simulate controllers from different modules with the same name
    sample_controller1 = SampleController1
    sample_controller1.__module__ = "app.controllers.user"
    sample_controller2 = SampleController2
    sample_controller2.__module__ = "app.controllers.admin"

    # Setup parser state with duplicate names
    builder.parser.parsed_models = {
        sample_model1: ModelWrapper(
            name="Sample",
            model=sample_model1,
            isolated_model=sample_model1,
            superclasses=[],
            value_models=[],
        ),
        sample_model2: ModelWrapper(
            name="Sample",
            model=sample_model2,
            isolated_model=sample_model2,
            superclasses=[],
            value_models=[],
        ),
    }

    builder.parser.parsed_enums = {
        sample_enum1: EnumWrapper(name="Status", enum=sample_enum1),
        sample_enum2: EnumWrapper(name="Status", enum=sample_enum2),
    }

    builder.parser.parsed_controllers = {
        sample_controller1: ControllerWrapper(
            name="MainController",
            controller=sample_controller1,
            superclasses=[],
            actions={},
            render=None,
        ),
        sample_controller2: ControllerWrapper(
            name="MainController",
            controller=sample_controller2,
            superclasses=[],
            actions={},
            render=None,
        ),
    }

    # Add a self-reference that refers to one of the models
    builder.parser.parsed_self_references = [
        SelfReference(name="Sample", model=sample_model1)
    ]

    # Run the name assignment
    builder._assign_unique_names()

    # Verify names were uniquified correctly
    assert builder.parser.parsed_models[sample_model1].name == "AppModelsUser_Sample"
    assert builder.parser.parsed_models[sample_model2].name == "AppModelsAdmin_Sample"

    assert builder.parser.parsed_enums[sample_enum1].name == "AppEnumsStatus_Status"
    assert builder.parser.parsed_enums[sample_enum2].name == "AppEnumsType_Status"

    assert (
        builder.parser.parsed_controllers[sample_controller1].name
        == "AppControllersUser_MainController"
    )
    assert (
        builder.parser.parsed_controllers[sample_controller2].name
        == "AppControllersAdmin_MainController"
    )

    # Verify self reference was updated to match its model's new name
    assert builder.parser.parsed_self_references[0].name == "AppModelsUser_Sample"
