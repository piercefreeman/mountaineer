from filzl.app import AppController

from my_website.controllers.complex import ComplexController
from my_website.controllers.detail import DetailController
from my_website.controllers.home import HomeController
from my_website.views import get_view_path

controller = AppController(view_root=get_view_path(""))
controller.register(HomeController())
controller.register(DetailController())
controller.register(ComplexController())
