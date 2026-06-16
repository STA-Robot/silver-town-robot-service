import time
import json
import threading
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from PyQt5.QtCore import QObject, pyqtSignal

class PoseNode(Node):
    def __init__(self, robot_names, callback):
        super().__init__("robot_state_subscriber")
        self._cb = callback
        self._last_seen = {name: 0.0 for name in robot_names}

        for name in robot_names:
            topic = f"/{name}/state"
            self.create_subscription(
                String,
                topic,
                lambda msg, rn=name: self._on_msg(rn, msg),
                10
            )

        # 1초마다 체크
        self.create_timer(1.0, self._check_timeout)

    def _on_msg(self, robot_name, msg):
        try:
            data = json.loads(msg.data)

            pose = data.get("pose", None)
            if pose and len(pose) >= 3:
                x, y, yaw = pose
                self._last_seen[robot_name] = time.time()
                self._cb(robot_name, x, y, yaw)

        except Exception as e:
            self.get_logger().error(f"state parse error: {e}")

    def _check_timeout(self):
        now = time.time()
        TIMEOUT = 3.0  # 3초 동안 안 오면 제거

        for name, t in self._last_seen.items():
            if t == 0:
                continue
            if now - t > TIMEOUT:
                self._cb(name, None, None, None)
                self._last_seen[name] = 0