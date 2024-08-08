from click import command, option
from mountaineer.cli import handle_build, handle_runserver, handle_watch


@command()
@option("--port", default=5006)
@option("--host", default="127.0.0.1", help="Host to run the server on")
def runserver(port, host):
    handle_runserver(
        package="ci_webapp",
        webservice="ci_webapp.main:app",
        webcontroller="ci_webapp.app:controller",
        port=port,
        host=host,
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
