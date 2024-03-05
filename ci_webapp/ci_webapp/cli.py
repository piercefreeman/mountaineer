from click import command
from mountaineer.cli import handle_runserver, handle_watch


@command()
def runserver():
    handle_runserver(
        package="ci_webapp",
        webservice="ci_webapp.main:app",
        webcontroller="ci_webapp.app:controller",
        port=5006,
        subscribe_to_mountaineer=True,
    )


@command()
def watch():
    handle_watch(
        package="ci_webapp",
        webcontroller="ci_webapp.app:controller",
        subscribe_to_mountaineer=True,
    )
