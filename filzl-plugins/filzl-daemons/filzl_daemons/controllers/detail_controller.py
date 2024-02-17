from collections import defaultdict
from datetime import datetime

from fastapi import Depends, Request
from filzl import LinkAttribute, ManagedViewPath, Metadata, RenderBase
from filzl.database import DatabaseDependencies
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from filzl_daemons.controllers.base_controller import DaemonControllerBase
from filzl_daemons.models import QueableStatus
from filzl_daemons.views import get_daemons_view_path


class ActionResult(BaseModel):
    id: int
    attempt_num: int
    finished_at: datetime
    exception: str | None
    exception_stack: str | None
    result_body: str | None


class Action(BaseModel):
    id: int
    registry_id: str
    input_body: str | None
    status: QueableStatus

    started_datetime: datetime | None
    ended_datetime: datetime | None
    created_at: datetime

    retry_current_attempt: int
    retry_max_attempts: int | None

    results: list[ActionResult]


class DaemonDetailRender(RenderBase):
    input_body: str
    result_body: str | None
    exception: str | None
    exception_stack: str | None
    launch_time: datetime
    end_time: datetime | None
    actions: list[Action]


class DaemonDetailController(DaemonControllerBase):
    url = "/admin/daemons/{instance_id}"
    view_path = (
        ManagedViewPath.from_view_root(
            get_daemons_view_path(""), package_root_link=None
        )
        / "daemons/detail/page.tsx"
    )

    async def render(
        self,
        instance_id: int,
        request: Request,
        db: AsyncSession = Depends(DatabaseDependencies.get_db_session),
    ) -> DaemonDetailRender:
        await self.require_admin(request)

        instance_query = select(
            self.local_model_definition.DaemonWorkflowInstance
        ).where(self.local_model_definition.DaemonWorkflowInstance.id == instance_id)
        instance_raw = await db.execute(instance_query)
        instance = instance_raw.scalars().first()
        if instance is None:
            raise ValueError(f"Instance with id {instance_id} not found")

        actions_query = (
            select(self.local_model_definition.DaemonAction)
            .where(self.local_model_definition.DaemonAction.instance_id == instance_id)
            .order_by(col(self.local_model_definition.DaemonAction.created_at).desc())
        )
        actions_raw = await db.execute(actions_query)
        actions = actions_raw.scalars().all()

        action_results_query = (
            select(self.local_model_definition.DaemonActionResult)
            .where(
                self.local_model_definition.DaemonActionResult.instance_id
                == instance_id
            )
            .order_by(
                col(self.local_model_definition.DaemonActionResult.attempt_num).desc()
            )
        )
        action_results_raw = await db.execute(action_results_query)
        action_results = action_results_raw.scalars().all()

        action_results_by_action = defaultdict(list)
        for action_result in action_results:
            action_results_by_action[action_result.action_id].append(action_result)

        parsed_actions: list[Action] = []
        for action in actions:
            assert action.id
            parsed_results: list[ActionResult] = []
            for result in action_results_by_action[action.id]:
                assert result.id
                parsed_results.append(
                    ActionResult(
                        id=result.id,
                        attempt_num=result.attempt_num,
                        finished_at=result.finished_at,
                        exception=result.exception,
                        exception_stack=result.exception_stack,
                        result_body=result.result_body,
                    )
                )

            parsed_actions.append(
                Action(
                    id=action.id,
                    created_at=action.created_at,
                    input_body=action.input_body,
                    registry_id=action.registry_id,
                    status=action.status,
                    started_datetime=action.started_datetime,
                    ended_datetime=action.ended_datetime,
                    retry_current_attempt=action.retry_current_attempt,
                    retry_max_attempts=action.retry_max_attempts,
                    results=parsed_results,
                )
            )

        return DaemonDetailRender(
            input_body=instance.input_body,
            result_body=instance.result_body,
            exception=instance.exception,
            exception_stack=instance.exception_stack,
            launch_time=instance.launch_time,
            end_time=instance.end_time,
            actions=parsed_actions,
            metadata=Metadata(
                title="Daemons | Detail",
                links=[
                    LinkAttribute(rel="stylesheet", href="/static/daemons_main.css"),
                ],
                ignore_global_metadata=True,
            ),
        )
