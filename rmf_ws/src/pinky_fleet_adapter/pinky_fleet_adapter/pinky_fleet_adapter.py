# Copyright 2021 Open Source Robotics Foundation, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sys
import argparse
import yaml
import time
import threading
import asyncio
import math
import json
import nudged

import rclpy
import rclpy.node
from rclpy.parameter import Parameter
from rclpy.duration import Duration
from std_msgs.msg import String

import rmf_adapter
from rmf_adapter import Adapter
import rmf_adapter.easy_full_control as rmf_easy
from rmf_adapter import Transformation

from .RobotClientAPI import RobotAPI


# ------------------------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------------------------
def compute_transforms(level, coords, node=None):
    """Get transforms between RMF and robot coordinates."""
    rmf_coords = coords['rmf']
    robot_coords = coords['robot']
    tf = nudged.estimate(rmf_coords, robot_coords)
    if node:
        mse = nudged.estimate_error(tf, rmf_coords, robot_coords)
        node.get_logger().info(
            f"Transformation error estimate for {level}: {mse}"
        )

    return Transformation(
        tf.get_rotation(),
        tf.get_scale(),
        tf.get_translation()
    )

# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------
def main(argv=sys.argv):
    # Init rclpy and adapter
    rclpy.init(args=argv)
    rmf_adapter.init_rclcpp()
    args_without_ros = rclpy.utilities.remove_ros_args(argv)

    parser = argparse.ArgumentParser(
        prog="fleet_adapter",
        description="Configure and spin up the fleet adapter")
    parser.add_argument("-c", "--config_file", type=str, required=True,
                        help="Path to the config.yaml file")
    parser.add_argument("-n", "--nav_graph", type=str, required=True,
                        help="Path to the nav_graph for this fleet adapter")
    parser.add_argument("-s", "--server_uri", type=str, required=False, default="",
                        help="URI of the api server to transmit state and task information.")
    parser.add_argument("-sim", "--use_sim_time", action="store_true",
                        help='Use sim time, default: false')
    args = parser.parse_args(args_without_ros[1:])
    print(f"Starting fleet adapter...")

    config_path = args.config_file
    nav_graph_path = args.nav_graph

    fleet_config = rmf_easy.FleetConfiguration.from_config_files(
        config_path, nav_graph_path
    )
    assert fleet_config, f'Failed to parse config file [{config_path}]'

    # Parse the yaml in Python to get the fleet_manager info
    with open(config_path, "r") as f:
        config_yaml = yaml.safe_load(f)

    # ROS 2 node for the command handle
    fleet_name = fleet_config.fleet_name
    node = rclpy.node.Node(f'{fleet_name}_command_handle')
    adapter = Adapter.make(f'{fleet_name}_fleet_adapter')
    assert adapter, (
        'Unable to initialize fleet adapter. '
        'Please ensure RMF Schedule Node is running'
    )

    # Enable sim time for testing offline
    if args.use_sim_time:
        param = Parameter("use_sim_time", Parameter.Type.BOOL, True)
        node.set_parameters([param])
        adapter.node.use_sim_time()

    adapter.start()
    time.sleep(1.0)

    if args.server_uri == '':
        server_uri = None
    else:
        server_uri = args.server_uri

    fleet_config.server_uri = server_uri

    # Configure the transforms between robot and RMF frames
    for level, coords in config_yaml['reference_coordinates'].items():
        tf = compute_transforms(level, coords, node)
        fleet_config.add_robot_coordinates_transformation(level, tf)

    fleet_handle = adapter.add_easy_fleet(fleet_config)
    _register_performable_actions(fleet_handle, node)

    # Initialize robot API for this fleet
    fleet_mgr_yaml = config_yaml['fleet_manager']
    api = RobotAPI(fleet_mgr_yaml, node)
    task_event_topic = config_yaml['rmf_fleet'].get(
        'task_event_topic',
        '/task_events',
    )
    task_event_pub = node.create_publisher(String, task_event_topic, 10)
    node.get_logger().info(f'Publishing task events on [{task_event_topic}]')

    parking_yaws = config_yaml['rmf_fleet'].get('parking_yaws', {})
    robots = {}
    for robot_name in fleet_config.known_robots:
        robot_config = fleet_config.get_known_robot_configuration(robot_name)
        robots[robot_name] = RobotAdapter(
            robot_name,
            robot_config,
            node,
            api,
            fleet_handle,
            fleet_name,
            parking_yaws,
            task_event_pub,
        )

    update_period = 1.0/config_yaml['rmf_fleet'].get(
        'robot_state_update_frequency', 10.0
    )

    def update_loop():
        asyncio.set_event_loop(asyncio.new_event_loop())
        while rclpy.ok():
            now = node.get_clock().now()

            # Update all the robots in parallel using a thread pool
            update_jobs = []
            for robot in robots.values():
                update_jobs.append(update_robot(robot))

            asyncio.get_event_loop().run_until_complete(
                asyncio.wait(update_jobs)
            )

            next_wakeup = now + Duration(nanoseconds=update_period*1e9)
            while node.get_clock().now() < next_wakeup:
                time.sleep(0.001)

    update_thread = threading.Thread(target=update_loop, args=())
    update_thread.start()

    # Create executor for the command handle node
    rclpy_executor = rclpy.executors.SingleThreadedExecutor()
    rclpy_executor.add_node(node)

    # Start the fleet adapter
    rclpy_executor.spin()

    # Shutdown
    node.destroy_node()
    rclpy_executor.shutdown()
    rclpy.shutdown()


class RobotAdapter:
    def __init__(
        self,
        name: str,
        configuration,
        node,
        api: RobotAPI,
        fleet_handle,
        fleet_name: str,
        parking_yaws: dict | None = None,
        task_event_pub=None,
    ):
        self.name = name
        self.fleet_name = fleet_name
        self.execution = None
        self.update_handle = None
        self.configuration = configuration
        self.node = node
        self.api = api
        self.fleet_handle = fleet_handle
        self.action_timers = {}
        self.parking_yaws = parking_yaws or {}
        self.task_event_pub = task_event_pub
        self.execution_context = None

    def update(self, state):
        activity_identifier = None
        execution = self.execution
        if execution:
            if self.api.is_command_completed(self.name):
                self._publish_task_event("completed", self.execution_context)
                execution.finished()
                self.execution = None
                self.execution_context = None
            else:
                activity_identifier = execution.identifier

        self.update_handle.update(state, activity_identifier)

    def make_callbacks(self):
        callbacks = rmf_easy.RobotCallbacks(
            lambda destination, execution: self.navigate(
                destination, execution
            ),
            lambda activity: self.stop(activity),
            lambda category, description, execution: self.execute_action(
                category, description, execution
            )
        )

        callbacks.localize = lambda estimate, execution: self.localize(
            estimate, execution
        )

        return callbacks

    def localize(self, estimate, execution):
        self.node.get_logger().info(
            f'Commanding [{self.name}] to change map to'
            f' [{estimate.map}]'
        )
        if self.api.localize(self.name, estimate.position, estimate.map):
            self.node.get_logger().info(
                f'Localized [{self.name}] on {estimate.map} '
                f'at position [{estimate.position}]'
            )
            execution.finished()
        else:
            self.node.get_logger().warn(
                f'Failed to localize [{self.name}] on {estimate.map} '
                f'at position [{estimate.position}]. Requesting replanning...'
            )
            if self.update_handle is not None and self.update_handle.more() is not None:
                self.update_handle.more().replan()

    def navigate(self, destination, execution):
        self.execution = execution
        pose = list(destination.position)
        destination_name = self._destination_name(destination)
        self.execution_context = {
            "activity_type": "navigation",
            "destination_name": destination_name,
            "destination_map": str(destination.map),
            "destination_pose": pose,
        }
        parking_yaw = self.parking_yaws.get(destination_name)
        if parking_yaw is not None:
            pose[2] = self._normalize_yaw(float(parking_yaw))
            self.execution_context["destination_pose"] = pose
            self.node.get_logger().info(
                f'Applying parking yaw [{pose[2]:.3f}] for '
                f'[{self.name}] at [{destination_name}]'
            )

        self.node.get_logger().info(
            f'Commanding [{self.name}] to navigate to {pose} '
            f'on map [{destination.map}]'
        )

        self.api.navigate(
            self.name,
            pose,
            destination.map,
            destination.speed_limit
        )

    def stop(self, activity):
        execution = self.execution
        if execution is not None:
            if execution.identifier.is_same(activity):
                self._cancel_action_timer(execution)
                self.execution = None
                self.api.stop(self.name)

    def execute_action(self, category: str, description: dict, execution):
        self.execution = execution
        context = self._action_context(category, description)
        self.execution_context = context
        if category in {"wait_at_table", "wait_at_warehouse"}:
            seconds = self._wait_seconds_from_description(description)
            place = "warehouse" if category == "wait_at_warehouse" else "table"
            self.node.get_logger().info(
                f'Commanding [{self.name}] to wait at {place} for {seconds:.1f}s'
            )
            self._publish_task_event("started", context)
            self._finish_action_after_delay(
                execution,
                max(seconds, 0.001),
                context,
            )
            return

        if category == "follow":
            self.node.get_logger().info(
                f'Commanding [{self.name}] to follow person'
            )
            if not self.api.follow(self.name):
                self.node.get_logger().warn(
                    f'Failed to publish follow command for [{self.name}]'
                )
            return

        self.node.get_logger().warn(
            f'Unsupported action [{category}] for [{self.name}]'
        )
        # TODO: Decide whether unknown actions should fail, replan, or finish.
        return

    def _wait_seconds_from_description(self, description) -> float:
        if not isinstance(description, dict):
            return 0.0

        value = description.get("seconds")
        if value is None and isinstance(description.get("description"), dict):
            value = description["description"].get("seconds")

        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            self.node.get_logger().warn(
                f'Invalid wait action seconds for [{self.name}]: {value}'
            )
            return 0.0

    def _action_context(self, category: str, description) -> dict:
        action_description = description
        if isinstance(description, dict) and isinstance(
            description.get("description"),
            dict,
        ):
            action_description = description["description"]

        context = {
            "activity_type": "action",
            "action_category": str(category),
        }
        if isinstance(action_description, dict):
            for key in ("mission_id", "table", "seconds"):
                if key in action_description:
                    context[key] = action_description[key]
        return context

    def _publish_task_event(self, event: str, context: dict | None = None) -> None:
        if self.task_event_pub is None:
            return

        payload = {
            "event": event,
            "fleet_name": self.fleet_name,
            "robot_name": self.name,
            "stamp": self.node.get_clock().now().nanoseconds,
        }
        if context:
            payload.update(context)

        msg = String()
        msg.data = json.dumps(payload, sort_keys=True)
        self.task_event_pub.publish(msg)
        self.node.get_logger().info(f'published task event {msg.data}')

    def _destination_name(self, destination) -> str:
        name = getattr(destination, "name", "")
        if callable(name):
            name = name()
        return str(name or "")

    @staticmethod
    def _normalize_yaw(yaw: float) -> float:
        return math.atan2(math.sin(yaw), math.cos(yaw))

    def _cancel_action_timer(self, execution):
        timer = self.action_timers.pop(id(execution), None)
        if timer is None:
            return

        timer.cancel()
        self.node.destroy_timer(timer)

    def _finish_action_after_delay(
        self,
        execution,
        seconds: float,
        context: dict | None = None,
    ):
        timer_key = id(execution)
        timer_ref = {}

        def finish_action():
            timer_ref["timer"].cancel()
            self.node.destroy_timer(timer_ref["timer"])
            if self.action_timers.pop(timer_key, None) is None:
                return
            self._publish_task_event("completed", context)
            execution.finished()
            if self.execution is execution:
                self.execution = None
                self.execution_context = None

        timer = self.node.create_timer(seconds, finish_action)
        timer_ref["timer"] = timer
        self.action_timers[timer_key] = timer


def _register_performable_actions(fleet_handle, node):
    more = fleet_handle.more()
    if more is None:
        # TODO: Decide how startup should fail when the underlying fleet handle is unavailable.
        return

    consider_all = rmf_adapter.consider_all()
    more.consider_composed_requests(consider_all)
    more.add_performable_action("wait_at_table", consider_all)
    more.add_performable_action("wait_at_warehouse", consider_all)
    more.add_performable_action("follow", consider_all)
    node.get_logger().info(
        'Registered performable actions '
        '[wait_at_table, wait_at_warehouse, follow] for compose tasks'
    )


# Parallel processing solution derived from
# https://stackoverflow.com/a/59385935
def parallel(f):
    def run_in_parallel(*args, **kwargs):
        return asyncio.get_event_loop().run_in_executor(
            None, f, *args, **kwargs
        )

    return run_in_parallel


@parallel
def update_robot(robot: RobotAdapter):
    data = robot.api.get_data(robot.name)
    if data is None:
        return

    state = rmf_easy.RobotState(
        data.map,
        data.position,
        data.battery_soc
    )

    if robot.update_handle is None:
        robot.update_handle = robot.fleet_handle.add_robot(
            robot.name,
            state,
            robot.configuration,
            robot.make_callbacks()
        )
        return

    robot.update(state)


if __name__ == '__main__':
    main(sys.argv)
