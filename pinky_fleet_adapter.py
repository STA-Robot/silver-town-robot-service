import argparse
import math
import sys
import threading
import time

import numpy as np
import rclpy
import rclpy.executors
import rclpy.node
import yaml
from rclpy.duration import Duration
from rclpy.parameter import Parameter

import rmf_adapter
from rmf_adapter import Adapter, Transformation
import rmf_adapter.easy_full_control as rmf_easy

from .robot_client_api import RobotAPI


def compute_transform(level: str, coords: dict, node=None) -> Transformation:
    """Estimate a 2D similarity transform from RMF to robot coordinates."""
    rmf_coords = np.asarray(coords.get("rmf", []), dtype=float)
    robot_coords = np.asarray(coords.get("robot", []), dtype=float)

    if rmf_coords.shape != robot_coords.shape or rmf_coords.shape[0] < 2:
        if node:
            node.get_logger().warn(
                f"Reference coordinates for [{level}] are incomplete; using identity"
            )
        return Transformation(0.0, 1.0, np.array([0.0, 0.0]))

    src_centroid = rmf_coords.mean(axis=0)
    dst_centroid = robot_coords.mean(axis=0)
    src = rmf_coords - src_centroid
    dst = robot_coords - dst_centroid

    denom = float(np.sum(src * src))
    if denom <= 1e-12:
        if node:
            node.get_logger().warn(
                f"Reference coordinates for [{level}] are degenerate; using identity"
            )
        return Transformation(0.0, 1.0, np.array([0.0, 0.0]))

    u, singular_values, vh = np.linalg.svd(src.T @ dst)
    rotation_matrix = vh.T @ u.T
    if np.linalg.det(rotation_matrix) < 0:
        vh[-1, :] *= -1.0
        rotation_matrix = vh.T @ u.T

    scale = float(np.sum(singular_values) / denom)
    rotation = math.atan2(rotation_matrix[1, 0], rotation_matrix[0, 0])
    translation = dst_centroid - scale * rotation_matrix @ src_centroid

    if node:
        transformed = (scale * (rotation_matrix @ rmf_coords.T)).T + translation
        mse = float(np.mean(np.sum((transformed - robot_coords) ** 2, axis=1)))
        node.get_logger().info(
            f"Transformation error estimate for [{level}]: {mse:.6f}"
        )

    return Transformation(rotation, scale, translation)


def main(argv=sys.argv):
    rclpy.init(args=argv)
    rmf_adapter.init_rclcpp()

    args_without_ros = rclpy.utilities.remove_ros_args(argv)
    parser = argparse.ArgumentParser(
        prog="pinky_fleet_adapter",
        description="Start the Pinky RMF full-control fleet adapter",
    )
    parser.add_argument("-c", "--config_file", type=str, required=True)
    parser.add_argument("-n", "--nav_graph", type=str, required=True)
    parser.add_argument("-s", "--server_uri", type=str, default="")
    parser.add_argument("-sim", "--use_sim_time", action="store_true")
    args = parser.parse_args(args_without_ros[1:])

    config_path = args.config_file
    nav_graph_path = args.nav_graph
    server_uri = args.server_uri if args.server_uri else None

    fleet_config = rmf_easy.FleetConfiguration.from_config_files(
        config_path, nav_graph_path, server_uri
    )
    assert fleet_config, f"Failed to parse config file [{config_path}]"

    with open(config_path, "r") as f:
        config_yaml = yaml.safe_load(f)

    fleet_name = fleet_config.fleet_name
    node = rclpy.node.Node(f"{fleet_name}_pinky_command_handle")
    adapter = Adapter.make(f"{fleet_name}_pinky_fleet_adapter")
    if not adapter:
        raise RuntimeError(
            "Unable to initialize fleet adapter. Start the RMF schedule node "
            "first, e.g. `ros2 run rmf_traffic_ros2 rmf_traffic_schedule`, "
            "or launch with `start_schedule:=true`."
        )

    if args.use_sim_time:
        param = Parameter("use_sim_time", Parameter.Type.BOOL, True)
        node.set_parameters([param])
        adapter.node.use_sim_time()

    if server_uri is not None:
        fleet_config.server_uri = server_uri

    rmf_fleet_config = config_yaml.get("rmf_fleet", {})
    merge_waypoint_distance = rmf_fleet_config.get("max_merge_waypoint_distance")
    if merge_waypoint_distance is not None:
        fleet_config.default_max_merge_waypoint_distance = float(
            merge_waypoint_distance
        )
        node.get_logger().info(
            "Configured max merge waypoint distance: "
            f"{fleet_config.default_max_merge_waypoint_distance:.3f} m"
        )

    merge_lane_distance = rmf_fleet_config.get("max_merge_lane_distance")
    if merge_lane_distance is not None:
        fleet_config.default_max_merge_lane_distance = float(merge_lane_distance)
        node.get_logger().info(
            "Configured max merge lane distance: "
            f"{fleet_config.default_max_merge_lane_distance:.3f} m"
        )

    for level, coords in config_yaml.get("reference_coordinates", {}).items():
        fleet_config.add_robot_coordinates_transformation(
            level, compute_transform(level, coords, node)
        )

    adapter.start()
    time.sleep(1.0)
    fleet_handle = adapter.add_easy_fleet(fleet_config)
    api = RobotAPI(config_yaml.get("fleet_manager", {}), node)

    robots = {}
    for robot_name in fleet_config.known_robots:
        robot_config = fleet_config.get_known_robot_configuration(robot_name)
        robots[robot_name] = RobotAdapter(
            robot_name, robot_config, node, api, fleet_handle
        )

    update_frequency = float(rmf_fleet_config.get("robot_state_update_frequency", 10.0))
    update_period = 1.0 / max(update_frequency, 0.1)
    stop_update = threading.Event()

    def update_loop():
        while rclpy.ok() and not stop_update.is_set():
            now = node.get_clock().now()
            for robot in robots.values():
                update_robot(robot)
            next_wakeup = now + Duration(seconds=update_period)
            while (
                rclpy.ok()
                and not stop_update.is_set()
                and node.get_clock().now() < next_wakeup
            ):
                time.sleep(0.001)

    update_thread = threading.Thread(target=update_loop, daemon=True)
    update_thread.start()

    executor = rclpy.executors.SingleThreadedExecutor()
    executor.add_node(node)
    node.get_logger().info("Pinky RMF fleet adapter is running")

    try:
        executor.spin()
    finally:
        stop_update.set()
        update_thread.join(timeout=1.0)
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


class RobotAdapter:
    def __init__(self, name: str, configuration, node, api: RobotAPI, fleet_handle):
        self.name = name
        self.execution = None
        self.update_handle = None
        self.configuration = configuration
        self.node = node
        self.api = api
        self.fleet_handle = fleet_handle

    def update(self, state):
        activity_identifier = None
        execution = self.execution
        if execution:
            if self.api.requires_replan(self.name):
                self.node.get_logger().warn(
                    f"[{self.name}] drive state requires replan"
                )
                self._request_replan()
                execution.finished()
                self.execution = None
            elif self.api.is_command_completed(self.name):
                execution.finished()
                self.execution = None
            else:
                activity_identifier = execution.identifier

        self.update_handle.update(state, activity_identifier)

    def make_callbacks(self):
        callbacks = rmf_easy.RobotCallbacks(
            lambda destination, execution: self.navigate(destination, execution),
            lambda activity: self.stop(activity),
            lambda category, description, execution: self.execute_action(
                category, description, execution
            ),
        )
        callbacks.localize = lambda estimate, execution: self.localize(
            estimate, execution
        )
        return callbacks

    def localize(self, estimate, execution):
        self.node.get_logger().info(
            f"Commanding [{self.name}] to localize on [{estimate.map}]"
        )
        if self.api.localize(self.name, estimate.position, estimate.map):
            execution.finished()
            return

        self.node.get_logger().warn(
            f"Failed to localize [{self.name}] on [{estimate.map}]"
        )
        self._request_replan()

    def navigate(self, destination, execution):
        self.execution = execution
        destination_name = getattr(destination, "name", "") or ""
        command_mode = "returning" if destination_name == "start" else "task"
        self.node.get_logger().info(
            f"Commanding [{self.name}] to navigate to {destination.position} "
            f"on map [{destination.map}] as [{command_mode}]"
        )
        accepted = self.api.navigate(
            self.name,
            destination.position,
            destination.map,
            destination.speed_limit,
            destination_name,
            command_mode,
        )
        if not accepted:
            self.node.get_logger().warn(
                f"[{self.name}] navigation request was rejected"
            )
            self._request_replan()
            self.execution = None

    def stop(self, activity):
        execution = self.execution
        if execution is not None:
            try:
                same_activity = execution.identifier.is_same(activity)
            except AttributeError:
                same_activity = True
            if same_activity:
                self.execution = None
        self.api.stop(self.name)

    def execute_action(self, category: str, description: dict, execution):
        del description
        self.node.get_logger().warn(
            f"[{self.name}] action category [{category}] is not implemented"
        )
        execution.finished()

    def _request_replan(self):
        if self.update_handle is None:
            return
        more = self.update_handle.more()
        if more is not None:
            more.replan()


def update_robot(robot: RobotAdapter):
    data = robot.api.get_data(robot.name)
    if data is None:
        return

    if data.emergency or data.state in ("blocked", "error"):
        robot.node.get_logger().warn(
            f"[{robot.name}] drive state [{data.state}], available={data.available}"
        )

    state = rmf_easy.RobotState(data.map, np.asarray(data.position), data.battery_soc)
    if robot.update_handle is None:
        robot.update_handle = robot.fleet_handle.add_robot(
            robot.name, state, robot.configuration, robot.make_callbacks()
        )
        robot.node.get_logger().info(f"Added [{robot.name}] to RMF fleet")
        return

    robot.update(state)


if __name__ == "__main__":
    main(sys.argv)
