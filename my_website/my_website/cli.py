from click import command
from mountaineer.cli import handle_runserver, handle_watch


@command()
def runserver():
    handle_runserver(
        package="my_website",
        webservice="my_website.main:app",
        webcontroller="my_website.app:controller",
        port=5006,
        subscribe_to_fizl=True,
    )


@command()
def watch():
    handle_watch(
        package="my_website",
        webcontroller="my_website.app:controller",
        subscribe_to_fizl=True,
    )
