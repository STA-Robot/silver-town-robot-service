import argparse
import math
import sys
from copy import deepcopy
from typing import Any

import rclpy
import rclpy.executors
import tf2_ros
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.time import Time
import yaml
from pinky_drive_msgs.msg import DriveCommand, DriveState
from rclpy.node import Node
from std_msgs.msg import Bool, Float32, String


STATE_UNKNOWN = "unknown"
STATE_IDLE = "idle"
STATE_NAVIGATING = "navigating"
STATE_RETURNING = "returning"
STATE_FOLLOWING = "following"
STATE_BLOCKED = "blocked"
STATE_EMERGENCY = "emergency"

COMMAND_NAVIGATE = "navigate"
COMMAND_RETURNING = "returning"
COMMAND_FOLLOW = "follow"
COMMAND_STOP = "stop"

COMMAND_ACCEPTED = "accepted"
COMMAND_SUCCEEDED = "succeeded"
COMMAND_FAILED = "failed"
COMMAND_REJECTED = "rejected"
COMMAND_CANCELED = "canceled"


class DriveManagerNode(Node):

    def __init__(self, config: dict[str, Any], robot_name: str):
        super().__init__("drive_manager")

        self.config = config
        self.robot_name = robot_name
        self.rmf_level = str(config.get("rmf_level", "L1"))
        self.map_frame = str(config.get("map_frame", "map"))
        self.robot_frame = str(config.get("robot_frame", "base_link"))

        self.command_topic = str(config.get("command_topic", "/command"))
        self.state_topic = str(config.get("state_topic", "/state"))
        self.nav2_action = str(config.get("nav2_action", "/navigate_to_pose"))
        self.battery_topic = str(
            config.get("battery_percent_topic", "/battery/percent")
        )
        self.emergency_topic = str(config.get("emergency_topic", "/emergency"))
        self.follow_event_topic = str(
            config.get("follow_event_topic", "/internal/follow_event")
        )

        self.state = STATE_UNKNOWN
        self.available = False
        self.emergency = False
        self.command_active = False
        self.active_command_id = ""
        self.last_command_id = ""
        self.last_command_status = ""
        self.message = ""
        self.nav2_goal_handle = None
        self.nav2_goal_command_id = ""
        self.pose = [0.0, 0.0, 0.0]
        self.battery_soc = math.nan

        self._create_ros_interfaces()

        self.get_logger().info(
            f"[{self.robot_name}] drive manager ready "
            f"command=[{self.command_topic}] state=[{self.state_topic}]"
        )

    def _create_ros_interfaces(self) -> None:
        qos_depth = int(self.config.get("qos_depth", 10))
        state_publish_frequency = float(
            self.config.get("state_publish_frequency", 10.0)
        )
        state_publish_period = 1.0 / state_publish_frequency

        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)
        self.nav2_client = ActionClient(
            self,
            NavigateToPose,
            self.nav2_action,
        )

        self.command_sub = self.create_subscription(
            DriveCommand,
            self.command_topic,
            self._command_callback,
            qos_depth,
        )

        self.state_pub = self.create_publisher(
            DriveState,
            self.state_topic,
            qos_depth,
        )

        self.battery_sub = self.create_subscription(
            Float32,
            self.battery_topic,
            self._battery_callback,
            qos_depth,
        )
        self.emergency_sub = self.create_subscription(
            Bool,
            self.emergency_topic,
            self._emergency_callback,
            qos_depth,
        )

        # start, lost, done 등의 follower 내부 상태 이벤트
        self.follow_event_sub = self.create_subscription(
            String,
            self.follow_event_topic,
            self._follow_event_callback,
            qos_depth,
        )

        self.state_timer = self.create_timer(
            state_publish_period,
            self._publish_state,
        )

    def _command_callback(self, msg: DriveCommand) -> None:
        if msg.robot_name and msg.robot_name != self.robot_name:
            return

        valid, reason = self._validate_command(msg)
        if not valid:
            self._reject_command(msg, reason)
            self._publish_state()
            return

        if msg.command_type == COMMAND_NAVIGATE:
            self._handle_navigate_command(msg)
        elif msg.command_type == COMMAND_RETURNING:
            self._handle_returning_command(msg)
        elif msg.command_type == COMMAND_FOLLOW:
            self._handle_follow_command(msg)
        elif msg.command_type == COMMAND_STOP:
            self._handle_stop_command(msg)
        else:
            self._reject_command(msg, f"unsupported command_type: {msg.command_type}")

        # command로 변경된 상태를 즉시 publish
        self._publish_state()

    def _battery_callback(self, msg: Float32) -> None:
        value = float(msg.data)
        if value > 1.0:
            value = value / 100.0
        self.battery_soc = min(1.0, max(0.0, value))

    def _emergency_callback(self, msg: Bool) -> None:
        self.emergency = bool(msg.data)
        if self.emergency:
            self._cancel_motion()
            self._transition(STATE_EMERGENCY, "emergency stop active")
        elif self.state == STATE_EMERGENCY:
            self._transition(STATE_IDLE, "emergency cleared")
        self._publish_state()

    def _follow_event_callback(self, msg: String) -> None:
        event = msg.data.strip().lower()
        if event in {"start", "following"}:
            self._transition(STATE_FOLLOWING, msg.data)
        elif event in {"blocked"}:
            self._transition(STATE_BLOCKED, msg.data)
        elif event in {"stop", "done", "idle"}:
            self._transition(STATE_IDLE, msg.data)
        else:
            self.message = msg.data
        self._publish_state()

    def _handle_navigate_command(self, command: DriveCommand) -> None:
        if self.command_active and self.state == STATE_RETURNING:
            self._cancel_motion()
        self._accept_command(command, STATE_NAVIGATING)
        self._send_nav_goal(command)

    def _handle_returning_command(self, command: DriveCommand) -> None:
        self._accept_command(command, STATE_RETURNING)
        self._send_nav_goal(command)

    def _handle_follow_command(self, command: DriveCommand) -> None:
        if self.command_active and self.state == STATE_RETURNING:
            self._cancel_motion()
        self._accept_command(command, STATE_FOLLOWING)
        self._start_follow(command)

    def _handle_stop_command(self, command: DriveCommand) -> None:
        self._cancel_motion()
        self._finish_command(
            command.command_id,
            COMMAND_CANCELED,
            "motion stopped",
            clear_active=True,
        )

    def _validate_command(self, command: DriveCommand) -> tuple[bool, str]:
        if not command.command_id:
            return False, "command_id is required"
        if command.map_name and command.map_name != self.rmf_level:
            return False, f"map mismatch: {command.map_name}"
        if self.emergency and command.command_type != COMMAND_STOP:
            return False, "robot is in emergency state"
        if (
            self.command_active
            and command.command_id != self.active_command_id
            and command.command_type != COMMAND_STOP
        ):
            if self.state == STATE_RETURNING and command.command_type in {
                COMMAND_NAVIGATE,
                COMMAND_FOLLOW,
            }:
                return True, ""
            return False, f"command already active: {self.active_command_id}"
        return True, ""

    def _accept_command(self, command: DriveCommand, state: str) -> None:
        # 명령을 활성 상태로 기록 -> DriveState가 accepted로 되도록
        self.command_active = True
        self.active_command_id = command.command_id
        self.last_command_id = command.command_id
        self.last_command_status = COMMAND_ACCEPTED
        self._transition(state, f"accepted {command.command_type}")
        self.get_logger().info(
            f"[{self.robot_name}] accepted command [{command.command_id}]"
        )

    def _reject_command(self, command: DriveCommand, message: str) -> None:
        # 거절 결과를 노드 상태로 기록 -> _publish_state()을 통해 상태값으로 응답 반환
        self.last_command_id = command.command_id
        self.last_command_status = COMMAND_REJECTED
        self.message = message
        self.get_logger().warning(
            f"[{self.robot_name}] rejected command [{command.command_id}]: {message}"
        )

    def _finish_command(
        self,
        command_id: str,
        status: str,
        message: str,
        final_state: str = STATE_IDLE,
        clear_active: bool = False,
    ) -> None:
        self.last_command_id = command_id
        self.last_command_status = status
        if clear_active or not command_id or command_id == self.active_command_id:
            self.command_active = False
            self.active_command_id = ""
            self.nav2_goal_handle = None
            self.nav2_goal_command_id = ""
        self._transition(final_state, message)

    def _send_nav_goal(self, command: DriveCommand) -> None:
        if not self.nav2_client.wait_for_server(
            timeout_sec=float(self.config.get("nav2_server_timeout", 2.0))
        ):
            self._finish_command(
                command.command_id,
                COMMAND_FAILED,
                "Nav2 action server is not ready",
                STATE_BLOCKED,
            )
            return

        goal = NavigateToPose.Goal()
        goal.pose = self._to_pose_stamped(command)
        send_future = self.nav2_client.send_goal_async(
            goal,
            feedback_callback=lambda feedback: self._nav2_feedback_callback(
                command.command_id, feedback
            ),
        )
        send_future.add_done_callback(
            lambda future: self._nav2_goal_response_callback(
                command.command_id, future
            )
        )

    def _to_pose_stamped(self, command: DriveCommand) -> PoseStamped:
        pose = PoseStamped()
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.header.frame_id = self.map_frame
        pose.pose.position.x = float(command.x)
        pose.pose.position.y = float(command.y)

        half_yaw = float(command.yaw) * 0.5
        pose.pose.orientation.z = math.sin(half_yaw)
        pose.pose.orientation.w = math.cos(half_yaw)
        return pose

    def _nav2_feedback_callback(self, command_id: str, feedback_msg: Any) -> None:
        if command_id != self.active_command_id:
            return
        # TODO: publish feedback msg info to RMF
        distance = getattr(feedback_msg.feedback, "distance_remaining", math.nan)
        if math.isfinite(float(distance)):
            self.message = f"navigation distance remaining: {float(distance):.2f}m"

    def _nav2_goal_response_callback(self, command_id: str, future: Any) -> None:
        if command_id != self.active_command_id:
            return

        try:
            goal_handle = future.result()
        except Exception as err:
            self._finish_command(
                command_id,
                COMMAND_FAILED,
                f"Nav2 goal send failed: {err}",
                STATE_BLOCKED,
            )
            self._publish_state()
            return

        if not goal_handle.accepted:
            self._finish_command(
                command_id, COMMAND_REJECTED, "Nav2 rejected goal", STATE_BLOCKED
            )
            self._publish_state()
            return

        self.nav2_goal_handle = goal_handle
        self.nav2_goal_command_id = command_id
        self.message = "Nav2 accepted goal"
        self._publish_state()

        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(
            lambda result: self._nav2_result_callback(command_id, result)
        )

    def _nav2_result_callback(self, command_id: str, future: Any) -> None:
        if command_id != self.active_command_id:
            return

        try:
            result = future.result()
        except Exception as err:
            self._finish_command(
                command_id,
                COMMAND_FAILED,
                f"Nav2 result failed: {err}",
                STATE_BLOCKED,
            )
            self._publish_state()
            return

        if result.status == GoalStatus.STATUS_SUCCEEDED:
            self._finish_command(command_id, COMMAND_SUCCEEDED, "navigation succeeded")
        elif result.status == GoalStatus.STATUS_CANCELED:
            self._finish_command(command_id, COMMAND_CANCELED, "navigation canceled")
        else:
            self._finish_command(
                command_id,
                COMMAND_FAILED,
                f"navigation failed with status {result.status}",
                STATE_BLOCKED,
            )
        self._publish_state()

    def _start_follow(self, command: DriveCommand) -> None:
        # TODO: Send a start request to the follower/person-tracking node.
        self.get_logger().info(
            f"[{self.robot_name}] follow start placeholder: "
            f"target=[{command.target_name}]"
        )

    def _cancel_motion(self) -> None:
        if self.nav2_goal_handle is not None:
            self.nav2_goal_handle.cancel_goal_async()
            self.nav2_goal_handle = None
            self.nav2_goal_command_id = ""
            self.message = "Nav2 cancel requested"
            return

        # TODO: Stop the follower/person-tracking node when follow integration is added.
        if self.command_active:
            self.get_logger().info(
                f"[{self.robot_name}] cancel motion placeholder: {self.active_command_id}"
            )

    def _lookup_pose(self) -> list[float] | None:
        try:
            transform = self.tf_buffer.lookup_transform(
                self.map_frame,
                self.robot_frame,
                Time(),
            )
        except Exception:
            # TODO: Narrow this to tf2 exceptions and throttle logging if needed.
            return None

        translation = transform.transform.translation
        rotation = transform.transform.rotation
        yaw = math.atan2(
            2.0 * (rotation.w * rotation.z + rotation.x * rotation.y),
            1.0 - 2.0 * (rotation.y * rotation.y + rotation.z * rotation.z),
        )
        return [float(translation.x), float(translation.y), yaw]

    def _publish_state(self) -> None:
        pose = self._lookup_pose()
        if pose is not None:
            self.pose = pose

        self.available = self._is_available()
        self.state_pub.publish(self._fill_state_message())

    def _fill_state_message(self) -> DriveState:
        msg = DriveState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.map_frame

        msg.robot_name = self.robot_name
        msg.map_name = self.rmf_level
        msg.pose = [
            float(self.pose[0]),
            float(self.pose[1]),
            float(self._normalize_yaw(self.pose[2])),
        ]
        msg.battery_soc = float(self.battery_soc)
        if math.isnan(msg.battery_soc) and self.config.get(
            "assume_full_battery_if_missing", False
        ):
            msg.battery_soc = 1.0

        msg.state = self.state
        msg.available = self.available
        msg.emergency = self.emergency
        msg.command_active = self.command_active
        msg.active_command_id = self.active_command_id
        msg.last_command_id = self.last_command_id
        msg.last_command_status = self.last_command_status
        msg.message = self.message
        return msg

    def _transition(self, state: str, message: str = "") -> None:
        self.state = state
        self.message = message

    def _is_available(self) -> bool:
        return (
            not self.emergency
            and not self.command_active
            and self.state == STATE_IDLE
        )

    @staticmethod
    def _normalize_yaw(yaw: float) -> float:
        return math.atan2(math.sin(yaw), math.cos(yaw))


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _format_robot_values(value: Any, robot_name: str) -> Any:
    if isinstance(value, str):
        return value.format(robot_name=robot_name)
    if isinstance(value, dict):
        return {
            key: _format_robot_values(sub_value, robot_name)
            for key, sub_value in value.items()
        }
    if isinstance(value, list):
        return [_format_robot_values(item, robot_name) for item in value]
    return value


def _load_config(config_file: str, robot_name: str) -> dict[str, Any]:
    with open(config_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    defaults = data.get("defaults", {})
    robots = data.get("robots", {})

    if robot_name in robots:
        config = _deep_merge(defaults, robots[robot_name] or {})
    elif robot_name in data and isinstance(data[robot_name], dict):
        config = _deep_merge(defaults, data[robot_name] or {})
    elif defaults:
        config = deepcopy(defaults)
    else:
        config = deepcopy(data)

    return _format_robot_values(config, robot_name)


def main(argv=sys.argv):
    parser = argparse.ArgumentParser(
        prog="drive_manager_node",
        description="Start one Pinky RMF drive manager node.",
    )
    parser.add_argument("--config-file", required=True)
    parser.add_argument("--robot-name", required=True)
    parser.add_argument("--rmf-level", default="")
    args, _ = parser.parse_known_args(argv[1:])

    rclpy.init(args=argv)

    config = _load_config(args.config_file, args.robot_name)
    if args.rmf_level:
        config["rmf_level"] = args.rmf_level

    node = DriveManagerNode(config, args.robot_name)
    executor = rclpy.executors.MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main(sys.argv)
