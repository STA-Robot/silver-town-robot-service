import argparse
import math
import sys
import threading
from copy import deepcopy
from typing import Any

import rclpy
import rclpy.executors
import yaml
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from pinky_drive_msgs.action import Navigate
from pinky_drive_msgs.msg import DriveState
from pinky_drive_msgs.srv import Stop
from rclpy.action import ActionClient, ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.time import Time
from std_msgs.msg import Bool, Float32, String
import tf2_ros
from tf_transformations import euler_from_quaternion, quaternion_from_euler


STATE_UNKNOWN = "unknown"
STATE_IDLE = "idle"
STATE_NAVIGATING = "navigating"
STATE_RETURNING = "returning"
STATE_FOLLOWING = "following"
STATE_BLOCKED = "blocked"
STATE_EMERGENCY = "emergency"

NAV2_NONE = "none"
NAV2_PENDING = "pending"
NAV2_ACCEPTED = "accepted"
NAV2_EXECUTING = "executing"
NAV2_CANCELING = "canceling"

COMMAND_TASK = "task"
COMMAND_RETURNING = "returning"

FOLLOW_START_EVENTS = {"start", "follow_start", "following_start", "following_started"}
FOLLOW_STOP_EVENTS = {"stop", "follow_stop", "following_stop", "delivery_done", "done"}
FOLLOW_BLOCKED_EVENTS = {
    "blocked",
    "target_lost",
    "target_lost_timeout",
    "follow_blocked",
}


class DriveManagerNode(Node):
    """Owns the RMF-facing drive API for one Pinky robot."""

    def __init__(self, config: dict[str, Any], robot_name: str):
        super().__init__("drive_manager")

        self.robot_name = robot_name
        self.config = config
        self.rmf_level = str(config.get("rmf_level", "L1"))
        self.map_frame = str(config.get("map_frame", "map"))
        self.robot_frame = str(config.get("robot_frame", "base_link"))
        self.robot_namespace = str(config.get("robot_namespace", robot_name)).strip("/")
        self.assume_full_battery_if_missing = bool(
            config.get("assume_full_battery_if_missing", False)
        )
        self.allow_blocked_retry = bool(config.get("allow_blocked_retry", True))
        self.nav2_server_timeout = float(config.get("nav2_server_timeout", 2.0))
        self.goal_acceptance_timeout = float(
            config.get("goal_acceptance_timeout", 5.0)
        )

        self._lock = threading.RLock()
        self._state = STATE_UNKNOWN
        self._nav2_state = NAV2_NONE
        self._message = "Waiting for Nav2 and TF"
        self._emergency = False
        self._command_active = False
        self._active_request_id = ""
        self._battery_soc: float | None = None
        self._pose = [0.0, 0.0, 0.0]
        self._pose_ready = False
        self._distance_remaining = math.nan
        self._nav2_goal_handle = None
        self._active_drive_goal_handle = None

        callback_group = ReentrantCallbackGroup()
        nav2_action_name = self._resolve_robot_name(
            str(config.get("nav2_action", "navigate_to_pose"))
        )
        battery_topic = self._resolve_robot_name(
            str(config.get("battery_percent_topic", "battery/percent"))
        )
        emergency_topic = self._resolve_robot_name(
            str(config.get("emergency_topic", "emergency"))
        )
        follow_event_topic = str(
            config.get("follow_event_topic", "internal/follow_event")
        )

        self._nav2_client = ActionClient(
            self, NavigateToPose, nav2_action_name, callback_group=callback_group
        )
        self._navigate_server = ActionServer(
            self,
            Navigate,
            "navigate",
            execute_callback=self._execute_navigate,
            goal_callback=self._goal_callback,
            cancel_callback=self._cancel_callback,
            callback_group=callback_group,
        )
        self._stop_service = self.create_service(
            Stop, "stop", self._handle_stop, callback_group=callback_group
        )
        self._state_pub = self.create_publisher(DriveState, "state", 10)
        self._battery_sub = self.create_subscription(
            Float32, battery_topic, self._battery_callback, 10
        )
        self._emergency_sub = self.create_subscription(
            Bool, emergency_topic, self._emergency_callback, 10
        )
        self._follow_event_sub = self.create_subscription(
            String, follow_event_topic, self._follow_event_callback, 10
        )

        self._tf_buffer = tf2_ros.Buffer()
        self._tf_listener = tf2_ros.TransformListener(
            self._tf_buffer, self, spin_thread=False
        )

        frequency = float(config.get("state_publish_frequency", 10.0))
        self._timer = self.create_timer(1.0 / max(frequency, 0.1), self._publish_state)

        self.get_logger().info(
            f"[{self.robot_name}] drive API ready under namespace "
            f"[{self.get_namespace()}], Nav2 [{nav2_action_name}], "
            f"TF [{self.map_frame} -> {self.robot_frame}]"
        )

    def _resolve_robot_name(self, name: str) -> str:
        if name.startswith("/"):
            return name
        if not self.robot_namespace:
            return name
        return f"/{self.robot_namespace}/{name}"

    def _battery_callback(self, msg: Float32):
        value = float(msg.data)
        if value > 1.0:
            value = value / 100.0
        with self._lock:
            self._battery_soc = min(1.0, max(0.0, value))

    def _emergency_callback(self, msg: Bool):
        emergency = bool(msg.data)
        publish_now = False

        with self._lock:
            if emergency == self._emergency:
                return

            self._emergency = emergency
            publish_now = True

            if emergency:
                self._cancel_motion_locked()
                self._clear_command_locked("Emergency stop is active")
                self._transition_locked(STATE_EMERGENCY)
            else:
                self._message = "Emergency stop cleared"
                if not self._command_active:
                    self._transition_locked(STATE_UNKNOWN)

        if publish_now:
            self._publish_state()

    def _follow_event_callback(self, msg: String):
        event = msg.data.strip().lower()
        if not event:
            return

        publish_now = True
        with self._lock:
            if self._emergency:
                self._message = f"Ignoring follow event [{event}] during emergency"
                return

            if event in FOLLOW_START_EVENTS:
                if self._state not in (STATE_IDLE, STATE_BLOCKED):
                    self.get_logger().warn(
                        f"[{self.robot_name}] ignoring follow start while "
                        f"in [{self._state}]"
                    )
                    return
                self._command_active = True
                self._active_request_id = ""
                self._nav2_state = NAV2_NONE
                self._distance_remaining = math.nan
                self._message = "Following mode started"
                self._transition_locked(STATE_FOLLOWING)

            elif event in FOLLOW_STOP_EVENTS:
                self._clear_command_locked("Following mode stopped")
                self._transition_locked(STATE_IDLE)

            elif event in FOLLOW_BLOCKED_EVENTS:
                self._clear_command_locked("target_lost_timeout")
                self._transition_locked(STATE_BLOCKED)

            else:
                publish_now = False
                self.get_logger().warn(
                    f"[{self.robot_name}] unknown follow event [{event}]"
                )

        if publish_now:
            self._publish_state()

    def _goal_callback(self, goal_request: Navigate.Goal):
        allowed, message = self._validate_goal(goal_request)
        if allowed:
            return GoalResponse.ACCEPT
        self.get_logger().warn(f"[{self.robot_name}] rejecting goal: {message}")
        return GoalResponse.REJECT

    def _cancel_callback(self, goal_handle):
        del goal_handle
        with self._lock:
            self._message = "Drive action cancel requested"
            self._cancel_nav2_locked()
        return CancelResponse.ACCEPT

    def _execute_navigate(self, goal_handle):
        goal = goal_handle.request
        accepted, message = self._validate_goal(goal)
        if not accepted:
            goal_handle.abort()
            return self._navigate_result(
                False, self._retryable_state(), self._state_snapshot(), message
            )

        with self._lock:
            if self._state == STATE_RETURNING:
                self._cancel_nav2_locked()

            self._active_drive_goal_handle = goal_handle
            self._command_active = True
            self._active_request_id = goal.request_id
            self._distance_remaining = math.nan
            self._nav2_state = NAV2_PENDING
            self._message = f"Sending {goal.command_mode} goal to Nav2"
            self._transition_locked(
                STATE_RETURNING
                if goal.command_mode == COMMAND_RETURNING
                else STATE_NAVIGATING
            )

        self._publish_state()

        if goal.speed_limit > 0.0:
            # TODO: Apply speed limits through the selected controller/Nav2 stack.
            self.get_logger().debug(
                f"[{self.robot_name}] speed_limit [{goal.speed_limit}] accepted "
                "but not applied in MVP"
            )

        if not self._nav2_client.wait_for_server(timeout_sec=self.nav2_server_timeout):
            with self._lock:
                self._clear_command_locked("Nav2 action server is not ready")
                self._transition_locked(STATE_BLOCKED)
            goal_handle.abort()
            return self._navigate_result(
                False, True, STATE_BLOCKED, "Nav2 action server is not ready"
            )

        with self._lock:
            if self._emergency:
                self._clear_command_locked("Robot entered emergency state")
                self._transition_locked(STATE_EMERGENCY)
                goal_handle.abort()
                return self._navigate_result(
                    False, True, STATE_EMERGENCY, "Robot entered emergency state"
                )

        nav_goal = NavigateToPose.Goal()
        nav_goal.pose = self._to_pose_stamped(goal)

        send_done = threading.Event()
        send_error = {"message": ""}
        nav_goal_ref = {"handle": None}

        def response_callback(future):
            try:
                nav_goal_handle = future.result()
            except Exception as err:  # noqa: BLE001 - ROS future exceptions vary.
                send_error["message"] = str(err)
                send_done.set()
                return

            if not nav_goal_handle.accepted:
                send_error["message"] = "Nav2 rejected goal"
                send_done.set()
                return

            nav_goal_ref["handle"] = nav_goal_handle
            with self._lock:
                if self._active_request_id == goal.request_id:
                    self._nav2_goal_handle = nav_goal_handle
                    self._nav2_state = NAV2_ACCEPTED
                    self._message = "Nav2 accepted goal"
            send_done.set()

        send_future = self._nav2_client.send_goal_async(
            nav_goal,
            feedback_callback=lambda feedback: self._nav2_feedback(goal_handle, feedback),
        )
        send_future.add_done_callback(response_callback)

        if not send_done.wait(self.goal_acceptance_timeout):
            with self._lock:
                self._clear_command_locked("Timed out waiting for Nav2 goal acceptance")
                self._transition_locked(STATE_BLOCKED)
            goal_handle.abort()
            return self._navigate_result(
                False, True, STATE_BLOCKED, "Timed out waiting for Nav2 goal acceptance"
            )

        with self._lock:
            if self._emergency:
                self._clear_command_locked("Robot entered emergency state")
                self._transition_locked(STATE_EMERGENCY)
                goal_handle.abort()
                return self._navigate_result(
                    False, True, STATE_EMERGENCY, "Robot entered emergency state"
                )

        if send_error["message"]:
            with self._lock:
                self._clear_command_locked(send_error["message"])
                self._transition_locked(STATE_BLOCKED)
            goal_handle.abort()
            return self._navigate_result(False, True, STATE_BLOCKED, send_error["message"])

        nav_goal_handle = nav_goal_ref["handle"]
        if nav_goal_handle is None:
            with self._lock:
                self._clear_command_locked("Nav2 goal handle was not created")
                self._transition_locked(STATE_BLOCKED)
            goal_handle.abort()
            return self._navigate_result(
                False, True, STATE_BLOCKED, "Nav2 goal handle was not created"
            )

        result_done = threading.Event()
        nav_result = {"status": GoalStatus.STATUS_UNKNOWN, "message": ""}
        result_future = nav_goal_handle.get_result_async()

        def result_callback(future):
            try:
                result = future.result()
                nav_result["status"] = int(result.status)
                nav_result["message"] = self._status_name(int(result.status))
            except Exception as err:  # noqa: BLE001 - ROS future exceptions vary.
                nav_result["message"] = str(err)
            result_done.set()

        result_future.add_done_callback(result_callback)
        result_done.wait()

        with self._lock:
            if self._emergency or self._state == STATE_EMERGENCY:
                self._clear_command_locked("Robot entered emergency state")
                self._transition_locked(STATE_EMERGENCY)
                goal_handle.abort()
                return self._navigate_result(
                    False, True, STATE_EMERGENCY, "Robot entered emergency state"
                )

            if self._active_request_id != goal.request_id:
                final_state = self._state
                retryable = final_state in (
                    STATE_IDLE,
                    STATE_BLOCKED,
                    STATE_EMERGENCY,
                    STATE_NAVIGATING,
                    STATE_RETURNING,
                )
                goal_handle.abort()
                return self._navigate_result(
                    False,
                    retryable,
                    final_state,
                    "Navigation command was interrupted or superseded",
                )

            status = nav_result["status"]
            status_name = self._status_name(status)

            if status == GoalStatus.STATUS_SUCCEEDED:
                # TODO: Insert an ArUco/YOLO precision parking phase here before
                # reporting success when the destination requires final alignment.
                self._clear_command_locked("Navigation succeeded")
                self._transition_locked(STATE_IDLE)
                goal_handle.succeed()
                return self._navigate_result(
                    True, False, STATE_IDLE, "Navigation succeeded"
                )

            if status == GoalStatus.STATUS_CANCELED:
                self._clear_command_locked("Navigation canceled")
                self._transition_locked(STATE_IDLE)
                if goal_handle.is_cancel_requested:
                    goal_handle.canceled()
                else:
                    goal_handle.abort()
                return self._navigate_result(
                    False, True, STATE_IDLE, "Navigation canceled"
                )

            self._clear_command_locked(f"Navigation ended with {status_name}")
            self._transition_locked(STATE_BLOCKED)

        goal_handle.abort()
        return self._navigate_result(
            False, True, STATE_BLOCKED, f"Navigation ended with {status_name}"
        )

    def _handle_stop(self, request: Stop.Request, response: Stop.Response):
        if request.robot_name and request.robot_name != self.robot_name:
            response.success = False
            response.state = self._state_snapshot()
            response.message = f"Unknown robot [{request.robot_name}]"
            return response

        with self._lock:
            previous_state = self._state
            self._cancel_motion_locked()
            self._clear_command_locked("Stop requested")

            if self._emergency:
                self._transition_locked(STATE_EMERGENCY)
            elif previous_state == STATE_UNKNOWN:
                self._transition_locked(STATE_UNKNOWN)
            else:
                # TODO: Keep blocked when a future diagnostics node can prove that
                # the blocked cause is still active after Stop.
                self._transition_locked(STATE_IDLE)

            response.success = True
            response.state = self._state
            response.message = "Stop requested"

        self._publish_state()
        return response

    def _validate_goal(self, goal: Navigate.Goal) -> tuple[bool, str]:
        if goal.robot_name != self.robot_name:
            return False, f"unknown robot [{goal.robot_name}]"
        if goal.map_name != self.rmf_level:
            return (
                False,
                f"unsupported map [{goal.map_name}], expected [{self.rmf_level}]",
            )
        if goal.command_mode not in (COMMAND_TASK, COMMAND_RETURNING):
            return False, f"unsupported command_mode [{goal.command_mode}]"
        if not goal.request_id:
            return False, "request_id is required"
        if not all(math.isfinite(value) for value in (goal.x, goal.y, goal.yaw)):
            return False, "goal pose contains non-finite values"
        if not self._nav2_client.server_is_ready():
            return False, "Nav2 action server is not ready"
        if self._lookup_pose() is None:
            return False, "TF pose is not ready"

        with self._lock:
            if self._emergency or self._state == STATE_EMERGENCY:
                return False, "emergency stop is active"
            if self._state == STATE_BLOCKED:
                if self.allow_blocked_retry:
                    return True, "accepted"
                return False, "robot is blocked"
            if self._state in (STATE_IDLE, STATE_RETURNING):
                return True, "accepted"
            return False, f"robot is not ready, current state [{self._state}]"

    def _nav2_feedback(self, drive_goal_handle, feedback_msg):
        goal = drive_goal_handle.request
        feedback = feedback_msg.feedback
        distance = float(getattr(feedback, "distance_remaining", math.nan))

        with self._lock:
            if self._active_request_id != goal.request_id:
                return
            self._nav2_state = NAV2_EXECUTING
            self._distance_remaining = distance
            state = self._state
            message = self._message

        drive_feedback = Navigate.Feedback()
        drive_feedback.state = state
        drive_feedback.distance_remaining = distance
        drive_feedback.message = message
        drive_goal_handle.publish_feedback(drive_feedback)

    def _publish_state(self):
        pose = self._lookup_pose()
        nav2_ready = self._nav2_client.server_is_ready()

        with self._lock:
            if not self._emergency and not self._command_active:
                if self._state == STATE_UNKNOWN and pose is not None and nav2_ready:
                    self._transition_locked(STATE_IDLE)
                    self._message = "Robot is idle"
                elif self._state == STATE_IDLE and (pose is None or not nav2_ready):
                    self._transition_locked(STATE_UNKNOWN)
                    self._message = "Waiting for Nav2 and TF"

            msg = DriveState()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.header.frame_id = self.map_frame
            msg.robot_name = self.robot_name
            msg.map_name = self.rmf_level
            msg.pose = self._pose
            msg.battery_soc = float(self._battery_soc_value())
            msg.state = self._state
            msg.nav2_state = self._nav2_state
            msg.available = self._available_locked()
            msg.emergency = self._emergency
            msg.command_active = self._command_active
            msg.active_request_id = self._active_request_id
            msg.message = self._message

        self._state_pub.publish(msg)

    def _lookup_pose(self):
        try:
            transform = self._tf_buffer.lookup_transform(
                self.map_frame,
                self.robot_frame,
                Time(),
                timeout=Duration(seconds=0.05),
            )
        except tf2_ros.TransformException:
            with self._lock:
                self._pose_ready = False
            return None

        translation = transform.transform.translation
        rotation = transform.transform.rotation
        _, _, yaw = euler_from_quaternion(
            [rotation.x, rotation.y, rotation.z, rotation.w]
        )
        pose = [float(translation.x), float(translation.y), self._normalize_yaw(yaw)]
        with self._lock:
            self._pose = pose
            self._pose_ready = True
        return pose

    def _to_pose_stamped(self, goal: Navigate.Goal) -> PoseStamped:
        pose = PoseStamped()
        pose.header.frame_id = self.map_frame
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.pose.position.x = float(goal.x)
        pose.pose.position.y = float(goal.y)
        quat = quaternion_from_euler(0.0, 0.0, float(goal.yaw))
        pose.pose.orientation.x = quat[0]
        pose.pose.orientation.y = quat[1]
        pose.pose.orientation.z = quat[2]
        pose.pose.orientation.w = quat[3]
        return pose

    def _cancel_motion_locked(self):
        self._cancel_nav2_locked()
        if self._state == STATE_FOLLOWING:
            # TODO: Call the follower controller stop API when that node is added.
            self._message = "Following stop requested"

    def _cancel_nav2_locked(self):
        if self._nav2_goal_handle is None:
            return
        try:
            self._nav2_goal_handle.cancel_goal_async()
            self._nav2_state = NAV2_CANCELING
        except Exception as err:  # noqa: BLE001 - ROS future exceptions vary.
            self.get_logger().warn(f"[{self.robot_name}] failed to cancel Nav2: {err}")

    def _clear_command_locked(self, message: str):
        self._command_active = False
        self._active_request_id = ""
        self._active_drive_goal_handle = None
        self._nav2_goal_handle = None
        self._distance_remaining = math.nan
        self._nav2_state = NAV2_NONE
        self._message = message

    def _transition_locked(self, state: str):
        if state != self._state:
            self.get_logger().info(
                f"[{self.robot_name}] drive state {self._state} -> {state}"
            )
        self._state = state

    def _available_locked(self) -> bool:
        return self._state in (STATE_IDLE, STATE_RETURNING) and not self._emergency

    def _battery_soc_value(self) -> float:
        if self._battery_soc is not None:
            return self._battery_soc
        if self.assume_full_battery_if_missing:
            return 1.0
        return math.nan

    def _retryable_state(self) -> bool:
        with self._lock:
            return self._state in (STATE_IDLE, STATE_BLOCKED, STATE_EMERGENCY)

    def _state_snapshot(self) -> str:
        with self._lock:
            return self._state

    @staticmethod
    def _navigate_result(
        success: bool, retryable: bool, final_state: str, message: str
    ) -> Navigate.Result:
        result = Navigate.Result()
        result.success = bool(success)
        result.retryable = bool(retryable)
        result.final_state = final_state
        result.message = message
        return result

    @staticmethod
    def _normalize_yaw(yaw: float) -> float:
        return math.atan2(math.sin(yaw), math.cos(yaw))

    @staticmethod
    def _status_name(status: int) -> str:
        names = {
            GoalStatus.STATUS_UNKNOWN: "unknown",
            GoalStatus.STATUS_ACCEPTED: "accepted",
            GoalStatus.STATUS_EXECUTING: "executing",
            GoalStatus.STATUS_CANCELING: "canceling",
            GoalStatus.STATUS_SUCCEEDED: "succeeded",
            GoalStatus.STATUS_CANCELED: "canceled",
            GoalStatus.STATUS_ABORTED: "aborted",
        }
        return names.get(status, "unknown")


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
    rclpy.init(args=argv)
    args_without_ros = rclpy.utilities.remove_ros_args(argv)

    parser = argparse.ArgumentParser(
        prog="drive_manager_node",
        description="Start one Pinky RMF drive manager node.",
    )
    parser.add_argument("--config-file", required=True)
    parser.add_argument("--robot-name", required=True)
    parser.add_argument("--robot-namespace", default="")
    parser.add_argument("--rmf-level", default="")
    args, _ = parser.parse_known_args(args_without_ros[1:])

    config = _load_config(args.config_file, args.robot_name)
    if args.robot_namespace:
        config["robot_namespace"] = args.robot_namespace
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
