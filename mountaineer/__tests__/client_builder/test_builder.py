import enum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List, Optional

import pytest
from pydantic import BaseModel

from mountaineer.actions import sideeffect
from mountaineer.app import AppController
from mountaineer.client_builder.builder import APIBuilder
from mountaineer.controller import ControllerBase
from mountaineer.render import RenderBase


@pytest.fixture(scope="function")
def simple_app_controller():
    with TemporaryDirectory() as temp_dir_name:
        temp_view_path = Path(temp_dir_name)
        # Simple view files
        (temp_view_path / "page.tsx").write_text("")
        (temp_view_path / "other.tsx").write_text("")
        app_controller = AppController(view_root=temp_view_path)
        yield app_controller


@pytest.fixture
def builder(simple_app_controller: AppController):
    return APIBuilder(simple_app_controller)


def test_generate_controller_definitions_complex(builder: APIBuilder):
    """
    Test complex controller inheritance scenarios including:
    - Multiple inheritance levels
    - Method overrides
    - Nested models
    - Enums
    - Optional fields
    - Lists
    - Action responses
    - Shared models between controllers
    """

    # Define some shared models and enums
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

    # Base render models
    class BaseRender(RenderBase):
        version: str
        env: str

    class UserRender(BaseRender):
        current_user: User

    class AdminRender(UserRender):
        all_users: List[User]
        pending_count: int

    # Action response models
    class ActionResponse(BaseModel):
        success: bool
        message: str

    class UserActionResponse(ActionResponse):
        user: User

    # Base controller with shared functionality
    class BaseController(ControllerBase):
        @sideeffect
        async def get_version(self) -> ActionResponse:
            return ActionResponse(success=True, message="1.0.0")

    # Mixin for user management
    class UserManagementMixin:
        @sideeffect
        async def update_user(self, user_id: int, status: Status) -> UserActionResponse:
            return UserActionResponse(
                success=True,
                message="Updated",
                user=User(
                    id=user_id,
                    name="Test",
                    status=status,
                    addresses=[],
                ),
            )

    # Admin controller with all features
    class AdminController(BaseController, UserManagementMixin):
        url = "/admin/"
        view_path = "/page.tsx"

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

        @sideeffect
        async def get_pending_users(self) -> User:
            return User(
                id=2,
                name="User",
                status=Status.PENDING,
                addresses=[],
            )

        @sideeffect
        async def approve_user(self, user_id: int) -> UserActionResponse:
            return UserActionResponse(
                success=True,
                message="Approved",
                user=User(
                    id=user_id,
                    name="Test",
                    status=Status.ACTIVE,
                    addresses=[],
                ),
            )

    # Regular user controller with limited functionality
    class UserController(BaseController):
        url = "/user/"
        view_path = "/other.tsx"

        def render(self) -> UserRender:
            return UserRender(
                version="1.0.0",
                env="test",
                current_user=User(
                    id=2,
                    name="User",
                    status=Status.ACTIVE,
                    addresses=[],
                ),
            )

        @sideeffect
        async def update_profile(
            self, name: str, address: Address
        ) -> UserActionResponse:
            return UserActionResponse(
                success=True,
                message="Updated",
                user=User(
                    id=2,
                    name=name,
                    status=Status.ACTIVE,
                    addresses=[address],
                ),
            )

    # Register both controllers
    admin_controller = AdminController()
    user_controller = UserController()
    builder.app.register(admin_controller)
    builder.app.register(user_controller)

    # Parse and generate
    builder._parse_all_controllers()

    # Assert correct parsing of inheritance
    assert len(builder.parsed_controllers) == 2
    admin_parsed = builder.parsed_controllers["AdminController"]
    user_parsed = builder.parsed_controllers["UserController"]

    # Verify admin controller parsing
    assert not admin_parsed.is_layout
    assert admin_parsed.url_prefix == "/internal/api/admin_controller"
    assert (
        [action.name for action in admin_parsed.wrapper.actions.values()] == [
            "get_pending_users", "approve_user"
        ]
    )
    assert admin_parsed.wrapper.render is not None

    # Verify user controller parsing
    assert not user_parsed.is_layout
    assert user_parsed.url_prefix == "/internal/api/user_controller"
    assert (
        [action.name for action in user_parsed.wrapper.actions.values()] == [
            "update_profile",
        ]
    )
    assert user_parsed.wrapper.render is not None

    # Generate all files
    builder._generate_model_definitions()
    builder._generate_action_definitions()
    builder._generate_link_shortcuts()
    builder._generate_view_servers()
    builder._generate_index_files()

    # Check generated files
    code_dir = builder.view_root.get_managed_code_dir()
    assert (code_dir / "controllers.ts").exists()

    # Verify content of controllers.ts
    controllers_content = (code_dir / "controllers.ts").read_text()

    # Check for all expected interfaces
    assert "export interface Status " in controllers_content
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

    # Check for correct type definitions
    assert "status: Status;" in controllers_content
    assert "addresses: Array<Address>;" in controllers_content
    assert "primary_address?: Address;" in controllers_content
    assert "all_users: Array<User>;" in controllers_content

    # Verify admin controller files
    admin_dir = admin_parsed.view_path.get_managed_code_dir()
    assert (admin_dir / "actions.ts").exists()
    assert (admin_dir / "useServer.ts").exists()
    assert (admin_dir / "links.ts").exists()

    # Check admin actions
    admin_actions = (admin_dir / "actions.ts").read_text()
    assert "export const get_version" in admin_actions
    assert "export const update_user" in admin_actions
    assert "export const get_pending_users" in admin_actions
    assert "export const approve_user" in admin_actions
    assert "Promise<ActionResponse>" in admin_actions
    assert "Promise<UserActionResponse>" in admin_actions
    assert "Promise<Array<User>>" in admin_actions

    # Verify user controller files
    user_dir = user_parsed.view_path.get_managed_code_dir()
    assert (user_dir / "actions.ts").exists()
    assert (user_dir / "useServer.ts").exists()
    assert (user_dir / "links.ts").exists()

    # Check user actions
    user_actions = (user_dir / "actions.ts").read_text()
    assert "export const get_version" in user_actions
    assert "export const update_profile" in user_actions
    assert "Promise<UserActionResponse>" in user_actions

    # Check useServer implementations
    admin_server = (admin_dir / "useServer.ts").read_text()
    assert "extends AdminRender, AdminController" in admin_server
    assert "linkGenerator: typeof LinkGenerator" in admin_server
    assert "get_version: get_version" in admin_server
    assert "update_user: update_user" in admin_server
    assert "get_pending_users: get_pending_users" in admin_server
    assert "approve_user: approve_user" in admin_server

    user_server = (user_dir / "useServer.ts").read_text()
    assert "extends UserRender, UserController" in user_server
    assert "linkGenerator: typeof LinkGenerator" in user_server
    assert "get_version: get_version" in user_server
    assert "update_profile: update_profile" in user_server
