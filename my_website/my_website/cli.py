from click import command


@command()
def runserver():
    from uvicorn import run

    run("my_website.app:app", port=5006, reload=True, access_log=False)