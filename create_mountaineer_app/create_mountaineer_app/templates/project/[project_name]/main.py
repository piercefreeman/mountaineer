from fastapi import FastAPI

from {{project_name}}.app import mountaineer

# Expose for ASGI
app = FastAPI()
app.mount(path="/", app=mountaineer, name="website")
