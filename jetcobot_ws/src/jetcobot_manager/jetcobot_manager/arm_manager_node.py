import sys
from collections import deque
from copy import deepcopy
from pathlib import Path
from typing import Any

import rclpy
import rclpy.executors
import yaml
from action_msgs.msg import GoalStatus
from ament_index_python.packages import get_package_share_directory
from jetcobot_workcell_msgs.action import PickPlace
from jetcobot_workcell_msgs.msg import WorkcellCommand, WorkcellState
from rclpy.action import ActionClient
from rclpy.node import Node


STATE_UNKNOWN = "unknown"
STATE_IDLE = "idle"
STATE_RESERVED = "reserved"
STATE_ALIGNING = "aligning"
STATE_PICKING = "picking"
STATE_HOMING = "homing"
STATE_BLOCKED = "blocked"
STATE_EMERGENCY = "emergency"

COMMAND_PICK_AND_PLACE = "pick_and_place"
COMMAND_STOP = "stop"
COMMAND_RESET = "reset"

COMMAND_ACCEPTED = "accepted"
COMMAND_SUCCEEDED = "succeeded"
COMMAND_FAILED = "failed"
COMMAND_REJECTED = "rejected"
COMMAND_CANCELED = "canceled"

DEFAULT_PICK_PLACE_STATE_MAP = {
    "GO_READY": STATE_HOMING,
    "SEARCHING": STATE_ALIGNING,
    "SERVO": STATE_ALIGNING,
    "OFFSET_MOVE": STATE_PICKING,
    "DESCENDING": STATE_PICKING,
    "GRIPPING": STATE_PICKING,
    "LIFTING": STATE_PICKING,
    "SERVO_FAILED": STATE_BLOCKED,
}

DEFAULT_PICK_PLACE_PROGRESS = {
    "GO_READY": 0.1,
    "SEARCHING": 0.2,
    "SERVO": 0.35,
    "OFFSET_MOVE": 0.55,
    "DESCENDING": 0.65,
    "GRIPPING": 0.75,
    "LIFTING": 0.85,
    "SERVO_FAILED": 0.0,
}


class ConfigError(ValueError):
    pass


def default_config_file() -> str:
    try:
        share_dir = get_package_share_directory("jetcobot_manager")
        return str(Path(share_dir) / "config" / "arm_manager.yaml")
    except Exception:
        return ""


def load_arm_manager_config(config_file: str) -> dict[str, Any]:
    if not config_file:
        raise ConfigError("config_file parameter is required")

    path = Path(config_file).expanduser()
    if not path.is_file():
        raise ConfigError(f"config file does not exist: {path}")

    with path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    return validate_arm_manager_config(config)


def validate_arm_manager_config(config: dict[str, Any]) -> dict[str, Any]:
    config = deepcopy(config)

    pick_place = config.setdefault("pick_place", {})
    if not isinstance(pick_place, dict):
        raise ConfigError("pick_place must be a mapping")
    pick_place.setdefault("action_name", "/pick_place")
    pick_place.setdefault("server_timeout", 5.0)
    pick_place.setdefault("seconds_estimate", 30.0)
    pick_place.setdefault("feedback_iteration_budget", 150)
    pick_place.setdefault("task_id_source", "command_id")
    state_map = pick_place.setdefault("state_map", dict(DEFAULT_PICK_PLACE_STATE_MAP))
    if not isinstance(state_map, dict):
        raise ConfigError("pick_place.state_map must be a mapping")
    pick_place["state_map"] = {
        str(server_state).upper(): str(manager_state)
        for server_state, manager_state in state_map.items()
    }
    pick_place["server_timeout"] = float(pick_place["server_timeout"])
    pick_place["seconds_estimate"] = float(pick_place["seconds_estimate"])
    pick_place["feedback_iteration_budget"] = int(
        pick_place["feedback_iteration_budget"]
    )
    pick_place["task_id_source"] = str(pick_place["task_id_source"])

    return config


class JetCobotArmManager(Node):
    def __init__(self):
        super().__init__("jetcobot_manager")

        self.declare_parameter("arm_name", "jetcobot1")
        self.declare_parameter("command_topic", "/command")
        self.declare_parameter("state_topic", "/state")
        self.declare_parameter("config_file", default_config_file())
        self.declare_parameter("state_publish_frequency", 10.0)
        self.declare_parameter("qos_depth", 10)
        self.declare_parameter("recent_command_cache_size", 50)

        self.config_file = str(self.get_parameter("config_file").value)
        self.config = load_arm_manager_config(self.config_file)
        self.declare_parameter(
            "pick_place_action",
            str(self.config["pick_place"]["action_name"]),
        )

        self.arm_name = str(self.get_parameter("arm_name").value)
        self.command_topic = str(self.get_parameter("command_topic").value)
        self.state_topic = str(self.get_parameter("state_topic").value)
        self.pick_place_action = str(self.get_parameter("pick_place_action").value)

        qos_depth = int(self.get_parameter("qos_depth").value)
        state_publish_frequency = float(
            self.get_parameter("state_publish_frequency").value
        )
        state_publish_period = 1.0 / state_publish_frequency
        recent_cache_size = int(self.get_parameter("recent_command_cache_size").value)

        self.state = STATE_IDLE
        self.available = True
        self.emergency = False
        self.command_active = False
        self.active_command_id = ""
        self.last_command_id = ""
        self.last_command_status = ""
        self.mission_id = ""
        self.progress = 0.0
        self.seconds_remaining = 0.0
        self.message = "ready"

        self._active_command_type = ""
        self._current_goal_handle = None
        self._completed_command_ids = deque(maxlen=max(1, recent_cache_size))
        self._pick_place_client = ActionClient(
            self,
            PickPlace,
            self.pick_place_action,
        )

        self._command_sub = self.create_subscription(
            WorkcellCommand,
            self.command_topic,
            self._command_callback,
            qos_depth,
        )
        self._state_pub = self.create_publisher(
            WorkcellState,
            self.state_topic,
            qos_depth,
        )
        self._state_timer = self.create_timer(
            state_publish_period,
            self._publish_state,
        )

        self.get_logger().info(
            f"[{self.arm_name}] arm manager ready "
            f"command=[{self.command_topic}] state=[{self.state_topic}] "
            f"pick_place_action=[{self.pick_place_action}] config=[{self.config_file}]"
        )

    def _command_callback(self, command: WorkcellCommand) -> None:
        if command.arm_name and command.arm_name != self.arm_name:
            return

        if command.command_id == self.active_command_id and self.command_active:
            self._publish_state()
            return
        if command.command_id and command.command_id in self._completed_command_ids:
            self._publish_state()
            return

        if command.command_type == COMMAND_STOP:
            self._handle_stop(command)
            self._publish_state()
            return
        if command.command_type == COMMAND_RESET:
            self._handle_reset(command)
            self._publish_state()
            return

        valid, reason = self._validate_command(command)
        if not valid:
            self._reject_command(command, reason)
            self._publish_state()
            return

        if command.command_type == COMMAND_PICK_AND_PLACE:
            self._handle_pick_and_place(command)
        else:
            self._reject_command(
                command,
                f"unsupported command_type: {command.command_type}",
            )
        self._publish_state()

    def _validate_command(self, command: WorkcellCommand) -> tuple[bool, str]:
        if not command.command_id:
            return False, "command_id is required"
        if self.emergency:
            return False, "arm is in emergency state"
        if self.command_active:
            return False, f"command already active: {self.active_command_id}"
        return True, ""

    def _handle_pick_and_place(self, command: WorkcellCommand) -> None:
        self._accept_command(command, COMMAND_PICK_AND_PLACE, STATE_RESERVED)
        self._send_pick_place_goal(command)

    def _handle_stop(self, command: WorkcellCommand) -> None:
        stopped_command_id = self.active_command_id
        self._cancel_current_goal()
        self.command_active = False
        self.active_command_id = ""
        self._active_command_type = ""
        self.progress = 0.0
        self.seconds_remaining = 0.0
        self.last_command_id = command.command_id
        self.last_command_status = COMMAND_SUCCEEDED
        self.state = STATE_BLOCKED
        self.available = False
        self.message = (
            f"pick_place goal cancel requested while running {stopped_command_id}"
            if stopped_command_id
            else "motion stopped"
        )
        if command.command_id:
            self._completed_command_ids.append(command.command_id)

    def _handle_reset(self, command: WorkcellCommand) -> None:
        self._cancel_current_goal()
        self.emergency = False
        self.command_active = False
        self.active_command_id = ""
        self._active_command_type = ""
        self.progress = 0.0
        self.seconds_remaining = 0.0
        self.last_command_id = command.command_id
        self.last_command_status = COMMAND_SUCCEEDED
        self.state = STATE_IDLE
        self.available = True
        self.message = "reset complete"
        if command.command_id:
            self._completed_command_ids.append(command.command_id)

    def _accept_command(
        self,
        command: WorkcellCommand,
        command_type: str,
        state: str,
    ) -> None:
        self.command_active = True
        self.active_command_id = command.command_id
        self._active_command_type = command_type
        self.last_command_id = command.command_id
        self.last_command_status = COMMAND_ACCEPTED
        self.mission_id = command.mission_id
        self.progress = 0.0
        self._set_seconds_remaining()
        self._transition(state, f"accepted {command.command_type}")
        self.get_logger().info(
            f"[{self.arm_name}] accepted command [{command.command_id}]"
        )

    def _reject_command(self, command: WorkcellCommand, message: str) -> None:
        self.last_command_id = command.command_id
        self.last_command_status = COMMAND_REJECTED
        self.progress = 0.0
        self.seconds_remaining = 0.0
        self.message = message
        self.get_logger().warning(
            f"[{self.arm_name}] rejected command [{command.command_id}]: {message}"
        )
        if command.command_id:
            self._completed_command_ids.append(command.command_id)

    def _finish_command(
        self,
        command_id: str,
        status: str,
        message: str,
        final_state: str,
    ) -> None:
        self.last_command_id = command_id
        self.last_command_status = status
        if command_id == self.active_command_id:
            self.command_active = False
            self.active_command_id = ""
            self._active_command_type = ""
        self._current_goal_handle = None
        self.progress = 1.0 if status == COMMAND_SUCCEEDED else 0.0
        self.seconds_remaining = 0.0
        self._transition(final_state, message)
        if command_id:
            self._completed_command_ids.append(command_id)
        self._publish_state()

    def _send_pick_place_goal(self, command: WorkcellCommand) -> None:
        if not self._pick_place_client.wait_for_server(
            timeout_sec=float(self.config["pick_place"]["server_timeout"])
        ):
            self._finish_command(
                command.command_id,
                COMMAND_FAILED,
                f"PickPlace action server is not ready: {self.pick_place_action}",
                STATE_BLOCKED,
            )
            return

        goal = PickPlace.Goal()
        goal.task_id = self._task_id_for_command(command)
        self._transition(STATE_RESERVED, f"sending PickPlace task {goal.task_id}")
        self._publish_state()

        send_future = self._pick_place_client.send_goal_async(
            goal,
            feedback_callback=lambda feedback: self._pick_place_feedback_callback(
                command.command_id,
                feedback,
            ),
        )
        send_future.add_done_callback(
            lambda future: self._pick_place_goal_response_callback(
                command.command_id,
                goal.task_id,
                future,
            )
        )

    def _task_id_for_command(self, command: WorkcellCommand) -> str:
        source = self.config["pick_place"]["task_id_source"]
        if source == "mission_id" and command.mission_id:
            return command.mission_id
        if source == "payload_json" and command.payload_json:
            return command.payload_json
        return command.command_id

    def _pick_place_goal_response_callback(
        self,
        command_id: str,
        task_id: str,
        future: Any,
    ) -> None:
        if command_id != self.active_command_id:
            return

        try:
            goal_handle = future.result()
        except Exception as exc:
            self._finish_command(
                command_id,
                COMMAND_FAILED,
                f"PickPlace goal send failed for task {task_id}: {exc}",
                STATE_BLOCKED,
            )
            return

        if not goal_handle.accepted:
            self._finish_command(
                command_id,
                COMMAND_REJECTED,
                f"PickPlace rejected task {task_id}",
                STATE_BLOCKED,
            )
            return

        self._current_goal_handle = goal_handle
        self._transition(STATE_PICKING, f"PickPlace accepted task {task_id}")
        self._set_progress(max(self.progress, 0.05))
        self._publish_state()

        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(
            lambda result: self._pick_place_result_callback(
                command_id,
                task_id,
                result,
            )
        )

    def _pick_place_feedback_callback(self, command_id: str, feedback_msg: Any) -> None:
        if command_id != self.active_command_id:
            return

        feedback = feedback_msg.feedback
        server_state = str(feedback.state).upper()
        manager_state = self.config["pick_place"]["state_map"].get(
            server_state,
            STATE_PICKING,
        )
        self._transition(manager_state, self._format_feedback_message(feedback))
        self._set_progress(self._progress_for_feedback(server_state, feedback))
        self._publish_state()

    def _format_feedback_message(self, feedback: Any) -> str:
        state = str(feedback.state)
        if state.upper() in {"SERVO", "SEARCHING"}:
            return (
                f"PickPlace feedback {state} "
                f"iteration={feedback.iteration} "
                f"error=({feedback.e_x:.4f}, {feedback.e_y:.4f})"
            )
        return f"PickPlace feedback {state}"

    def _progress_for_feedback(self, server_state: str, feedback: Any) -> float:
        progress = DEFAULT_PICK_PLACE_PROGRESS.get(server_state, self.progress)
        if server_state in {"SEARCHING", "SERVO"}:
            budget = max(1, int(self.config["pick_place"]["feedback_iteration_budget"]))
            servo_progress = min(1.0, max(0.0, feedback.iteration / budget))
            progress = 0.2 + servo_progress * 0.3
        if server_state == "GO_READY" and self.progress >= 0.8:
            progress = 0.9
        return max(self.progress, min(0.99, progress))

    def _pick_place_result_callback(
        self,
        command_id: str,
        task_id: str,
        future: Any,
    ) -> None:
        if command_id != self.active_command_id:
            return

        try:
            action_result = future.result()
        except Exception as exc:
            self._finish_command(
                command_id,
                COMMAND_FAILED,
                f"PickPlace result failed for task {task_id}: {exc}",
                STATE_BLOCKED,
            )
            return

        self._current_goal_handle = None
        result = action_result.result
        message = result.message or f"PickPlace task {task_id} finished"

        if action_result.status == GoalStatus.STATUS_CANCELED:
            self._finish_command(
                command_id,
                COMMAND_CANCELED,
                f"PickPlace canceled task {task_id}: {message}",
                STATE_BLOCKED,
            )
            return

        if action_result.status == GoalStatus.STATUS_SUCCEEDED and result.success:
            self._finish_command(
                command_id,
                COMMAND_SUCCEEDED,
                message,
                STATE_IDLE,
            )
            return

        self._finish_command(
            command_id,
            COMMAND_FAILED,
            f"PickPlace failed task {task_id}: {message}",
            STATE_BLOCKED,
        )

    def _cancel_current_goal(self) -> None:
        if self._current_goal_handle is not None:
            self._current_goal_handle.cancel_goal_async()
            self._current_goal_handle = None

    def _set_progress(self, progress: float) -> None:
        self.progress = min(1.0, max(0.0, progress))
        self._set_seconds_remaining()

    def _set_seconds_remaining(self) -> None:
        estimate = float(self.config["pick_place"]["seconds_estimate"])
        self.seconds_remaining = max(0.0, (1.0 - self.progress) * estimate)

    def _publish_state(self) -> None:
        self.available = self._is_available()
        msg = WorkcellState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.arm_name = self.arm_name
        msg.state = self.state
        msg.available = self.available
        msg.emergency = self.emergency
        msg.command_active = self.command_active
        msg.active_command_id = self.active_command_id
        msg.last_command_id = self.last_command_id
        msg.last_command_status = self.last_command_status
        msg.mission_id = self.mission_id
        msg.progress = float(self.progress)
        msg.seconds_remaining = float(self.seconds_remaining)
        msg.message = self.message
        self._state_pub.publish(msg)

    def _transition(self, state: str, message: str = "") -> None:
        self.state = state if state else STATE_UNKNOWN
        self.message = message

    def _is_available(self) -> bool:
        return not self.emergency and not self.command_active and self.state == STATE_IDLE


def main(args=None):
    rclpy.init(args=args)
    node = None
    executor = rclpy.executors.MultiThreadedExecutor()
    try:
        node = JetCobotArmManager()
        executor.add_node(node)
        executor.spin()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"jetcobot arm manager startup failed: {exc}", file=sys.stderr)
        raise
    finally:
        executor.shutdown()
        if node is not None:
            node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
