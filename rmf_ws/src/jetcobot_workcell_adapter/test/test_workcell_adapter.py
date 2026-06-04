import pytest
import rclpy
from jetcobot_workcell_msgs.msg import WorkcellState
from rmf_ingestor_msgs.msg import IngestorRequest, IngestorRequestItem, IngestorResult

from jetcobot_workcell_adapter.workcell_adapter import JetCobotWorkcellAdapter


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
def adapter():
    node = JetCobotWorkcellAdapter(
        target_guid="warehouse_pick_place_jetcobot1",
        arm_name="jetcobot1",
        state_publish_frequency=100.0,
        arm_state_timeout_sec=60.0,
    )
    node._command_pub = FakePublisher()
    node._result_pub = FakePublisher()
    node._state_pub = FakePublisher()
    yield node
    node.destroy_node()


def _request(request_guid="mission_abc-pick-place", target_guid=None):
    msg = IngestorRequest()
    msg.request_guid = request_guid
    msg.target_guid = target_guid or "warehouse_pick_place_jetcobot1"
    msg.transporter_type = "pinky"

    item = IngestorRequestItem()
    item.type_guid = "towel"
    item.quantity = 0
    item.compartment_name = ""
    msg.items.append(item)
    return msg


def _arm_state(
    *,
    available=True,
    command_active=False,
    last_command_id="",
    last_command_status="",
):
    msg = WorkcellState()
    msg.arm_name = "jetcobot1"
    msg.state = "idle" if available else "reserved"
    msg.available = available
    msg.command_active = command_active
    msg.last_command_id = last_command_id
    msg.last_command_status = last_command_status
    return msg


def test_managed_request_publishes_acknowledged(adapter):
    adapter._on_ingestor_request(_request())

    assert adapter._result_pub.messages[-1].status == IngestorResult.ACKNOWLEDGED
    assert adapter._command_pub.messages == []


def test_unmanaged_request_is_ignored(adapter):
    adapter._on_ingestor_request(_request(target_guid="other_workcell"))

    assert adapter._result_pub.messages == []
    assert adapter._command_pub.messages == []


def test_available_arm_receives_pick_and_place_command(adapter):
    adapter._on_arm_state(_arm_state(available=True))
    adapter._on_ingestor_request(_request())

    command = adapter._command_pub.messages[-1]
    assert command.arm_name == "jetcobot1"
    assert command.command_id == "mission_abc-pick-place"
    assert command.command_type == "pick_and_place"
    assert command.mission_id == "mission_abc"
    assert list(command.item_type_guids) == ["towel"]


def test_busy_arm_queues_until_available(adapter):
    adapter._on_arm_state(_arm_state(available=False, command_active=True))
    adapter._on_ingestor_request(_request())

    assert adapter._command_pub.messages == []
    assert adapter._request_guid_queue() == ["mission_abc-pick-place"]

    adapter._on_arm_state(_arm_state(available=True, command_active=False))

    assert adapter._command_pub.messages[-1].command_id == "mission_abc-pick-place"
    assert adapter._request_guid_queue() == ["mission_abc-pick-place"]


def test_succeeded_arm_state_publishes_success(adapter):
    adapter._on_arm_state(_arm_state(available=True))
    adapter._on_ingestor_request(_request())
    adapter._on_arm_state(
        _arm_state(
            available=True,
            last_command_id="mission_abc-pick-place",
            last_command_status="succeeded",
        )
    )

    assert adapter._result_pub.messages[-1].status == IngestorResult.SUCCESS
    assert adapter._request_guid_queue() == []


@pytest.mark.parametrize("status", ["failed", "rejected", "canceled"])
def test_failed_arm_states_publish_failed(adapter, status):
    adapter._on_arm_state(_arm_state(available=True))
    adapter._on_ingestor_request(_request())
    adapter._on_arm_state(
        _arm_state(
            available=True,
            last_command_id="mission_abc-pick-place",
            last_command_status=status,
        )
    )

    assert adapter._result_pub.messages[-1].status == IngestorResult.FAILED
