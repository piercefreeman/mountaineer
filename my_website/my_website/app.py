from filzl.app import AppController
from my_website.controllers.home import HomeController
from my_website.views import get_view_path

controller = AppController()
controller.register(HomeController())

app = controller.app


# We'll eventually want to refactor this out to be a standalone watch tool, so TS files can be build
# without the server having to run / all the associated warmup logic
# This is just a convenient place to put it because it's called once every time uvicorn detects that
# there is a client side change.
from filzl.client_interface.builder import build_client_code
build_client_code(controller, get_view_path(""))
