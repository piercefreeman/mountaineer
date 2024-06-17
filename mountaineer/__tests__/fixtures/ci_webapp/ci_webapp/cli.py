from click import command, option
from mountaineer.cli import handle_build, handle_runserver, handle_watch


@command()
@option("--port", default=5006)
def runserver(port):
    handle_runserver(
        package="ci_webapp",
        webservice="ci_webapp.main:app",
        webcontroller="ci_webapp.app:controller",
        port=port,
        subscribe_to_mountaineer=True,
    )


@command()
def watch():
    handle_watch(
        package="ci_webapp",
        webcontroller="ci_webapp.app:controller",
        subscribe_to_mountaineer=True,
    )


@command()
def build():
    handle_build(
        webcontroller="ci_webapp.app:controller",
    )
