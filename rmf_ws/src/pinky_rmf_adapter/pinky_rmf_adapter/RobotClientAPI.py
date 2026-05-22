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


import time

from pinky_drive_msgs.msg import DriveCommand, DriveState


'''
    The RobotAPI class is a wrapper for API calls to the robot. Here users
    are expected to fill up the implementations of functions which will be used
    by the RobotCommandHandle. For example, if your robot has a REST API, you
    will need to make http request calls to the appropriate endpoints within
    these functions.
'''


class RobotAPI:
    # The constructor below accepts parameters typically required to submit
    # http requests. Users should modify the constructor as per the
    # requirements of their robot's API
    def __init__(self, config_yaml, node=None):
        self.prefix = config_yaml.get('prefix', '')
        self.user = config_yaml.get('user', '')
        self.password = config_yaml.get('password', '')
        self.timeout = 5.0
        self.debug = False
        self.node = node
        self.robots = config_yaml.get('robots', {})
        self.command_pubs = {}
        self.state_subs = {}
        self.states = {}
        self.active_command_ids = {}

        if self.node is not None:
            self._create_ros_interfaces()

    def _create_ros_interfaces(self):
        qos_depth = 10
        for robot_name, robot_config in self.robots.items():
            command_topic = robot_config['command_topic']
            state_topic = robot_config['state_topic']
            self.command_pubs[robot_name] = self.node.create_publisher(
                DriveCommand,
                command_topic,
                qos_depth,
            )
            self.state_subs[robot_name] = self.node.create_subscription(
                DriveState,
                state_topic,
                lambda msg, name=robot_name: self._on_state(name, msg),
                qos_depth,
            )

    def _on_state(self, robot_name: str, msg: DriveState):
        self.states[robot_name] = msg

    def _next_command_id(self, robot_name: str, command_type: str) -> str:
        return f"rmf-{robot_name}-{command_type}-{time.time_ns()}"

    def _publish_command(
        self,
        robot_name: str,
        command_type: str,
        pose=None,
        map_name: str = "",
        speed_limit=0.0,
        target_name: str = "",
    ):
        if self.node is None or robot_name not in self.command_pubs:
            # TODO: Decide how to report missing robot topic configuration.
            return False

        command = DriveCommand()
        command.header.stamp = self.node.get_clock().now().to_msg()
        command.robot_name = robot_name
        command.command_id = self._next_command_id(robot_name, command_type)
        command.command_type = command_type
        command.map_name = map_name
        if pose is not None:
            command.x = float(pose[0])
            command.y = float(pose[1])
            command.yaw = float(pose[2])
        command.speed_limit = float(speed_limit or 0.0)
        command.target_name = target_name
        command.payload_json = ""

        self.active_command_ids[robot_name] = command.command_id
        self.command_pubs[robot_name].publish(command)
        return True

    def check_connection(self):
        ''' Return True if connection to the robot API server is successful '''
        return bool(self.command_pubs)

    def localize(
        self,
        robot_name: str,
        pose,
        map_name: str,
    ):
        ''' Request the robot to localize on target map. This 
            function should return True if the robot has accepted the 
            request, else False '''
        # TODO: Add a localization command or service if Pinky exposes one.
        return False
    
    def navigate(
        self,
        robot_name: str,
        pose,
        map_name: str,
        speed_limit=0.0
    ):
        ''' Request the robot to navigate to pose:[x,y,theta] where x, y and
            and theta are in the robot's coordinate convention. This function
            should return True if the robot has accepted the request,
            else False '''
        return self._publish_command(
            robot_name=robot_name,
            command_type="navigate",
            pose=pose,
            map_name=map_name,
            speed_limit=speed_limit,
        )

    def start_activity(
        self,
        robot_name: str,
        activity: str,
        label: str
    ):
        ''' Request the robot to begin a process. This is specific to the robot
        and the use case. For example, load/unload a cart for Deliverybot
        or begin cleaning a zone for a cleaning robot.
        Return True if process has started/is queued successfully, else
        return False '''
        # TODO: Wire robot-specific non-navigation activities when needed.
        return False

    def stop(self, robot_name: str):
        ''' Command the robot to stop.
            Return True if robot has successfully stopped. Else False. '''
        return self._publish_command(
            robot_name=robot_name,
            command_type="stop",
        )

    def position(self, robot_name: str):
        ''' Return [x, y, theta] expressed in the robot's coordinate frame or
        None if any errors are encountered '''
        state = self.states.get(robot_name)
        if state is None:
            return None
        return list(state.pose)

    def battery_soc(self, robot_name: str):
        ''' Return the state of charge of the robot as a value between 0.0
        and 1.0. Else return None if any errors are encountered. '''
        state = self.states.get(robot_name)
        if state is None:
            return None
        return float(state.battery_soc)

    def map(self, robot_name: str):
        ''' Return the name of the map that the robot is currently on or
        None if any errors are encountered. '''
        state = self.states.get(robot_name)
        if state is None:
            return None
        return state.map_name

    def is_command_completed(self, robot_name: str | None = None):
        ''' Return True if the robot has completed its last command, else
        return False. '''
        if robot_name is None:
            # TODO: Remove this compatibility path once all callers pass a robot.
            return False

        command_id = self.active_command_ids.get(robot_name)
        state = self.states.get(robot_name)
        if command_id is None or state is None:
            return False

        if state.last_command_id != command_id:
            return False

        if state.last_command_status in {"succeeded", "canceled"}:
            self.active_command_ids.pop(robot_name, None)
            return True

        # TODO: Decide whether failed/rejected should finish, replan, or block.
        return False

    def get_data(self, robot_name: str):
        ''' Returns a RobotUpdateData for one robot if a name is given. Otherwise
        return a list of RobotUpdateData for all robots. '''
        map = self.map(robot_name)
        position = self.position(robot_name)
        battery_soc = self.battery_soc(robot_name)
        if not (map is None or position is None or battery_soc is None):
            return RobotUpdateData(robot_name, map, position, battery_soc)
        return None


class RobotUpdateData:
    ''' Update data for a single robot. '''
    def __init__(self,
                 robot_name: str,
                 map: str,
                 position: list[float],
                 battery_soc: float,
                 requires_replan: bool | None = None):
        self.robot_name = robot_name
        self.position = position
        self.map = map
        self.battery_soc = battery_soc
        self.requires_replan = requires_replan
