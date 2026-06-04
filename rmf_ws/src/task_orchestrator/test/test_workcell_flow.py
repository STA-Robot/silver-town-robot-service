import pytest
import rclpy
from rmf_ingestor_msgs.msg import IngestorResult

from task_orchestrator.task_orchestrator import (
    Mission,
    TaskOrchestrator,
    build_pick_place_ingestor_request,
)


class FakePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, msg):
        self.messages.append(msg)


@pytest.fixture(scope="module", autouse=True)
def rclpy_context():
    rclpy.init(args=None)
    yield
    rclpy.shutdown()


@pytest.fixture
def orchestrator():
    node = TaskOrchestrator(
        storage_full_default=True,
        workcell_target_guid="warehouse_pick_place_jetcobot1",
        workcell_item_type_guids=["towel", "cup"],
    )
    node.workcell_request_pub = FakePublisher()
    yield node
    node.destroy_node()


def _mission(state="table_task_submitted"):
    return Mission(
        mission_id="mission_abc",
        table_id="table_1",
        table_waypoint="table_1",
        state=state,
        assigned_robot="pinky1",
    )


def _workcell_result(request_guid, status):
    msg = IngestorResult()
    msg.request_guid = request_guid
    msg.source_guid = "warehouse_pick_place_jetcobot1"
    msg.status = status
    return msg


def test_build_pick_place_ingestor_request_contents():
    request = build_pick_place_ingestor_request(
        mission_id="mission_abc",
        target_guid="warehouse_pick_place_jetcobot1",
        transporter_type="pinky",
        item_type_guids=["towel", "cup"],
    )

    assert request.request_guid == "mission_abc-pick-place"
    assert request.target_guid == "warehouse_pick_place_jetcobot1"
    assert request.transporter_type == "pinky"
    assert [item.type_guid for item in request.items] == ["towel", "cup"]


def test_table_task_completion_with_full_storage_submits_warehouse(orchestrator):
    mission = _mission()
    calls = []
    orchestrator.submit_warehouse_task = lambda submitted: calls.append(submitted)

    orchestrator.on_table_task_completed(mission)

    assert mission.storage_full is True
    assert calls == [mission]


def test_warehouse_completion_publishes_ingestor_request(orchestrator):
    mission = _mission(state="warehouse_task_submitted")

    orchestrator.on_warehouse_task_completed(mission)

    request = orchestrator.workcell_request_pub.messages[-1]
    assert request.request_guid == "mission_abc-pick-place"
    assert request.target_guid == "warehouse_pick_place_jetcobot1"
    assert [item.type_guid for item in request.items] == ["towel", "cup"]
    assert mission.current_workcell_request_id == "mission_abc-pick-place"
    assert mission.state == "workcell_request_submitted"


def test_workcell_success_marks_mission_completed(orchestrator):
    mission = _mission(state="workcell_request_submitted")
    mission.current_workcell_request_id = "mission_abc-pick-place"
    orchestrator.missions_by_workcell_request_id[mission.current_workcell_request_id] = (
        mission
    )

    orchestrator._on_ingestor_result(
        _workcell_result("mission_abc-pick-place", IngestorResult.SUCCESS)
    )

    assert mission.state == "mission_completed"
    assert mission.current_workcell_request_id is None


def test_workcell_failure_marks_mission_intervention_required(orchestrator):
    mission = _mission(state="workcell_request_submitted")
    mission.current_workcell_request_id = "mission_abc-pick-place"
    orchestrator.missions_by_workcell_request_id[mission.current_workcell_request_id] = (
        mission
    )

    orchestrator._on_ingestor_result(
        _workcell_result("mission_abc-pick-place", IngestorResult.FAILED)
    )

    assert mission.state == "intervention_required"
    assert mission.current_workcell_request_id is None
