from __future__ import annotations

import asyncio
import multiprocessing
from datetime import datetime
from typing import Any
from uuid import uuid4

from filzl_daemons.db import PostgresBackend
from filzl_daemons.io import safe_task
from filzl_daemons.logging import LOGGER


class WorkerBase(multiprocessing.Process):
    def __init__(self, *, backend: PostgresBackend):
        super().__init__()
        self.backend = backend
        self.process_id = uuid4()
        self.custom_worker_args: dict[str, Any] = {}

    async def init_worker_db(self):
        """
        Create a new tracking object for this worker in the database.
        """
        # Initialize the object that tracks this worker
        async with self.backend.session_maker() as session:
            worker = self.backend.local_models.WorkerStatus(
                internal_process_id=self.process_id,
                is_draining=False,
                last_ping=datetime.utcnow(),
                launch_time=datetime.utcnow(),
                **self.custom_worker_args,
            )
            session.add(worker)
            await session.commit()

        return worker.id

    async def start(self):
        self.worker_id = await self.init_worker_db()

        super().start()

    def worker_init(self):
        # Only used by some workers, but added here for ease of canceling
        # the process ping loop if the worker is draining
        self.is_draining = False

    def ping(self, ping_interval: int = 30):
        """
        Report health of this worker process to the backend.
        """

        async def run_single_ping():
            if self.worker_id is None:
                LOGGER.warning("Worker ID not set during update...")
                return

            LOGGER.debug(f"Pinging update for worker {self.worker_id}")
            async with self.backend.get_object_by_id(
                self.backend.local_models.WorkerStatus, self.worker_id
            ) as (worker, session):
                worker.last_ping = datetime.utcnow()
                worker.is_draining = self.is_draining
                await session.commit()

        async def shutdown_on_drain():
            while True:
                await asyncio.sleep(1)
                if self.is_draining:
                    break

            # Final shutdown
            await run_single_ping()

        async def run_ping():
            # Then update it periodically
            while True:
                await run_single_ping()
                await asyncio.sleep(ping_interval)

        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            asyncio.wait(
                [
                    loop.create_task(safe_task(run_ping)()),
                    loop.create_task(safe_task(shutdown_on_drain)()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
        )
