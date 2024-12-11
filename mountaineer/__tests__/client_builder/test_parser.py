from enum import Enum
from tempfile import TemporaryDirectory
from typing import Optional
from pydantic import BaseModel
import pytest
from datetime import datetime

from mountaineer.actions.passthrough_dec import passthrough
from mountaineer.actions.sideeffect_dec import sideeffect
from mountaineer.app import AppController
from mountaineer.client_builder.parser import ControllerParser, EnumWrapper, ModelWrapper
from mountaineer.controller import ControllerBase
from pathlib import Path
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
    controller_parser: ControllerParser,
    app_controller: AppController
):
    """
    Test parsing of a complex controller with:
    - Multiple levels of model inheritance
    - Nested models with optional fields
    - Enum values
    - Both sideeffect and passthrough actions
    - Various field types including lists and optionals

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

    # The actual controller
    class UserDashboardController(ControllerBase):
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
                    version=1
                ),
                pending_notifications=5
            )

        @sideeffect
        def update_profile(self, update: ProfileUpdateRequest) -> ProfileUpdateResponse:
            # Implementation not needed for test
            pass

        @passthrough
        def get_friends(self, limit: int = 10) -> UserProfile:
            # Implementation not needed for test
            pass

    # Registering the controller adds necessary types
    controller = UserDashboardController()
    app_controller.register(controller)

    result = controller_parser.parse_controller(controller.__class__)

    # Assertions for ModelWrapper structures
    assert result.render is not None
    assert len(result.render.superclasses) == 0
    assert len(result.render.value_models) == 2  # user and pending_notifications

    # Check the UserProfile model wrapping
    user_field = next(f for f in result.render.value_models if f.name == "user")
    assert isinstance(user_field.value, ModelWrapper)
    profile_wrapper = user_field.value
    assert len(profile_wrapper.superclasses) == 2  # BaseStats and BaseMetadata
    assert len(profile_wrapper.value_models) == 7  # Direct fields excluding inherited ones

    # Check actions
    assert len(result.actions) == 2

    # Check update_profile action
    update_action = result.actions["update_profile"]
    assert update_action.request_body is not None
    assert len(update_action.request_body.value_models) == 2  # location and settings
    assert update_action.response_body is not None
    assert len(update_action.response_body.value_models) == 2  # success and updated_user

    # Check get_friends action
    friends_action = result.actions["get_friends"]
    assert friends_action.params[0].name == "limit"
    assert friends_action.params[0].value == int
    assert friends_action.params[0].required is False
    assert friends_action.response_body is not None  # Should wrap list[UserProfile]

    # Verify enum handling
    role_field = next(
        f for f in profile_wrapper.value_models
        if f.name == "role"
    )
    assert isinstance(role_field.value, EnumWrapper)
    assert role_field.value.enum == UserRole

    # Verify nested optional handling
    location_field = next(
        f for f in profile_wrapper.value_models
        if f.name == "location"
    )
    assert isinstance(location_field.value, ModelWrapper)
    postal_code_field = next(
        f for f in location_field.value.value_models
        if f.name == "postal_code"
    )
    assert postal_code_field.required is False
