from filzl_daemons import models

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
