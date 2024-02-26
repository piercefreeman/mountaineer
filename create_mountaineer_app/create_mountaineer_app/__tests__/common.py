from time import sleep

import psycopg2
from click import secho
from psycopg2 import OperationalError

from create_mountaineer_app.generation import ProjectMetadata


def is_database_ready(metadata: ProjectMetadata):
    try:
        conn = psycopg2.connect(
            # Default parameters specified in the templated .env
            dbname=f"{metadata.project_name}_db",
            user=f"{metadata.project_name}",
            password=metadata.postgres_password,
            host="localhost",
            port=metadata.postgres_port,
        )
        conn.close()
        return True
    except OperationalError:
        return False


def wait_for_database_to_be_ready(metadata: ProjectMetadata, max_wait=10):
    while max_wait > 0:
        if is_database_ready(metadata):
            secho("Database is ready!", fg="green")
            break

        max_wait -= 1
        secho("Waiting for database to become ready...", fg="yellow")
        sleep(1)

    if max_wait == 0:
        raise Exception("Timed out waiting for database to be ready.")
