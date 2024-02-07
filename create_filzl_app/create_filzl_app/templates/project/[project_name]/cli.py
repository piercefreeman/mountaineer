from click import command
from filzl.cli import handle_runserver, handle_watch


@command()
def runserver():
    handle_runserver(
        package="{{project_name}}",
        webservice="{{project_name}}.main:app",
        webcontroller="{{project_name}}.app:controller",
        port=5006,
    )


@command()
def watch():
    handle_watch(
        package="{{project_name}}",
        webcontroller="{{project_name}}.app:controller",
    )
