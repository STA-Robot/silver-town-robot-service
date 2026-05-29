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
from jetcobot_workcell_msgs.msg import WorkcellCommand, WorkcellState
from moveit_msgs.action import MoveGroup
from moveit_msgs.msg import Constraints, JointConstraint, MoveItErrorCodes
from rclpy.action import ActionClient
from rclpy.node import Node


STATE_UNKNOWN = "unknown"
STATE_IDLE = "idle"
STATE_RESERVED = "reserved"
STATE_PICKING = "picking"
STATE_PLACING = "placing"
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

DEFAULT_ARM_JOINT_NAMES = [
    "joint2_to_joint1",
    "joint3_to_joint2",
    "joint4_to_joint3",
    "joint5_to_joint4",
    "joint6_to_joint5",
    "joint6output_to_joint6",
]
DEFAULT_GRIPPER_JOINT_NAMES = ["gripper_controller"]
RUNNING_STATES = {STATE_RESERVED, STATE_PICKING, STATE_PLACING, STATE_HOMING}


class ConfigError(ValueError):
    pass


def default_config_file() -> str:
    try:
        share_dir = get_package_share_directory("jetcobot_driver")
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
    joint_names = config.setdefault("joint_names", {})
    joint_names.setdefault("arm", list(DEFAULT_ARM_JOINT_NAMES))
    joint_names.setdefault("gripper", list(DEFAULT_GRIPPER_JOINT_NAMES))

    targets = config.get("joint_targets")
    if not isinstance(targets, dict) or not targets:
        raise ConfigError("joint_targets must contain at least one target")

    for target_name, target in targets.items():
        if not isinstance(target, dict):
            raise ConfigError(f"target [{target_name}] must be a mapping")
        group = str(target.get("group", ""))
        if group not in joint_names:
            raise ConfigError(f"target [{target_name}] has unknown group [{group}]")
        positions = target.get("positions")
        if not isinstance(positions, list):
            raise ConfigError(f"target [{target_name}] positions must be a list")
        expected_count = len(joint_names[group])
        if len(positions) != expected_count:
            raise ConfigError(
                f"target [{target_name}] has {len(positions)} positions, "
                f"expected {expected_count} for group [{group}]"
            )
        target["positions"] = [float(position) for position in positions]

    sequence = config.get("pick_and_place_sequence")
    if not isinstance(sequence, list) or not sequence:
        raise ConfigError("pick_and_place_sequence must contain at least one step")
    for index, step in enumerate(sequence):
        if not isinstance(step, dict):
            raise ConfigError(f"sequence step {index} must be a mapping")
        target_name = str(step.get("target", ""))
        if target_name not in targets:
            raise ConfigError(
                f"sequence step {index} references unknown target [{target_name}]"
            )

    motion = config.setdefault("motion", {})
    motion.setdefault("move_group_server_timeout", 5.0)
    motion.setdefault("allowed_planning_time", 5.0)
    motion.setdefault("planning_attempts", 3)
    motion.setdefault("velocity_scaling", 0.1)
    motion.setdefault("acceleration_scaling", 0.1)
    motion.setdefault("joint_tolerance", 0.02)
    motion.setdefault("replan", True)
    motion.setdefault("replan_attempts", 2)
    motion.setdefault("replan_delay", 0.1)
    motion.setdefault("seconds_per_step_estimate", 3.0)
    return config


class JetCobotArmManager(Node):
    def __init__(self):
        super().__init__("jetcobot_arm_manager")

        self.declare_parameter("arm_name", "jetcobot1")
        self.declare_parameter("command_topic", "/command")
        self.declare_parameter("state_topic", "/state")
        self.declare_parameter("move_group_action", "/move_action")
        self.declare_parameter("arm_group", "arm")
        self.declare_parameter("gripper_group", "gripper")
        self.declare_parameter("config_file", default_config_file())
        self.declare_parameter("state_publish_frequency", 10.0)
        self.declare_parameter("qos_depth", 10)
        self.declare_parameter("recent_command_cache_size", 50)

        self.arm_name = str(self.get_parameter("arm_name").value)
        self.command_topic = str(self.get_parameter("command_topic").value)
        self.state_topic = str(self.get_parameter("state_topic").value)
        self.move_group_action = str(self.get_parameter("move_group_action").value)
        self.arm_group = str(self.get_parameter("arm_group").value)
        self.gripper_group = str(self.get_parameter("gripper_group").value)
        self.config_file = str(self.get_parameter("config_file").value)
        self.config = load_arm_manager_config(self.config_file)

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
        self._sequence_index = 0
        self._current_goal_handle = None
        self._completed_command_ids = deque(maxlen=max(1, recent_cache_size))

        self._move_group_client = ActionClient(
            self,
            MoveGroup,
            self.move_group_action,
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
            f"move_group=[{self.move_group_action}] config=[{self.config_file}]"
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
        self._accept_command(command, STATE_RESERVED)
        self._active_command_type = COMMAND_PICK_AND_PLACE
        self._sequence_index = 0
        self._send_next_sequence_step()

    def _handle_stop(self, command: WorkcellCommand) -> None:
        stopped_command_id = self.active_command_id
        self._cancel_current_goal()
        self.command_active = False
        self.active_command_id = ""
        self._active_command_type = ""
        self._sequence_index = 0
        self.progress = 0.0
        self.seconds_remaining = 0.0
        self.last_command_id = command.command_id
        self.last_command_status = COMMAND_SUCCEEDED
        self.state = STATE_BLOCKED
        self.available = False
        self.message = (
            f"motion stopped while running {stopped_command_id}"
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
        self._sequence_index = 0
        self.progress = 0.0
        self.seconds_remaining = 0.0
        self.last_command_id = command.command_id
        self.last_command_status = COMMAND_SUCCEEDED
        self.state = STATE_IDLE
        self.available = True
        self.message = "reset complete"
        if command.command_id:
            self._completed_command_ids.append(command.command_id)

    def _accept_command(self, command: WorkcellCommand, state: str) -> None:
        self.command_active = True
        self.active_command_id = command.command_id
        self.last_command_id = command.command_id
        self.last_command_status = COMMAND_ACCEPTED
        self.mission_id = command.mission_id
        self.progress = 0.0
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
        self._sequence_index = 0
        self.progress = 1.0 if status == COMMAND_SUCCEEDED else 0.0
        self.seconds_remaining = 0.0
        self._transition(final_state, message)
        if command_id:
            self._completed_command_ids.append(command_id)
        self._publish_state()

    def _send_next_sequence_step(self) -> None:
        if not self.command_active or not self.active_command_id:
            return

        sequence = self.config["pick_and_place_sequence"]
        if self._sequence_index >= len(sequence):
            self._finish_command(
                self.active_command_id,
                COMMAND_SUCCEEDED,
                "pick and place sequence completed",
                STATE_IDLE,
            )
            return

        if not self._move_group_client.wait_for_server(
            timeout_sec=float(self.config["motion"]["move_group_server_timeout"])
        ):
            self._finish_command(
                self.active_command_id,
                COMMAND_FAILED,
                "MoveGroup action server is not ready",
                STATE_BLOCKED,
            )
            return

        command_id = self.active_command_id
        step = sequence[self._sequence_index]
        target_name = str(step["target"])
        state = str(step.get("state", STATE_RESERVED))
        message = str(step.get("message", f"moving to {target_name}"))

        self._transition(state, message)
        self._update_progress()
        self._publish_state()

        goal = self._build_move_group_goal(target_name)
        send_future = self._move_group_client.send_goal_async(goal)
        send_future.add_done_callback(
            lambda future: self._move_goal_response_callback(
                command_id,
                target_name,
                future,
            )
        )

    def _build_move_group_goal(self, target_name: str) -> MoveGroup.Goal:
        target = self.config["joint_targets"][target_name]
        group = str(target["group"])
        motion = self.config["motion"]

        goal = MoveGroup.Goal()
        goal.request.group_name = self._moveit_group_name(group)
        goal.request.num_planning_attempts = int(motion["planning_attempts"])
        goal.request.allowed_planning_time = float(motion["allowed_planning_time"])
        goal.request.max_velocity_scaling_factor = float(motion["velocity_scaling"])
        goal.request.max_acceleration_scaling_factor = float(
            motion["acceleration_scaling"]
        )
        goal.request.goal_constraints = [self._joint_constraints_for_target(target)]
        goal.planning_options.plan_only = False
        goal.planning_options.replan = bool(motion["replan"])
        goal.planning_options.replan_attempts = int(motion["replan_attempts"])
        goal.planning_options.replan_delay = float(motion["replan_delay"])
        return goal

    def _moveit_group_name(self, configured_group: str) -> str:
        if configured_group == "arm":
            return self.arm_group
        if configured_group == "gripper":
            return self.gripper_group
        return configured_group

    def _joint_constraints_for_target(self, target: dict[str, Any]) -> Constraints:
        group = str(target["group"])
        joint_names = self.config["joint_names"][group]
        positions = target["positions"]
        tolerance = float(self.config["motion"]["joint_tolerance"])

        constraints = Constraints()
        constraints.name = str(target.get("name", group))
        for joint_name, position in zip(joint_names, positions):
            joint_constraint = JointConstraint()
            joint_constraint.joint_name = str(joint_name)
            joint_constraint.position = float(position)
            joint_constraint.tolerance_above = tolerance
            joint_constraint.tolerance_below = tolerance
            joint_constraint.weight = 1.0
            constraints.joint_constraints.append(joint_constraint)
        return constraints

    def _move_goal_response_callback(
        self,
        command_id: str,
        target_name: str,
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
                f"MoveGroup goal send failed for {target_name}: {exc}",
                STATE_BLOCKED,
            )
            return

        if not goal_handle.accepted:
            self._finish_command(
                command_id,
                COMMAND_REJECTED,
                f"MoveGroup rejected target {target_name}",
                STATE_BLOCKED,
            )
            return

        self._current_goal_handle = goal_handle
        self.message = f"MoveGroup accepted target {target_name}"
        self._publish_state()

        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(
            lambda result: self._move_result_callback(
                command_id,
                target_name,
                result,
            )
        )

    def _move_result_callback(
        self,
        command_id: str,
        target_name: str,
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
                f"MoveGroup result failed for {target_name}: {exc}",
                STATE_BLOCKED,
            )
            return

        self._current_goal_handle = None
        moveit_error = action_result.result.error_code
        if (
            action_result.status == GoalStatus.STATUS_SUCCEEDED
            and moveit_error.val == MoveItErrorCodes.SUCCESS
        ):
            self._sequence_index += 1
            self._update_progress()
            self._send_next_sequence_step()
            return

        if action_result.status == GoalStatus.STATUS_CANCELED:
            self._finish_command(
                command_id,
                COMMAND_CANCELED,
                f"MoveGroup canceled target {target_name}",
                STATE_BLOCKED,
            )
            return

        detail = moveit_error.message or f"error code {moveit_error.val}"
        self._finish_command(
            command_id,
            COMMAND_FAILED,
            f"MoveGroup failed target {target_name}: {detail}",
            STATE_BLOCKED,
        )

    def _cancel_current_goal(self) -> None:
        if self._current_goal_handle is not None:
            self._current_goal_handle.cancel_goal_async()
            self._current_goal_handle = None

    def _update_progress(self) -> None:
        sequence_len = len(self.config["pick_and_place_sequence"])
        if sequence_len <= 0:
            self.progress = 0.0
            self.seconds_remaining = 0.0
            return

        self.progress = min(1.0, max(0.0, self._sequence_index / sequence_len))
        remaining_steps = max(0, sequence_len - self._sequence_index)
        self.seconds_remaining = float(
            remaining_steps * self.config["motion"]["seconds_per_step_estimate"]
        )

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
