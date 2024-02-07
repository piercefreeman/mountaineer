from uuid import uuid4

from locust import HttpUser, between, task


class SSRTest(HttpUser):
    """
    Load test the server SSR logic
    """

    wait_time = between(1, 2)

    def on_start(self):
        pass

    @task
    def simple_rendering(self):
        self.client.get("/")
        self.client.get(f"/detail/{uuid4()}/")

    @task
    def complex_rendering(self):
        self.client.get(f"/complex/{uuid4()}/")
