from datetime import datetime
from enum import Enum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional

import pytest
from pydantic import BaseModel

from mountaineer.actions.passthrough_dec import passthrough
from mountaineer.actions.sideeffect_dec import sideeffect
from mountaineer.app import AppController
from mountaineer.client_builder.parser import (
    ControllerParser,
    EnumWrapper,
    SelfReference,
)
from mountaineer.client_builder.types import Or
from mountaineer.controller import ControllerBase
from mountaineer.render import RenderBase


# Test Models
class UserRole(Enum):
    ADMIN = "admin"
    USER = "user"
    GUEST = "guest"


class BaseStats(BaseModel):
    created_at: datetime
    updated_at: datetime


class BaseMetadata(BaseModel):
    version: int
    is_active: bool = True


class Location(BaseModel):
    city: str
    country: str
    postal_code: Optional[str] = None


class UserSettings(BaseModel):
    theme: str = "light"
    notifications_enabled: bool = True
    preferred_language: str = "en"


class UserProfile(BaseStats, BaseMetadata):
    id: int
    username: str
    role: UserRole
    location: Location
    settings: UserSettings
    friends: list[int] = []
    last_login: Optional[datetime] = None


class SystemStatus(BaseModel):
    status: bool
    last_check: datetime


class UserRoleResponse(BaseModel):
    role: UserRole
    permissions: list[str]


class DashboardData(RenderBase):
    user: UserProfile
    pending_notifications: int = 0


class ProfileUpdateRequest(BaseModel):
    location: Optional[Location] = None
    settings: Optional[UserSettings] = None


class ProfileUpdateResponse(BaseModel):
    success: bool
    updated_user: UserProfile


# Test Controllers
class BaseController(ControllerBase):
    @passthrough
    def get_system_status(self) -> SystemStatus:
        return SystemStatus(status=True, last_check=datetime.now())


class SharedController(BaseController):
    @passthrough
    def shared_friends(self, limit: int = 10) -> UserProfile:
        return UserProfile(
            id=1,
            username="test",
            role=UserRole.USER,
            location=Location(city="Test City", country="Test Country"),
            settings=UserSettings(),
            created_at=datetime.now(),
            updated_at=datetime.now(),
            version=1,
        )

    @passthrough
    def get_user_role(self) -> UserRoleResponse:
        return UserRoleResponse(role=UserRole.USER, permissions=[])


class UserDashboardController(SharedController):
    url = "/dashboard/"
    view_path = "/dashboard/page.tsx"

    async def render(self) -> DashboardData:
        return DashboardData(
            user=UserProfile(
                id=1,
                username="test",
                role=UserRole.USER,
                location=Location(city="Test City", country="Test Country"),
                settings=UserSettings(),
                created_at=datetime.now(),
                updated_at=datetime.now(),
                version=1,
            ),
            pending_notifications=5,
        )

    @sideeffect
    def update_profile(self, update: ProfileUpdateRequest) -> ProfileUpdateResponse:
        return ProfileUpdateResponse(
            success=True,
            updated_user=UserProfile(
                id=1,
                username="test",
                role=UserRole.USER,
                location=Location(city="Test City", country="Test Country"),
                settings=UserSettings(),
                created_at=datetime.now(),
                updated_at=datetime.now(),
                version=1,
            ),
        )

    @passthrough
    def get_friends(self, limit: int = 10) -> UserProfile:
        return UserProfile(
            id=1,
            username="test",
            role=UserRole.USER,
            location=Location(city="Test City", country="Test Country"),
            settings=UserSettings(),
            created_at=datetime.now(),
            updated_at=datetime.now(),
            version=1,
        )


# Fixtures
@pytest.fixture
def controller_parser():
    return ControllerParser()


@pytest.fixture
def app_controller():
    with TemporaryDirectory() as temp_dir_name:
        temp_view_path = Path(temp_dir_name)
        app_controller = AppController(view_root=temp_view_path)
        yield app_controller


@pytest.fixture
def parsed_controller(controller_parser, app_controller):
    controller = UserDashboardController()
    app_controller.register(controller)
    return controller_parser.parse_controller(controller.__class__)


# Test Controller Inheritance Structure
def test_controller_inheritance(parsed_controller):
    """Test the inheritance structure of the controller"""
    assert len(parsed_controller.superclasses) == 2

    superclass_names = [sc.name for sc in parsed_controller.superclasses]
    assert "SharedController" in superclass_names
    assert "BaseController" in superclass_names


# Test Base Controller Actions
def test_base_controller_actions(parsed_controller):
    """Test the actions defined in the base controller"""
    base_controller = parsed_controller.superclasses[1]
    assert set(base_controller.actions.keys()) == {"get_system_status"}

    action = base_controller.actions["get_system_status"]
    assert len(action.params) == 0
    assert action.response_body is not None

    # Test response structure
    fields = {f.name: f for f in action.response_body.value_models}
    assert set(fields.keys()) == {"passthrough"}

    system_status = fields["passthrough"].value
    status_fields = {f.name: f for f in system_status.value_models}
    assert set(status_fields.keys()) == {"status", "last_check"}
    assert status_fields["status"].value == bool
    assert status_fields["last_check"].value == datetime


# Test Shared Controller Actions
def test_shared_controller_actions(parsed_controller):
    """Test the actions defined in the shared controller"""
    shared_controller = parsed_controller.superclasses[0]
    assert set(shared_controller.actions.keys()) == {"shared_friends", "get_user_role"}

    # Test shared_friends action
    friends_action = shared_controller.actions["shared_friends"]
    assert len(friends_action.params) == 1
    assert friends_action.params[0].name == "limit"
    assert friends_action.params[0].value == int
    assert not friends_action.params[0].required

    # Test get_user_role action
    role_action = shared_controller.actions["get_user_role"]
    assert len(role_action.params) == 0

    fields = {f.name: f for f in role_action.response_body.value_models}
    role_wrapper = fields["passthrough"].value
    role_fields = {f.name: f for f in role_wrapper.value_models}
    assert set(role_fields.keys()) == {"role", "permissions"}
    assert isinstance(role_fields["role"].value, EnumWrapper)
    assert role_fields["role"].value.enum == UserRole


# Test Dashboard Controller Actions
def test_dashboard_controller_actions(parsed_controller):
    """Test the actions defined in the dashboard controller"""
    assert set(parsed_controller.actions.keys()) == {"update_profile", "get_friends"}

    # Test update_profile action
    update_action = parsed_controller.actions["update_profile"]
    assert update_action.request_body is not None

    update_fields = {f.name: f for f in update_action.request_body.value_models}
    assert set(update_fields.keys()) == {"location", "settings"}
    assert not update_fields["location"].required
    assert not update_fields["settings"].required

    # Test get_friends action
    friends_action = parsed_controller.actions["get_friends"]
    assert len(friends_action.params) == 1
    assert friends_action.params[0].name == "limit"
    assert not friends_action.params[0].required


# Test Render Model Structure
def test_render_model_structure(parsed_controller):
    """Test the structure of the render model"""
    assert parsed_controller.render is not None
    assert len(parsed_controller.render.superclasses) == 0

    fields = {f.name: f for f in parsed_controller.render.value_models}
    assert set(fields.keys()) == {"user", "pending_notifications"}
    assert not fields["pending_notifications"].required

    user_profile = fields["user"].value
    profile_fields = {f.name: f for f in user_profile.value_models}
    assert set(profile_fields.keys()) == {
        "id",
        "username",
        "role",
        "location",
        "settings",
        "friends",
        "last_login",
    }


# Test Complex Model Inheritance
def test_complex_model_inheritance(parsed_controller):
    """Test the inheritance structure of complex models"""
    user_field = parsed_controller.render.value_models[0]
    profile = user_field.value

    assert len(profile.superclasses) == 2
    superclass_names = {sc.model.__name__ for sc in profile.superclasses}
    assert superclass_names == {"BaseStats", "BaseMetadata"}

    # Test BaseStats fields
    base_stats = next(
        sc for sc in profile.superclasses if sc.model.__name__ == "BaseStats"
    )
    stats_fields = {f.name: f for f in base_stats.value_models}
    assert set(stats_fields.keys()) == {"created_at", "updated_at"}

    # Test BaseMetadata fields
    base_metadata = next(
        sc for sc in profile.superclasses if sc.model.__name__ == "BaseMetadata"
    )
    metadata_fields = {f.name: f for f in base_metadata.value_models}
    assert set(metadata_fields.keys()) == {"version", "is_active"}


# Test Nested Models
def test_nested_models(parsed_controller):
    """Test the structure of nested models"""
    user_field = parsed_controller.render.value_models[0]
    profile_fields = {f.name: f for f in user_field.value.value_models}

    # Test Location model
    location = profile_fields["location"].value
    location_fields = {f.name: f for f in location.value_models}
    assert set(location_fields.keys()) == {"city", "country", "postal_code"}
    assert not location_fields["postal_code"].required

    # Test UserSettings model
    settings = profile_fields["settings"].value
    settings_fields = {f.name: f for f in settings.value_models}
    assert set(settings_fields.keys()) == {
        "theme",
        "notifications_enabled",
        "preferred_language",
    }
    assert not settings_fields["theme"].required
    assert not settings_fields["notifications_enabled"].required
    assert not settings_fields["preferred_language"].required


# Test Action Response Wrappers
def test_action_response_wrappers(parsed_controller):
    """Test the structure of action response wrappers"""
    # Test sideeffect wrapper
    update_action = parsed_controller.actions["update_profile"]
    response_fields = {f.name: f for f in update_action.response_body.value_models}
    assert set(response_fields.keys()) == {"sideeffect", "passthrough"}

    # Test passthrough wrapper
    friends_action = parsed_controller.actions["get_friends"]
    friends_fields = {f.name: f for f in friends_action.response_body.value_models}
    assert set(friends_fields.keys()) == {"passthrough"}


# Define a self-referencing model
class CategoryNode(BaseModel):
    id: int
    name: str
    parent: Optional["CategoryNode"] = None
    children: list["CategoryNode"] = []
    created_at: datetime


# Update forward refs
CategoryNode.model_rebuild()


def test_parse_self_referencing_model(controller_parser):
    """Test parsing a Pydantic model with self-referencing fields"""
    # Parse the model
    parsed_model = controller_parser._parse_model(CategoryNode)

    # Test basic model properties
    assert parsed_model.model == CategoryNode
    assert len(parsed_model.superclasses) == 0

    # Get all field names
    field_names = {field.name for field in parsed_model.value_models}
    assert field_names == {"id", "name", "parent", "children", "created_at"}

    # Get fields by name for detailed testing
    fields = {f.name: f for f in parsed_model.value_models}

    # Test primitive fields
    assert fields["id"].value == int
    assert fields["id"].required == True
    assert fields["name"].value == str
    assert fields["name"].required == True
    assert fields["created_at"].value == datetime
    assert fields["created_at"].required == True

    # Test self-referencing fields
    parent_field = fields["parent"]
    assert not parent_field.required  # Optional field
    assert isinstance(parent_field.value, Or)
    self_reference = parent_field.value.children[0]
    assert isinstance(self_reference, SelfReference)
    assert self_reference.model == CategoryNode

    children_field = fields["children"]
    assert children_field.required == False  # Has default value
    assert hasattr(children_field.value, "children")  # Should have type info preserved

    # Verify isolated model contains all direct fields
    assert set(parsed_model.isolated_model.model_fields.keys()) == {
        "id",
        "name",
        "parent",
        "children",
        "created_at",
    }