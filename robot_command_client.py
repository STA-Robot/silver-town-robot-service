import math
import threading
import uuid
from dataclasses import dataclass

from pinky_drive_msgs.action import Navigate
from pinky_drive_msgs.msg import DriveState
from pinky_drive_msgs.srv import Stop
from rclpy.action import ActionClient


@dataclass
class CommandState:
    status: str = "idle"
    completed: bool = False
    failed: bool = False
    retryable: bool = False
    message: str = ""


class RobotCommandClient:
    """Drive workspace interface client for one Pinky robot."""

    def __init__(self, node, robot_name: str, config: dict):
        self.node = node
        self.robot_name = robot_name
        self.config = config
        self.rmf_level = config.get("rmf_level", "L1")
        self.state_timeout = float(config.get("state_timeout", 2.0))
        self._goal_timeout = float(config.get("goal_acceptance_timeout", 5.0))

        navigate_action = self._resolve_drive_name(
            config.get("navigate_action", "navigate")
        )
        stop_service = self._resolve_drive_name(config.get("stop_service", "stop"))
        state_topic = self._resolve_drive_name(config.get("state_topic", "state"))

        self._action_client = ActionClient(node, Navigate, navigate_action)
        self._stop_client = node.create_client(Stop, stop_service)
        self._state_subscription = node.create_subscription(
            DriveState, state_topic, self._state_callback, 10
        )

        self._lock = threading.Lock()
        self._drive_state: DriveState | None = None
        self._drive_state_time = None
        self._goal_handle = None
        self._result_future = None
        self._state = CommandState()

        node.get_logger().info(
            f"[{robot_name}] drive interface action [{navigate_action}], "
            f"stop [{stop_service}], state [{state_topic}]"
        )

    def _resolve_drive_name(self, name: str) -> str:
        if name.startswith("/"):
            return name
        namespace = self.config.get("drive_namespace", "").strip("/")
        if not namespace:
            return name
        return f"/{namespace}/{name}"

    def _state_callback(self, msg: DriveState):
        if msg.robot_name and msg.robot_name != self.robot_name:
            return
        with self._lock:
            self._drive_state = msg
            self._drive_state_time = self.node.get_clock().now()

            if msg.emergency or msg.state in ("blocked", "error"):
                self._state.failed = True
                self._state.message = msg.message or f"Drive state is [{msg.state}]"

    def check_connection(self) -> bool:
        action_ready = self._action_client.wait_for_server(
            timeout_sec=float(self.config.get("action_server_timeout", 2.0))
        )
        service_ready = self._stop_client.wait_for_service(
            timeout_sec=float(self.config.get("stop_service_timeout", 2.0))
        )
        if not action_ready:
            self.node.get_logger().warn(
                f"[{self.robot_name}] drive Navigate action server is not ready"
            )
        if not service_ready:
            self.node.get_logger().warn(
                f"[{self.robot_name}] drive Stop service is not ready"
            )
        return action_ready and service_ready

    def send_goal(
        self,
        pose: list[float],
        map_name: str,
        speed_limit: float = 0.0,
        destination_name: str = "",
        command_mode: str = "task",
    ) -> bool:
        if map_name != self.rmf_level:
            self.node.get_logger().warn(
                f"[{self.robot_name}] refusing goal on map [{map_name}], "
                f"expected [{self.rmf_level}]"
            )
            return False

        if len(pose) < 3 or not all(math.isfinite(float(v)) for v in pose[:3]):
            self.node.get_logger().warn(
                f"[{self.robot_name}] goal pose must be finite [x, y, yaw], got {pose}"
            )
            return False

        if not self.is_available():
            drive_state = self.drive_state()
            state = "unknown" if drive_state is None else drive_state.state
            self.node.get_logger().warn(
                f"[{self.robot_name}] refusing goal because drive state is [{state}]"
            )
            return False

        if not self.check_connection():
            return False

        goal_msg = Navigate.Goal()
        goal_msg.robot_name = self.robot_name
        goal_msg.map_name = map_name
        goal_msg.x = float(pose[0])
        goal_msg.y = float(pose[1])
        goal_msg.yaw = float(pose[2])
        goal_msg.speed_limit = float(speed_limit or 0.0)
        goal_msg.request_id = f"{self.robot_name}_{uuid.uuid4().hex[:12]}"
        goal_msg.destination_name = destination_name or ""
        goal_msg.command_mode = command_mode or "task"

        done = threading.Event()
        accepted = {"value": False}

        with self._lock:
            self._goal_handle = None
            self._result_future = None
            self._state = CommandState(status="pending")

        send_future = self._action_client.send_goal_async(goal_msg)

        def goal_response_callback(future):
            try:
                goal_handle = future.result()
            except Exception as err:
                with self._lock:
                    self._state = CommandState(
                        status="rejected",
                        completed=True,
                        failed=True,
                        message=str(err),
                    )
                self.node.get_logger().error(
                    f"[{self.robot_name}] failed to send drive goal: {err}"
                )
                done.set()
                return

            if not goal_handle.accepted:
                with self._lock:
                    self._state = CommandState(
                        status="rejected",
                        completed=True,
                        failed=True,
                        retryable=True,
                        message="Drive manager rejected goal",
                    )
                self.node.get_logger().warn(
                    f"[{self.robot_name}] drive manager rejected goal {pose}"
                )
                done.set()
                return

            result_future = goal_handle.get_result_async()
            result_future.add_done_callback(self._result_callback)
            with self._lock:
                self._goal_handle = goal_handle
                self._result_future = result_future
                self._state = CommandState(status="executing")
            accepted["value"] = True
            self.node.get_logger().info(
                f"[{self.robot_name}] drive manager accepted {command_mode} goal "
                f"[{destination_name}]"
            )
            done.set()

        send_future.add_done_callback(goal_response_callback)
        if not done.wait(self._goal_timeout):
            with self._lock:
                self._state = CommandState(
                    status="pending",
                    completed=False,
                    failed=False,
                    message="Timed out waiting for drive goal acceptance",
                )
            self.node.get_logger().warn(
                f"[{self.robot_name}] timed out waiting for drive goal acceptance"
            )
            return False

        return accepted["value"]

    def _result_callback(self, future):
        with self._lock:
            if future is not self._result_future:
                return

        try:
            result = future.result().result
        except Exception as err:
            with self._lock:
                self._state = CommandState(
                    status="failed", completed=True, failed=True, message=str(err)
                )
            self.node.get_logger().error(
                f"[{self.robot_name}] drive result failed: {err}"
            )
            return

        failed = not bool(result.success)
        status = "succeeded" if result.success else result.final_state or "failed"
        with self._lock:
            self._state = CommandState(
                status=status,
                completed=True,
                failed=failed,
                retryable=bool(result.retryable),
                message=result.message,
            )
            self._goal_handle = None
            self._result_future = None

        if failed:
            self.node.get_logger().warn(
                f"[{self.robot_name}] drive command failed in [{status}]: "
                f"{result.message}"
            )
        else:
            self.node.get_logger().info(
                f"[{self.robot_name}] drive command completed successfully"
            )

    def cancel_goal(self) -> bool:
        with self._lock:
            goal_handle = self._goal_handle
            self._state.status = "canceling"

        if goal_handle is not None:
            try:
                goal_handle.cancel_goal_async()
            except Exception as err:
                self.node.get_logger().warn(
                    f"[{self.robot_name}] failed to cancel drive goal: {err}"
                )

        request = Stop.Request()
        request.robot_name = self.robot_name
        request.request_id = f"{self.robot_name}_{uuid.uuid4().hex[:12]}"
        try:
            self._stop_client.call_async(request)
        except Exception as err:
            self.node.get_logger().warn(
                f"[{self.robot_name}] failed to call drive Stop service: {err}"
            )
            return False
        return True

    def position(self) -> list[float] | None:
        drive_state = self.drive_state()
        if drive_state is None or drive_state.state == "unknown":
            return None
        return [float(v) for v in drive_state.pose]

    def battery_soc(self) -> float | None:
        drive_state = self.drive_state()
        if drive_state is None:
            return None
        soc = float(drive_state.battery_soc)
        if math.isnan(soc):
            return None
        return min(1.0, max(0.0, soc))

    def map_name(self) -> str:
        drive_state = self.drive_state()
        if drive_state is not None and drive_state.map_name:
            return drive_state.map_name
        return self.rmf_level

    def is_available(self) -> bool:
        drive_state = self.drive_state()
        return bool(drive_state and drive_state.available and not drive_state.emergency)

    def drive_state(self) -> DriveState | None:
        with self._lock:
            state = self._drive_state
            state_time = self._drive_state_time
        if state is None or state_time is None:
            return None

        age = self.node.get_clock().now() - state_time
        if age.nanoseconds > self.state_timeout * 1e9:
            return None
        return state

    def is_command_completed(self) -> bool:
        with self._lock:
            return self._state.completed

    def requires_replan(self) -> bool:
        drive_state = self.drive_state()
        if drive_state is not None and (
            drive_state.emergency or drive_state.state in ("blocked", "error")
        ):
            return True
        with self._lock:
            return self._state.failed
