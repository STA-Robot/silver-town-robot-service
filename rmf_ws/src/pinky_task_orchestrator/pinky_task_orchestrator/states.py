from enum import Enum


class WorkflowState(str, Enum):
    """Application-level task state, separate from Pinky drive state."""

    IDLE = "idle"
    CALLED = "called"
    DISPATCHING_TO_PICKUP = "dispatching_to_pickup"
    MOVING_TO_PICKUP = "moving_to_pickup"
    WAITING_FOR_LOAD = "waiting_for_load"
    DISPATCHING_TO_DROPOFF = "dispatching_to_dropoff"
    MOVING_TO_DROPOFF = "moving_to_dropoff"
    WAITING_FOR_UNLOAD = "waiting_for_unload"
    RETURNING = "returning"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    CANCELED = "canceled"


TERMINAL_STATES = {
    WorkflowState.COMPLETED,
    WorkflowState.BLOCKED,
    WorkflowState.CANCELED,
}
