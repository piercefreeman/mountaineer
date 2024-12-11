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
    ModelWrapper,
)
from mountaineer.controller import ControllerBase
from mountaineer.render import RenderBase


@pytest.fixture
def controller_parser():
    return ControllerParser()


@pytest.fixture
def app_controller():
    with TemporaryDirectory() as temp_dir_name:
        temp_view_path = Path(temp_dir_name)
        app_controller = AppController(view_root=temp_view_path)
        yield app_controller


def test_complex_controller_parsing(
    controller_parser: ControllerParser, app_controller: AppController
):
    """
    Test parsing of a complex controller with field-specific assertions to verify:
    - Controller inheritance structure and method inheritance
    - Field names and types in models
    - Action parameters and return types
    - Optional fields and default values
    - Enum handling
    - Passthrough/sideeffect wrapper handling
    """

    # Define our enum
    class UserRole(Enum):
        ADMIN = "admin"
        USER = "user"
        GUEST = "guest"

    # Base models for inheritance
    class BaseStats(BaseModel):
        created_at: datetime
        updated_at: datetime

    class BaseMetadata(BaseModel):
        version: int
        is_active: bool = True

    # Nested models
    class Location(BaseModel):
        city: str
        country: str
        postal_code: Optional[str] = None

    class UserSettings(BaseModel):
        theme: str = "light"
        notifications_enabled: bool = True
        preferred_language: str = "en"

    # Complex inherited model for responses
    class UserProfile(BaseStats, BaseMetadata):
        id: int
        username: str
        role: UserRole
        location: Location
        settings: UserSettings
        friends: list[int] = []
        last_login: Optional[datetime] = None

    # Response models for base functionality
    class SystemStatus(BaseModel):
        status: bool
        last_check: datetime

    class UserRoleResponse(BaseModel):
        role: UserRole
        permissions: list[str]

    # Models for the controller's render and actions
    class DashboardData(RenderBase):
        user: UserProfile
        pending_notifications: int = 0

    class ProfileUpdateRequest(BaseModel):
        location: Optional[Location] = None
        settings: Optional[UserSettings] = None

    class ProfileUpdateResponse(BaseModel):
        success: bool
        updated_user: UserProfile

    # Base controller with shared functionality
    class BaseController(ControllerBase):
        @passthrough
        def get_system_status(self) -> SystemStatus:
            pass

    # Intermediate controller adding user-related functionality
    class SharedController(BaseController):
        @passthrough
        def shared_friends(self, limit: int = 10) -> UserProfile:
            pass

        @passthrough
        def get_user_role(self) -> UserRoleResponse:
            pass

    # Final controller implementing dashboard functionality
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
            pass

        @passthrough
        def get_friends(self, limit: int = 10) -> UserProfile:
            pass

    # Register controller
    controller = UserDashboardController()
    app_controller.register(controller)

    result = controller_parser.parse_controller(controller.__class__)

    # Test controller inheritance structure
    assert len(result.superclasses) == 2  # Should have SharedController and BaseController
    shared_controller = result.superclasses[0]
    base_controller = result.superclasses[1]

    # Verify BaseController actions
    assert set(base_controller.actions.keys()) == {"get_system_status"}
    system_status_action = base_controller.actions["get_system_status"]
    assert system_status_action.response_body is not None
    assert len(system_status_action.params) == 0

    # Verify get_system_status response structure (passthrough wrapped)
    system_fields = {f.name: f for f in system_status_action.response_body.value_models}
    assert set(system_fields.keys()) == {"passthrough"}
    system_status_wrapper = system_fields["passthrough"]
    assert isinstance(system_status_wrapper.value, ModelWrapper)

    # Verify actual SystemStatus fields
    status_fields = {f.name: f for f in system_status_wrapper.value.value_models}
    assert set(status_fields.keys()) == {"status", "last_check"}
    assert status_fields["status"].value == bool
    assert status_fields["status"].required
    assert status_fields["last_check"].value == datetime
    assert status_fields["last_check"].required

    # Verify SharedController actions
    assert set(shared_controller.actions.keys()) == {"shared_friends", "get_user_role"}

    # Check shared_friends action
    shared_friends_action = shared_controller.actions["shared_friends"]
    assert len(shared_friends_action.params) == 1
    assert shared_friends_action.params[0].name == "limit"
    assert shared_friends_action.params[0].value == int
    assert not shared_friends_action.params[0].required  # Has default value

    # Verify shared_friends response structure (passthrough wrapped)
    friends_fields = {f.name: f for f in shared_friends_action.response_body.value_models}
    assert set(friends_fields.keys()) == {"passthrough"}
    friends_wrapper = friends_fields["passthrough"]
    assert isinstance(friends_wrapper.value, ModelWrapper)

    # Check get_user_role action
    user_role_action = shared_controller.actions["get_user_role"]
    assert len(user_role_action.params) == 0

    # Verify get_user_role response structure (passthrough wrapped)
    role_fields = {f.name: f for f in user_role_action.response_body.value_models}
    assert set(role_fields.keys()) == {"passthrough"}
    role_wrapper = role_fields["passthrough"]
    assert isinstance(role_wrapper.value, ModelWrapper)

    # Verify UserRoleResponse fields
    role_response_fields = {f.name: f for f in role_wrapper.value.value_models}
    assert set(role_response_fields.keys()) == {"role", "permissions"}
    assert isinstance(role_response_fields["role"].value, EnumWrapper)
    assert role_response_fields["role"].value.enum == UserRole
    assert role_response_fields["role"].required
    assert role_response_fields["permissions"].required

    # Verify UserDashboardController's direct actions
    assert set(result.actions.keys()) == {"update_profile", "get_friends"}

    # Test render model structure
    assert result.render is not None
    assert len(result.render.superclasses) == 0

    # Verify DashboardData fields
    dashboard_fields = {f.name: f for f in result.render.value_models}
    assert set(dashboard_fields.keys()) == {"user", "pending_notifications"}
    assert dashboard_fields["pending_notifications"].value == int
    assert not dashboard_fields["pending_notifications"].required  # Has default value

    # Check UserProfile structure
    user_field = dashboard_fields["user"]
    assert isinstance(user_field.value, ModelWrapper)
    profile_wrapper = user_field.value

    # Verify UserProfile inheritance
    assert len(profile_wrapper.superclasses) == 2
    superclass_names = {sc.model.__name__ for sc in profile_wrapper.superclasses}
    assert superclass_names == {"BaseStats", "BaseMetadata"}

    # Verify BaseStats fields
    base_stats = next(sc for sc in profile_wrapper.superclasses if sc.model.__name__ == "BaseStats")
    base_stats_fields = {f.name: f for f in base_stats.value_models}
    assert set(base_stats_fields.keys()) == {"created_at", "updated_at"}
    assert all(f.required for f in base_stats_fields.values())

    # Verify BaseMetadata fields
    base_metadata = next(sc for sc in profile_wrapper.superclasses if sc.model.__name__ == "BaseMetadata")
    metadata_fields = {f.name: f for f in base_metadata.value_models}
    assert set(metadata_fields.keys()) == {"version", "is_active"}
    assert metadata_fields["version"].required
    assert not metadata_fields["is_active"].required  # Has default value

    # Verify UserProfile direct fields
    profile_fields = {f.name: f for f in profile_wrapper.value_models}
    assert set(profile_fields.keys()) == {
        "id", "username", "role", "location", "settings",
        "friends", "last_login"
    }

    # Check specific UserProfile field properties
    assert profile_fields["id"].required
    assert profile_fields["username"].required
    assert isinstance(profile_fields["role"].value, EnumWrapper)
    assert profile_fields["role"].value.enum == UserRole
    assert not profile_fields["last_login"].required  # Optional field
    #assert profile_fields["friends"].required  # Has default value but still required

    # Verify nested Location model
    location_field = profile_fields["location"]
    assert isinstance(location_field.value, ModelWrapper)
    location_fields = {f.name: f for f in location_field.value.value_models}
    assert set(location_fields.keys()) == {"city", "country", "postal_code"}
    assert location_fields["city"].required
    assert location_fields["country"].required
    assert not location_fields["postal_code"].required  # Optional field

    # Verify nested UserSettings model
    settings_field = profile_fields["settings"]
    assert isinstance(settings_field.value, ModelWrapper)
    settings_fields = {f.name: f for f in settings_field.value.value_models}
    assert set(settings_fields.keys()) == {"theme", "notifications_enabled", "preferred_language"}
    assert not settings_fields["theme"].required  # Has default value
    assert not settings_fields["notifications_enabled"].required  # Has default value
    assert not settings_fields["preferred_language"].required  # Has default value

    # Test update_profile action
    update_action = result.actions["update_profile"]

    # Verify request body
    assert update_action.request_body is not None
    update_fields = {f.name: f for f in update_action.request_body.value_models}
    assert set(update_fields.keys()) == {"location", "settings"}
    assert not update_fields["location"].required  # Optional fields
    assert not update_fields["settings"].required

    # Verify update_profile response (sideeffect wrapped)
    assert update_action.response_body is not None
    response_fields = {f.name: f for f in update_action.response_body.value_models}
    assert set(response_fields.keys()) == {"sideeffect", "passthrough"}

    # Verify the nested response structure
    passthrough_model = response_fields["passthrough"].value
    assert isinstance(passthrough_model, ModelWrapper)
    passthrough_fields = {f.name: f for f in passthrough_model.value_models}
    assert set(passthrough_fields.keys()) == {"success", "updated_user"}
    assert passthrough_fields["success"].required
    assert passthrough_fields["updated_user"].required

    # Verify the sideeffect structure (should match passthrough)
    sideeffect_model = response_fields["sideeffect"].value
    assert isinstance(sideeffect_model, ModelWrapper)
    sideeffect_fields = {f.name: f for f in sideeffect_model.value_models}
    assert set(sideeffect_fields.keys()) == {"user", "pending_notifications"}
    assert sideeffect_fields["user"].required
    assert not sideeffect_fields["pending_notifications"].required

    # Check get_friends action
    friends_action = result.actions["get_friends"]
    assert len(friends_action.params) == 1
    limit_param = friends_action.params[0]
    assert limit_param.name == "limit"
    assert limit_param.value == int
    assert not limit_param.required  # Has default value

    # Verify get_friends response (passthrough wrapped)
    assert friends_action.response_body is not None
    get_friends_fields = {f.name: f for f in friends_action.response_body.value_models}
    assert set(get_friends_fields.keys()) == {"passthrough"}
    get_friends_wrapper = get_friends_fields["passthrough"]
    assert isinstance(get_friends_wrapper.value, ModelWrapper)
    # UserProfile fields already verified above
