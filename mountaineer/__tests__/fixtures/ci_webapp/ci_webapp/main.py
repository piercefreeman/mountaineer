from fastapi import FastAPI

from ci_webapp.app import mountaineer

# Expose for ASGI
app = FastAPI()
app.mount(path="/", app=mountaineer, name="website")
