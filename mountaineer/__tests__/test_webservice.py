import logging
from typing import Any, Generator
from unittest.mock import Mock, patch

import pytest
from rich.spinner import Spinner
from rich.text import Text

from mountaineer.webservice import (
    ServerStatus,
    configure_uvicorn_logging,
)


@pytest.fixture
def mock_console() -> Generator[Mock, Any, None]:
    with patch("mountaineer.webservice.CONSOLE") as mock:
        yield mock


@pytest.fixture
def server_status() -> ServerStatus:
    return ServerStatus(name="Test Server", emoticon="🚀")


@pytest.fixture
def mock_live() -> Generator[Mock, Any, None]:
    # We need to patch where the Live class is used, not where it's defined
    with patch("mountaineer.webservice.Live") as mock:
        mock_instance = Mock()
        mock.return_value = mock_instance
        yield mock_instance


class TestServerStatus:
    def test_initial_state(self, server_status: ServerStatus) -> None:
        """Test the initial state of ServerStatus"""
        assert server_status.name == "Test Server"
        assert server_status.emoticon == "🚀"
        assert server_status.status == "Starting server..."
        assert server_status.final_status is None
        assert server_status.url is None

    def test_update_without_url(self, server_status: ServerStatus) -> None:
        """Test updating status without URL"""
        # Test the spinner output
        server_status.update("Processing...", final=False)
        rendered = server_status.__rich__()

        # We know it should be a Spinner when not final
        assert isinstance(rendered, Spinner)
        # Get the text from the spinner's current state
        spinner_text = rendered.text
        assert "Processing..." == str(spinner_text)

    def test_update_with_url(self, server_status: ServerStatus) -> None:
        """Test updating status with URL"""
        test_url = "http://localhost:8000"
        server_status.update("Server ready", url=test_url, final=True)
        rendered = server_status.__rich__()

        # Get the plain text and check content
        assert isinstance(rendered, Text)
        assert "ready at" in rendered.plain
        assert test_url in rendered.plain


class TestUvicornLogging:
    @pytest.fixture(autouse=True)
    def setup_logging(
        self, mock_live: Mock, mock_console: Mock
    ) -> Generator[None, Any, None]:
        """Setup and teardown for logging tests"""
        # Store original loggers
        original_loggers: dict[str, dict[str, Any]] = {}
        logger_names = ["uvicorn", "uvicorn.error"]
        for name in logger_names:
            logger = logging.getLogger(name)
            original_loggers[name] = {
                "handlers": list(logger.handlers),
                "propagate": logger.propagate,
                "level": logger.level,
            }

        # Configure logging before each test
        configure_uvicorn_logging("Test Server", "🚀", "info")

        yield

        # Restore original loggers
        for name, config in original_loggers.items():
            logger = logging.getLogger(name)
            logger.handlers = config["handlers"]
            logger.propagate = config["propagate"]
            logger.setLevel(config["level"])

    def test_logger_configuration(self) -> None:
        """Test that loggers are configured correctly"""
        for name in ["uvicorn", "uvicorn.error"]:
            logger = logging.getLogger(name)
            # The loggers should be configured by the setup_logging fixture
            assert not logger.propagate
            assert not logger.handlers
            assert logger.level == logging.INFO

    def test_startup_logging_sequence(self, mock_live: Mock) -> None:
        """Test the full startup logging sequence"""
        logger = logging.getLogger("uvicorn")

        # Simulate the startup sequence with proper string formatting
        logger.info("Started server process [%s]", "12345")
        logger.info("Waiting for application startup")
        logger.info("Application startup complete")
        logger.info("Uvicorn running on %s %s:%s", "http", "127.0.0.1", "8000")

        # Verify the Live display lifecycle
        assert mock_live.start.called
