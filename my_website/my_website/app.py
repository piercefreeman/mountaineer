from filzl.app import AppController
from my_website.controllers.home import HomeController

controller = AppController()
controller.register(HomeController())

app = controller.app
