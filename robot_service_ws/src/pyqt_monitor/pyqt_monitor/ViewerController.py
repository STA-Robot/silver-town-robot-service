import json
import threading
from typing import Optional

import cv2
import numpy as np

from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String

from PyQt5.QtCore import QObject, pyqtSignal, Qt
from PyQt5.QtGui  import QImage, QPixmap


class ViewerRosNode(Node):
    """ROS2 통신 전담 — QObject 아님"""

    def __init__(self, on_frame_cb, on_ai_target_cb):
        super().__init__('viewer_controller_node')

        self._on_frame_cb     = on_frame_cb
        self._on_ai_target_cb = on_ai_target_cb

        self.create_subscription(
            String, '/ai_target', self._on_ai_target, 10
        )
        self._viewer_req_pub = self.create_publisher(
            String, '/viewer_request', 10
        )

    def _on_ai_target(self, msg):
        self._on_ai_target_cb(msg)

    def subscribe_image(self, topic):
        return self.create_subscription(
            CompressedImage, topic, self._on_frame_cb, 10
        )

    def destroy_sub(self, sub):
        if sub:
            self.destroy_subscription(sub)

    def send_viewer_request(self, robot_ip, action):
        msg      = String()
        msg.data = f"{robot_ip}:{action}"
        self._viewer_req_pub.publish(msg)


class ViewerController(QObject):
    """PyQt UI 전담 — Node 아님"""

    frame_ready = pyqtSignal(object)

    def __init__(self, ui):
        QObject.__init__(self)

        self.ui   = ui
        self.lock = threading.Lock()

        self._viewed_ip:   Optional[str]    = None
        self._ai_robot_ip: Optional[str]    = None
        self._image_sub:   Optional[object] = None

        # ROS 노드 생성
        self.ros = ViewerRosNode(
            on_frame_cb=self._on_frame,
            on_ai_target_cb=self._on_ai_target
        )

        self.frame_ready.connect(self._show_frame)

    def get_ros_node(self):
        return self.ros

    def _on_ai_target(self, msg):
        try:
            data     = json.loads(msg.data)
            robot_ip = data["ip"]
            active   = data.get("active", True)

            with self.lock:
                old_ai            = self._ai_robot_ip
                self._ai_robot_ip = robot_ip if active else None
                viewed            = self._viewed_ip

            if viewed in (robot_ip, old_ai):
                self._resubscribe(viewed)
        except Exception as e:
            self.ros.get_logger().warn(f"[ai_target 오류] {e}")

    def on_view(self, robot_ip):
        with self.lock:
            prev_ip = self._viewed_ip

        if prev_ip and prev_ip != robot_ip:
            self.ros.send_viewer_request(prev_ip, "off")

        with self.lock:
            self._viewed_ip = robot_ip

        self.ros.send_viewer_request(robot_ip, "on")

        title_widget = self.ui.viewer_layout.itemAt(0).widget()
        if title_widget:
            title_widget.setText(f"  VIEWER — ({robot_ip})")

        self._resubscribe(robot_ip)

    def _resubscribe(self, robot_ip):
        if robot_ip is None:
            return

        with self.lock:
            if self._image_sub:
                self.ros.destroy_sub(self._image_sub)
                self._image_sub = None
            ai_robot = self._ai_robot_ip

        topic = '/ai/image_result' if robot_ip == ai_robot \
            else f'/robot_{robot_ip.replace(".", "_")}/image/compressed'

        sub = self.ros.subscribe_image(topic)
        with self.lock:
            self._image_sub = sub

        self.ros.get_logger().info(f"[Viewer] 구독: {topic}")

    def _on_frame(self, ros_msg):
        frame = cv2.imdecode(
            np.frombuffer(ros_msg.data, np.uint8),
            cv2.IMREAD_COLOR
        )
        if frame is None:
            return
        self.frame_ready.emit(frame)

    def _show_frame(self, frame):
        rgb    = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w   = rgb.shape[:2]
        qimg   = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg).scaled(
            self.ui.viewer.width(),
            self.ui.viewer.height(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.ui.viewer.setPixmap(pixmap)