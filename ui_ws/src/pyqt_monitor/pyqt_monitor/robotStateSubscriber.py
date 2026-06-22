import os
import time
import yaml
from ament_index_python.packages import get_package_share_directory
from typing import Callable

from rclpy.node import Node

from pinky_drive_msgs.msg import DriveState
from PyQt5.QtCore import QObject, pyqtSignal


class RobotStateNode(Node):
   #ROS2 통신 전담 — /{robot_name}/state 구독 (DriveState, pose 포함)

    TIMEOUT_SEC = 3.0  # 이 시간 동안 메시지가 없으면 오프라인 처리

    def __init__(self, robot_configs: list, on_state_cb: Callable, on_offline_cb: Callable):
        super().__init__('robot_state_subscriber_node')

        self._on_state_cb = on_state_cb
        self._on_offline_cb = on_offline_cb
        self._last_seen = {robot["robot_name"]: 0.0 for robot in robot_configs}

        for robot in robot_configs:
            robot_name = robot["robot_name"]
            topic = f'/{robot_name}/state'

            self.create_subscription(
                DriveState,
                topic,
                self._on_state,
                10
            )
            self.get_logger().info(f"[RobotState] 구독: {topic}")

        self.create_timer(1.0, self._check_timeout)

    def _on_state(self, msg: DriveState):
        self._last_seen[msg.robot_name] = time.time()

        x, y, yaw = 0.0, 0.0, 0.0
        if len(msg.pose) >= 3:
            x, y, yaw = msg.pose[0], msg.pose[1], msg.pose[2]

        self._on_state_cb(
            robot_name=msg.robot_name,
            state=msg.state,
            battery=msg.battery_soc,
            available=msg.available,
            emergency=msg.emergency,
            x=x,
            y=y,
            yaw=yaw,
        )
        

    def _check_timeout(self):
        now = time.time()
        for name, t in self._last_seen.items():
            if t == 0.0:
                continue
            if now - t > self.TIMEOUT_SEC:
                self._on_offline_cb(name)
                self._last_seen[name] = 0.0


class RobotStateSubscriber(QObject):
    #PyQt 시그널 전담
    # robot_name, state, battery(0~1), available, emergency
    robot_state_signal = pyqtSignal(str, str, float, bool, bool)
    # robot_name, x, y, yaw
    robot_pose_signal = pyqtSignal(str, float, float, float)
    # robot_name (통신 끊김 → 지도에서 제거)
    robot_offline_signal = pyqtSignal(str)

    def __init__(self, ui ,ws_bridge=None):
        QObject.__init__(self)
        self.ui = ui
        self.ws_bridge = ws_bridge
        config_path = os.path.join(
            get_package_share_directory('visionDataHub'),
            'config', 'video_config.yaml'
        )
        with open(config_path) as f:
            cfg = yaml.safe_load(f)

        self.robot_configs = cfg["robots"]

        self.ros = RobotStateNode(
            robot_configs=self.robot_configs,
            on_state_cb=self._on_state_cb,
            on_offline_cb=self._on_offline_cb,
        )

        self.robot_state_signal.connect(self.ui._on_robot_state)
        self.robot_pose_signal.connect(self.ui.map_widget.update_pose)
        self.robot_offline_signal.connect(self.ui.map_widget.clear_pose)

    def _on_state_cb(self, robot_name, state, battery, available, emergency, x, y, yaw):
        self.robot_state_signal.emit(
            robot_name, state, float(battery), available, emergency
        )
        self.robot_pose_signal.emit(robot_name, float(x), float(y), float(yaw))
        if self.ws_bridge:
            self.ws_bridge.send_threadsafe({
                "robotId": robot_name,
                "state":      state,
                "battery":    float(battery),
                "px": x, "py": y, "pz": 0.0,
                "yaw": yaw,
            })

    def _on_offline_cb(self, robot_name):
        self.robot_offline_signal.emit(robot_name)

    def get_ros_node(self) -> RobotStateNode:
        return self.ros

    def destroy(self):
        self.ros.destroy_node()