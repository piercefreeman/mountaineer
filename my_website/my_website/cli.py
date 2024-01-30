from click import command
from filzl.cli import handle_runserver, handle_watch


@command()
def runserver():
    handle_runserver(
        package="my_website",
        webservice="my_website.app:app",
        webcontroller="my_website.app:controller",
        port=5006,
    )


@command()
def watch():
    handle_watch(
        package="my_website",
        webcontroller="my_website.app:controller",
    )
