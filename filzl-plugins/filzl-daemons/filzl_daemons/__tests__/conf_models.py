from tempfile import TemporaryDirectory
import pytest
from sqlalchemy import Engine
from sqlmodel import SQLModel, create_engine, Session
from filzl_daemons import models
from pathlib import Path
from filzl_daemons.workflow import Daemon

#
# We need to re-implement the models to add the table=True flag
# so we actually create them when we create the larger metadata.
#

class DaemonWorkflowInstance(models.DaemonWorkflowInstance, table=True):
    pass

class WorkerStatus(models.WorkerStatus, table=True):
    pass

class DaemonAction(models.DaemonAction, table=True):
    pass

class DaemonActionResult(models.DaemonActionResult, table=True):
    pass

LOCAL_MODEL_DEFINITION = models.LocalModelDefinition(
    DaemonWorkflowInstance=DaemonWorkflowInstance,
    WorkerStatus=WorkerStatus,
    DaemonAction=DaemonAction,
    DaemonActionResult=DaemonActionResult,
)
