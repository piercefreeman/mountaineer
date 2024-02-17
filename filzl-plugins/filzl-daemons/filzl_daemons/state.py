from hashlib import sha256

from pydantic import BaseModel

from filzl_daemons.actions import ActionExecutionStub


class CurrentState(BaseModel):
    state: str


class StateUpdate(BaseModel):
    registry_id: str
    input_body: BaseModel | None


def init_state(input_payload: BaseModel):
    return CurrentState(
        state=sha256(input_payload.model_dump_json().encode()).hexdigest(),
    )


def update_state(state: CurrentState, metadata: ActionExecutionStub):
    state_hash = StateUpdate(
        registry_id=metadata.registry_id, input_body=metadata.input_body
    ).model_dump_json()
    current_state = sha256((state.state + state_hash).encode()).hexdigest()
    return CurrentState(
        state=current_state,
    )
