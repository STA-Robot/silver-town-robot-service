import argparse
from collections import deque
from dataclasses import dataclass
import json
import sys
from typing import Any

from jetcobot_msgs.msg import ArmCommand, ArmState
import rclpy
from rclpy.node import Node
from rmf_ingestor_msgs.msg import IngestorRequest, IngestorResult, IngestorState
import yaml


COMMAND_PICK_AND_PLACE = "pick_and_place"
COMMAND_SUCCEEDED = "succeeded"
FINAL_FAILURE_STATUSES = {"failed", "rejected", "canceled"}
PICK_PLACE_SUFFIX = "-pick-place"


@dataclass
class PendingRequest:
    request: IngestorRequest
    arm_name: str


def load_adapter_config(config_file: str) -> dict[str, Any]:
    if not config_file:
        return {}

    with open(config_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def mission_id_from_request_guid(request_guid: str) -> str:
    if request_guid.endswith(PICK_PLACE_SUFFIX):
        return request_guid[: -len(PICK_PLACE_SUFFIX)]
    return request_guid


class JetCobotWorkcellAdapter(Node):
    def __init__(
        self,
        target_guid: str = "warehouse_pick_place_jetcobot1",
        arm_name: str = "jetcobot1",
        command_topic: str = "/jetcobot1/command",
        state_topic: str = "/jetcobot1/state",
        ingestor_request_topic: str = "/ingestor_requests",
        ingestor_state_topic: str = "/ingestor_states",
        ingestor_result_topic: str = "/ingestor_results",
        state_publish_frequency: float = 2.0,
        arm_state_timeout_sec: float = 5.0,
        qos_depth: int = 10,
    ):
        super().__init__("jetcobot_workcell_adapter")
        self.target_guid = str(target_guid)
        self.arm_name = str(arm_name)
        self.command_topic = str(command_topic)
        self.state_topic = str(state_topic)
        self.ingestor_request_topic = str(ingestor_request_topic)
        self.ingestor_state_topic = str(ingestor_state_topic)
        self.ingestor_result_topic = str(ingestor_result_topic)
        self.arm_state_timeout_sec = float(arm_state_timeout_sec)

        qos_depth = int(qos_depth)
        publish_period = 1.0 / max(float(state_publish_frequency), 0.1)

        self._queue: deque[PendingRequest] = deque()
        self._active_request: PendingRequest | None = None
        self._completed_request_ids: set[str] = set()
        self._last_arm_state: ArmState | None = None
        self._last_arm_state_time = None

        self._command_pub = self.create_publisher(
            ArmCommand,
            self.command_topic,
            qos_depth,
        )
        self._state_pub = self.create_publisher(
            IngestorState,
            self.ingestor_state_topic,
            qos_depth,
        )
        self._result_pub = self.create_publisher(
            IngestorResult,
            self.ingestor_result_topic,
            qos_depth,
        )
        self._request_sub = self.create_subscription(
            IngestorRequest,
            self.ingestor_request_topic,
            self._on_ingestor_request,
            qos_depth,
        )
        self._arm_state_sub = self.create_subscription(
            ArmState,
            self.state_topic,
            self._on_arm_state,
            qos_depth,
        )
        self._state_timer = self.create_timer(publish_period, self._publish_state)

        self.get_logger().info(
            f"JetCobot workcell adapter ready target={self.target_guid} "
            f"arm={self.arm_name} request={self.ingestor_request_topic} "
            f"result={self.ingestor_result_topic} command={self.command_topic} "
            f"state={self.state_topic}"
        )

    def _on_ingestor_request(self, request: IngestorRequest) -> None:
        if request.target_guid != self.target_guid:
            self.get_logger().debug(
                f"ignore ingestor request target={request.target_guid} "
                f"request_guid={request.request_guid}"
            )
            return

        if not request.request_guid:
            self.get_logger().warning("reject ingestor request without request_guid")
            self._publish_result("", IngestorResult.FAILED)
            return

        if self._is_known_request(request.request_guid):
            self.get_logger().debug(
                f"duplicate ingestor request request_guid={request.request_guid}"
            )
            self._publish_result(request.request_guid, IngestorResult.ACKNOWLEDGED)
            return

        pending = PendingRequest(request=request, arm_name=self.arm_name)
        self._queue.append(pending)
        self._publish_result(request.request_guid, IngestorResult.ACKNOWLEDGED)
        self.get_logger().info(
            f"accepted ingestor request request_guid={request.request_guid} "
            f"target={request.target_guid} queue={len(self._queue)}"
        )
        self._try_dispatch_next()
        self._publish_state()

    def _is_known_request(self, request_guid: str) -> bool:
        if request_guid in self._completed_request_ids:
            return True
        if self._active_request and self._active_request.request.request_guid == request_guid:
            return True
        return any(entry.request.request_guid == request_guid for entry in self._queue)

    def _on_arm_state(self, state: ArmState) -> None:
        if state.arm_name and state.arm_name != self.arm_name:
            return

        self._last_arm_state = state
        self._last_arm_state_time = self.get_clock().now()

        if self._active_request is None:
            self._try_dispatch_next()
            self._publish_state()
            return

        request_guid = self._active_request.request.request_guid
        if state.last_command_id != request_guid:
            self._publish_state()
            return

        if state.last_command_status == COMMAND_SUCCEEDED:
            self._finish_active_request(IngestorResult.SUCCESS, state.message)
        elif state.last_command_status in FINAL_FAILURE_STATUSES:
            self._finish_active_request(IngestorResult.FAILED, state.message)
        else:
            self._publish_state()

    def _finish_active_request(self, status: int, message: str) -> None:
        if self._active_request is None:
            return

        request_guid = self._active_request.request.request_guid
        self._completed_request_ids.add(request_guid)
        self._publish_result(request_guid, status)
        status_name = "success" if status == IngestorResult.SUCCESS else "failed"
        self.get_logger().info(
            f"finished workcell request request_guid={request_guid} "
            f"status={status_name} message={message}"
        )
        self._active_request = None
        self._try_dispatch_next()
        self._publish_state()

    def _try_dispatch_next(self) -> None:
        if self._active_request is not None or not self._queue:
            return
        if not self._arm_can_accept_request():
            return

        pending = self._queue.popleft()
        self._active_request = pending
        command = self._build_workcell_command(pending.request, pending.arm_name)
        self._command_pub.publish(command)
        self.get_logger().info(
            f"published workcell command command_id={command.command_id} "
            f"arm={command.arm_name} items={list(command.item_type_guids)}"
        )

    def _arm_can_accept_request(self) -> bool:
        if self._last_arm_state is None or self._arm_state_is_stale():
            return False
        return bool(self._last_arm_state.available) and not bool(
            self._last_arm_state.command_active
        )

    def _arm_state_is_stale(self) -> bool:
        if self._last_arm_state_time is None:
            return True
        age = (self.get_clock().now() - self._last_arm_state_time).nanoseconds
        return age > int(self.arm_state_timeout_sec * 1_000_000_000)

    def _build_workcell_command(
        self,
        request: IngestorRequest,
        arm_name: str,
    ) -> ArmCommand:
        command = ArmCommand()
        command.header.stamp = self.get_clock().now().to_msg()
        command.arm_name = arm_name
        command.command_id = request.request_guid
        command.command_type = COMMAND_PICK_AND_PLACE
        command.mission_id = mission_id_from_request_guid(request.request_guid)
        command.item_type_guids = self._item_type_guids(request)
        command.payload_json = json.dumps(
            {
                "target_guid": request.target_guid,
                "transporter_type": request.transporter_type,
                "items": [
                    {
                        "type_guid": item.type_guid,
                        "quantity": int(item.quantity),
                        "compartment_name": item.compartment_name,
                    }
                    for item in request.items
                ],
            },
            sort_keys=True,
        )
        return command

    def _item_type_guids(self, request: IngestorRequest) -> list[str]:
        result = []
        seen = set()
        for item in request.items:
            type_guid = item.type_guid.strip()
            if type_guid and type_guid not in seen:
                seen.add(type_guid)
                result.append(type_guid)
        return result

    def _publish_result(self, request_guid: str, status: int) -> None:
        result = IngestorResult()
        result.time = self.get_clock().now().to_msg()
        result.request_guid = request_guid
        result.source_guid = self.target_guid
        result.status = status
        self._result_pub.publish(result)

    def _publish_state(self) -> None:
        state = IngestorState()
        state.time = self.get_clock().now().to_msg()
        state.guid = self.target_guid
        state.mode = self._ingestor_mode()
        state.request_guid_queue = self._request_guid_queue()
        state.seconds_remaining = self._seconds_remaining()
        self._state_pub.publish(state)

    def _ingestor_mode(self) -> int:
        if self._last_arm_state is None or self._arm_state_is_stale():
            return IngestorState.OFFLINE
        if self._active_request is not None or self._queue:
            return IngestorState.BUSY
        if not self._arm_can_accept_request():
            return IngestorState.BUSY
        return IngestorState.IDLE

    def _request_guid_queue(self) -> list[str]:
        request_guids = []
        if self._active_request is not None:
            request_guids.append(self._active_request.request.request_guid)
        request_guids.extend(entry.request.request_guid for entry in self._queue)
        return request_guids

    def _seconds_remaining(self) -> float:
        if self._active_request is None or self._last_arm_state is None:
            return 0.0
        return float(self._last_arm_state.seconds_remaining)


def main(argv=sys.argv):
    rclpy.init(args=argv)
    args_without_ros = rclpy.utilities.remove_ros_args(argv)

    parser = argparse.ArgumentParser(
        prog="workcell_adapter",
        description="Bridge RMF ingestor requests to JetCobot workcell commands.",
    )
    parser.add_argument("--config-file", default="")
    args = parser.parse_args(args_without_ros[1:])

    config = load_adapter_config(args.config_file)
    node = JetCobotWorkcellAdapter(
        target_guid=config.get("target_guid", "warehouse_pick_place_jetcobot1"),
        arm_name=config.get("arm_name", "jetcobot1"),
        command_topic=config.get("command_topic", "/jetcobot1/command"),
        state_topic=config.get("state_topic", "/jetcobot1/state"),
        ingestor_request_topic=config.get(
            "ingestor_request_topic",
            "/ingestor_requests",
        ),
        ingestor_state_topic=config.get("ingestor_state_topic", "/ingestor_states"),
        ingestor_result_topic=config.get(
            "ingestor_result_topic",
            "/ingestor_results",
        ),
        state_publish_frequency=float(config.get("state_publish_frequency", 2.0)),
        arm_state_timeout_sec=float(config.get("arm_state_timeout_sec", 5.0)),
        qos_depth=int(config.get("qos_depth", 10)),
    )

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main(sys.argv)
