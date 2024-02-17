from fastapi import Depends, Request
from sqlalchemy import text
from filzl import ManagedViewPath, Metadata, RenderBase, LinkAttribute
from filzl.database import DatabaseDependencies
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from filzl_daemons.controllers.base_controller import DaemonControllerBase
from filzl_daemons.views import get_daemons_view_path
from datetime import datetime
from filzl_daemons.models import QueableStatus


class InstanceStatus(BaseModel):
    id: int

    workflow_name: str
    status: QueableStatus
    launch_time: datetime
    end_time: datetime | None
    current_worker_status_id: int | None

    model_config = {
        "from_attributes": True,
    }

class QueueStat(BaseModel):
    workflow_name: str
    count: int

class DaemonHomeRender(RenderBase):
    instances: list[InstanceStatus]
    stats: list[QueueStat]


class DaemonHomeController(DaemonControllerBase):
    url = "/admin/daemons"
    view_path = (
        ManagedViewPath.from_view_root(
            get_daemons_view_path(""), package_root_link=None
        )
        / "daemons/home/page.tsx"
    )

    async def render(
        self,
        request: Request,
        db: AsyncSession = Depends(DatabaseDependencies.get_db_session),
    ) -> DaemonHomeRender:
        await self.require_admin(request)

        query = select(self.local_model_definition.DaemonWorkflowInstance).limit(100)
        result = await db.execute(query)
        instances = result.scalars().all()

        result = await db.execute(
            text(
                f"SELECT COUNT(*), workflow_name FROM {self.local_model_definition.DaemonWorkflowInstance.__tablename__} WHERE status = :status GROUP BY workflow_name",
            ),
            {
                "status": QueableStatus.QUEUED,
            }
        )
        counts = result.all()
        print(counts)

        return DaemonHomeRender(
            instances=[
                InstanceStatus.model_validate(instance) for instance in instances
            ],
            stats=[
                QueueStat(
                    workflow_name=stat[1],
                    count=stat[0],
                )
                for stat in counts
            ],
            metadata=Metadata(
                title="Daemons | Home",
                links=[
                    LinkAttribute(rel="stylesheet", href="/static/daemon_main.css"),
                ]
            )
        )
