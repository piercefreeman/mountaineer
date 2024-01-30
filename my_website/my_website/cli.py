from click import command
from filzl.watch import CallbackDefinition, CallbackType, PackageWatchdog


@command()
def runserver():
    from uvicorn import run

    run("my_website.app:app", port=5006, reload=True, access_log=False)


@command()
def watch():
    def update_build():
        print("SHOULD UPDATE!!")

    package_names = ["filzl", "my_website"]
    watchdog = PackageWatchdog(
        package_names,
        callbacks=[
            CallbackDefinition(
                CallbackType.CREATED | CallbackType.MODIFIED,
                update_build,
            )
        ],
    )
    watchdog.start_watching()
