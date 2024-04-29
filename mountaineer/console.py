# Separated from logging.py to isolate build-time dependencies
# from ones required by actual deployments
from rich.console import Console

CONSOLE = Console()
ERROR_CONSOLE = Console(stderr=True)
