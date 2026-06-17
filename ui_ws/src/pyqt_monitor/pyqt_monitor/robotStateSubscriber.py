
import os
import yaml
from ament_index_python.packages import get_package_share_directory
from typing import Callable

from rclpy.node import Node
from std_msgs.msg import Header

from pinky_drive_msgs.msg import DriveState
from PyQt5.QtCore import QObject, pyqtSignal


class RobotStateNode(Node):
    #ROS2 통신 전담 — /{ros_name}/state 구독
    def __init__(self, robot_configs: list, on_state_cb: Callable):
        super().__init__('robot_state_subscriber_node')

        self._on_state_cb = on_state_cb

        for robot in robot_configs:
            robot_name = robot["robot_name"]
            topic = f'/{robot_name}/state'

            sub = self.create_subscription(
                DriveState,
                topic,
                self._on_state,
                10
            )
            self.get_logger().info(f"[RobotState] 구독: {topic}")
       

    def _on_state(self, msg: DriveState):
        self._on_state_cb(
            robot_name=msg.robot_name,
            state=msg.state,
            battery=msg.battery_soc,
            available=msg.available,
            emergency=msg.emergency
        )


class RobotStateSubscriber(QObject):
    #PyQt 시그널 전담
    # robot_name, state, battery(0~1), available, emergency
    robot_state_signal = pyqtSignal(str, str, float, bool, bool)

    def __init__(self, ui):
        QObject.__init__(self)

        self.ui = ui

        # config 로드
        config_path = os.path.join(
            get_package_share_directory('visionDataHub'),
            'config', 'video_config.yaml'
        )
        with open(config_path) as f:
            cfg = yaml.safe_load(f)

        self.robot_configs = cfg["robots"]

        # ROS 노드 생성
        self.ros = RobotStateNode(
            robot_configs=self.robot_configs,
            on_state_cb=self._on_state_cb
        )

        # 시그널 → QTlayout 슬롯 연결
        self.robot_state_signal.connect(self.ui._on_robot_state)

    def _on_state_cb(self, robot_name, state, battery, available, emergency):
        #ROS 스레드 → PyQt 메인스레드로 시그널 전달
        self.robot_state_signal.emit(
            robot_name,
            state,
            float(battery),
            available,
            emergency
        )
 
    def get_ros_node(self) -> RobotStateNode:
        return self.ros

    def destroy(self):
        self.ros.destroy_node()