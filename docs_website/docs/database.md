# Database

Mountaineer bundles common conventions for configuring a Postgres database with async connection handlers. This lets it plug and play easily with the async code that you're already writing for your controllers.

## Config

A configuration class is defined in `mountaineer.database` that you can use to configure your database connection. Make sure to register your downstream configuration with the `DatabaseConfig` if you want to use it. For the full list of configuration options and defaults, see the `DatabaseConfig` superclass.

```python
from mountaineer.database import DatabaseConfig
from mountaineer import ConfigBase

class AppConfig(DatabaseConfig, ConfigBase):
    POSTGRES_HOST: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_PORT: int = 5432
```

Since database hosts, usernames, and passwords change for development vs. production you'll always want to store these within an `.env` file in your local directory. During development these will just be injected dynamically via whatever configuration/secrets service you adopt. More on that later.

## Calling the database

Within your render and action functions, you'll have access to the `DatabaseDependencies`. The main entrypoint here will be the `get_db_session` dependency, which will give you a new async session to work with. It'll already be opened to a new transaction when your function is called.

Transactions are an internal concept of Postgres and most other SQL databases. They let you perform logic in an encapsolated chunk without actually writing their data to the database. This has the benefit that if you have an error partially through your logic, you can just rollback the transaction and the database will be left in the same state it was before you started. You can then try again later without the need to clean up any partial writes.

`SELECT` queries don't modify the database state, so these can be executed as-is within action functions.

For `INSERT`, `UPDATE`, and `DELETE` requests however - these modify the state of the database. So you'll want perform whatever logic you need and commit your changes at the end.

```python
from mountaineer.database import DatabaseDependencies

class HomeController(ControllerBase):
    ...

    @sideeffect
    async def add_todo(
        self,
        payload: NewTodoRequest,
        session: AsyncSession = Depends(DatabaseDependencies.get_db_session)
    ) -> None:
        new_todo =  TodoItem(description=payload.description)
        session.add(new_todo)
        await session.commit()
```

## Pooling

Most webapps are deployed in environments where they have multiple processes running, either on the same machine or separate servers. SQLAlchemy's default pool handling isn't well supported in these situations since it relies on a process-delineated connection pool. By default Mountaineer assumes that you'll deploy your database with a pooler closer to the database itself - something like PgBouncer, Odyssey, or HAProxy.
