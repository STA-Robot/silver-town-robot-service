import math
import sys
import threading
import time

import rclpy
from control_msgs.action import FollowJointTrajectory
from rclpy.action import ActionServer, GoalResponse
from rclpy.node import Node
from sensor_msgs.msg import JointState


ARM_JOINT_NAMES = (
    "joint2_to_joint1",
    "joint3_to_joint2",
    "joint4_to_joint3",
    "joint5_to_joint4",
    "joint6_to_joint5",
    "joint6output_to_joint6",
)
GRIPPER_JOINT_NAME = "gripper_controller"
ALL_JOINT_NAMES = ARM_JOINT_NAMES + (GRIPPER_JOINT_NAME,)

ARM_ACTION_NAME = "/arm_controller/follow_joint_trajectory"
GRIPPER_ACTION_NAME = "/gripper_controller/follow_joint_trajectory"

GRIPPER_OPEN_COMMAND = 0
GRIPPER_CLOSE_COMMAND = 1
GRIPPER_OPEN_THRESHOLD_RAD = -0.15


class JetCobotTrajectoryDriver(Node):
    def __init__(self):
        super().__init__("jetcobot_trajectory_driver")

        self.declare_parameter("port", "/dev/ttyJETCOBOT")
        self.declare_parameter("baud", 1000000)
        self.declare_parameter("speed", 25)
        self.declare_parameter("gripper_speed", 80)
        self.declare_parameter("joint_state_rate", 20.0)
        self.declare_parameter("wait_for_motion", True)
        self.declare_parameter("motion_timeout", 15.0)
        self.declare_parameter("joint_tolerance_deg", 3.0)
        self.declare_parameter("poll_interval", 0.2)
        self.declare_parameter("gripper_wait_seconds", 1.0)

        self._port = self.get_parameter("port").value
        self._baud = int(self.get_parameter("baud").value)
        self._speed = int(self.get_parameter("speed").value)
        self._gripper_speed = int(self.get_parameter("gripper_speed").value)
        self._joint_state_rate = float(self.get_parameter("joint_state_rate").value)
        self._wait_for_motion = self._parameter_bool("wait_for_motion")
        self._motion_timeout = float(self.get_parameter("motion_timeout").value)
        self._joint_tolerance_deg = float(
            self.get_parameter("joint_tolerance_deg").value
        )
        self._poll_interval = float(self.get_parameter("poll_interval").value)
        self._gripper_wait_seconds = float(
            self.get_parameter("gripper_wait_seconds").value
        )
        self._motion_timeout = max(0.1, self._motion_timeout)
        self._joint_tolerance_deg = max(0.0, self._joint_tolerance_deg)
        self._poll_interval = max(0.01, self._poll_interval)
        self._gripper_wait_seconds = max(0.0, self._gripper_wait_seconds)

        self._lock = threading.Lock()
        self._positions = {joint_name: 0.0 for joint_name in ALL_JOINT_NAMES}

        self._mc = self._connect_robot()

        self._joint_state_pub = self.create_publisher(JointState, "/joint_states", 10)
        timer_period = 1.0 / self._joint_state_rate
        self._joint_state_timer = self.create_timer(
            timer_period, self._publish_joint_states
        )

        self._arm_server = ActionServer(
            self,
            FollowJointTrajectory,
            ARM_ACTION_NAME,
            execute_callback=self._execute_arm_goal,
            goal_callback=self._validate_arm_goal,
        )
        self._gripper_server = ActionServer(
            self,
            FollowJointTrajectory,
            GRIPPER_ACTION_NAME,
            execute_callback=self._execute_gripper_goal,
            goal_callback=self._validate_gripper_goal,
        )

        self.get_logger().info(
            f"JetCobot driver ready on {self._port} at {self._baud} baud"
        )

    def _connect_robot(self):
        try:
            from pymycobot import MyCobot280
        except Exception as exc:
            self.get_logger().error(f"Failed to import pymycobot.MyCobot280: {exc}")
            raise

        try:
            robot = MyCobot280(self._port, self._baud)
        except Exception as exc:
            self.get_logger().error(
                f"Failed to connect to JetCobot on {self._port} at {self._baud}: {exc}"
            )
            raise

        if robot is None:
            raise RuntimeError(
                f"pymycobot.MyCobot280 returned None for {self._port} "
                f"at {self._baud} baud"
            )

        return robot

    def _parameter_bool(self, name):
        value = self.get_parameter(name).value
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _validate_arm_goal(self, goal_request):
        error = self._validate_trajectory(goal_request.trajectory, ARM_JOINT_NAMES)
        if error:
            self.get_logger().warn(f"Rejecting arm trajectory: {error}")
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def _validate_gripper_goal(self, goal_request):
        error = self._validate_trajectory(
            goal_request.trajectory, (GRIPPER_JOINT_NAME,)
        )
        if error:
            self.get_logger().warn(f"Rejecting gripper trajectory: {error}")
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def _validate_trajectory(self, trajectory, required_joint_names):
        if not trajectory.points:
            return "trajectory has no points"

        joint_names = list(trajectory.joint_names)
        missing = [name for name in required_joint_names if name not in joint_names]
        if missing:
            return f"missing joints: {', '.join(missing)}"

        final_positions = trajectory.points[-1].positions
        if len(final_positions) < len(joint_names):
            return "final point does not include a position for each trajectory joint"

        return None

    def _execute_arm_goal(self, goal_handle):
        result = FollowJointTrajectory.Result()
        trajectory = goal_handle.request.trajectory

        try:
            final_positions = self._positions_for_joints(trajectory, ARM_JOINT_NAMES)
            final_degrees = [math.degrees(position) for position in final_positions]

            with self._lock:
                self._mc.send_angles(final_degrees, self._speed)
                for joint_name, position in zip(ARM_JOINT_NAMES, final_positions):
                    self._positions[joint_name] = position

            if self._wait_for_motion:
                reached, message = self._wait_for_arm_target(final_degrees)
                if not reached:
                    goal_handle.abort()
                    result.error_code = (
                        FollowJointTrajectory.Result.GOAL_TOLERANCE_VIOLATED
                    )
                    result.error_string = message
                    self.get_logger().error(message)
                    return result

            goal_handle.succeed()
            result.error_code = FollowJointTrajectory.Result.SUCCESSFUL
            result.error_string = (
                "arm target reached" if self._wait_for_motion else "arm command sent"
            )
            self.get_logger().info(f"Sent arm target: {final_degrees}")
        except Exception as exc:
            goal_handle.abort()
            result.error_code = FollowJointTrajectory.Result.INVALID_GOAL
            result.error_string = f"failed to send arm command: {exc}"
            self.get_logger().error(result.error_string)

        return result

    def _execute_gripper_goal(self, goal_handle):
        result = FollowJointTrajectory.Result()
        trajectory = goal_handle.request.trajectory

        try:
            target_position = self._positions_for_joints(
                trajectory, (GRIPPER_JOINT_NAME,)
            )[0]
            command = (
                GRIPPER_OPEN_COMMAND
                if target_position > GRIPPER_OPEN_THRESHOLD_RAD
                else GRIPPER_CLOSE_COMMAND
            )

            with self._lock:
                self._mc.set_gripper_state(command, self._gripper_speed, 1)
                self._positions[GRIPPER_JOINT_NAME] = target_position

            if self._wait_for_motion and self._gripper_wait_seconds > 0.0:
                time.sleep(self._gripper_wait_seconds)

            goal_handle.succeed()
            result.error_code = FollowJointTrajectory.Result.SUCCESSFUL
            result.error_string = (
                "gripper wait complete"
                if self._wait_for_motion
                else "gripper command sent"
            )
            self.get_logger().info(
                f"Sent gripper target {target_position:.3f} rad as command {command}"
            )
        except Exception as exc:
            goal_handle.abort()
            result.error_code = FollowJointTrajectory.Result.INVALID_GOAL
            result.error_string = f"failed to send gripper command: {exc}"
            self.get_logger().error(result.error_string)

        return result

    def _positions_for_joints(self, trajectory, ordered_joint_names):
        final_positions = trajectory.points[-1].positions
        joint_index = {
            joint_name: index for index, joint_name in enumerate(trajectory.joint_names)
        }
        return [
            final_positions[joint_index[joint_name]]
            for joint_name in ordered_joint_names
        ]

    def _wait_for_arm_target(self, target_degrees):
        deadline = time.monotonic() + self._motion_timeout
        last_error = math.inf
        last_degrees = None

        while time.monotonic() < deadline:
            current_degrees = self._read_arm_angles_degrees()
            if current_degrees is None:
                time.sleep(self._poll_interval)
                continue

            last_degrees = current_degrees
            errors = [
                abs(current - target)
                for current, target in zip(current_degrees, target_degrees)
            ]
            last_error = max(errors)
            current_positions = [
                math.radians(angle_degrees) for angle_degrees in current_degrees
            ]
            with self._lock:
                for joint_name, position in zip(ARM_JOINT_NAMES, current_positions):
                    self._positions[joint_name] = position
            self._publish_joint_states()

            if last_error <= self._joint_tolerance_deg:
                return True, (
                    f"arm target reached within {last_error:.2f} deg "
                    f"(tolerance {self._joint_tolerance_deg:.2f} deg)"
                )

            time.sleep(self._poll_interval)

        if last_degrees is None:
            return False, (
                "arm motion timed out before valid joint angles were read "
                f"(timeout {self._motion_timeout:.1f}s)"
            )

        return False, (
            f"arm motion timed out: max error {last_error:.2f} deg "
            f"exceeds tolerance {self._joint_tolerance_deg:.2f} deg; "
            f"target={self._format_degrees(target_degrees)} "
            f"current={self._format_degrees(last_degrees)}"
        )

    def _read_arm_angles_degrees(self):
        try:
            with self._lock:
                angles = self._mc.get_angles()
        except Exception as exc:
            self.get_logger().warn(f"failed to read arm angles: {exc}")
            return None

        if angles is None:
            self.get_logger().warn(f"invalid arm angle response: {angles}")
            return None

        if not isinstance(angles, (list, tuple)):
            self.get_logger().warn(
                f"invalid arm angle response type "
                f"{type(angles).__name__}: {angles}"
            )
            return None

        if len(angles) < len(ARM_JOINT_NAMES):
            self.get_logger().warn(f"invalid arm angle response: {angles}")
            return None

        try:
            return [float(angle) for angle in angles[: len(ARM_JOINT_NAMES)]]
        except (TypeError, ValueError):
            self.get_logger().warn(f"non-numeric arm angle response: {angles}")
            return None

    @staticmethod
    def _format_degrees(degrees):
        return "[" + ", ".join(f"{degree:.1f}" for degree in degrees) + "]"

    def _publish_joint_states(self):
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = list(ALL_JOINT_NAMES)

        with self._lock:
            msg.position = [
                self._positions[joint_name] for joint_name in ALL_JOINT_NAMES
            ]

        self._joint_state_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = JetCobotTrajectoryDriver()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"jetcobot_driver startup failed: {exc}", file=sys.stderr)
        raise
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
