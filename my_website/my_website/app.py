from filzl.app import AppController

from my_website.controllers.home import HomeController
from my_website.views import get_view_path

controller = AppController(view_root=get_view_path(""))
controller.register(HomeController())

app = controller.app
