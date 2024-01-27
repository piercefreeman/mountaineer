from filzl.app import AppController
from my_website.controllers.home import HomeController

app = AppController()
app.register(HomeController())
