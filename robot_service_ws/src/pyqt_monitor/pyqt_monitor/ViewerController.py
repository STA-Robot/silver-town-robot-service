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
   #ROS2 통신 전담
    def __init__(self, on_frame_cb, on_ai_target_cb, on_robot_status_cb):
        super().__init__('viewer_controller_node')

        self._on_frame_cb     = on_frame_cb
        self._on_ai_target_cb = on_ai_target_cb
        self._on_robot_status_cb   = on_robot_status_cb

        self.create_subscription(String, '/ai_target', self._on_ai_target, 10)
        self.create_subscription(String, '/robot_status', self._on_robot_status, 10)

        self._viewer_req_pub = self.create_publisher(String, '/viewer_request', 10)

    def _on_ai_target(self, msg):
        self._on_ai_target_cb(msg)

    def _on_robot_status(self, msg):
        self._on_robot_status_cb(msg)

    def subscribe_image(self, topic):
        return self.create_subscription(
            CompressedImage, topic, self._on_frame_cb, 10
        )

    def destroy_sub(self, sub):
        if sub:
            self.destroy_subscription(sub)

    def send_viewer_request(self, robot_name, action):
        msg      = String()
        msg.data = f"{robot_name}:{action}"
        self._viewer_req_pub.publish(msg)


class ViewerController(QObject):
    #PyQt UI 전담 
    frame_ready = pyqtSignal(object)
    clear_viewer = pyqtSignal()# 빈 화면으로 초기화
    robot_status_signal  = pyqtSignal(str, str, bool)  # name, ip, online

    def __init__(self, ui):
        QObject.__init__(self)

        self.ui   = ui
        self.lock = threading.Lock()

        self._viewed_name:   Optional[str]    = None
        self._ai_robot_name: Optional[str]    = None
        self._image_sub:   Optional[object] = None

        # ROS 노드 생성
        self.ros = ViewerRosNode(
            on_frame_cb=self._on_frame,
            on_ai_target_cb=self._on_ai_target,
            on_robot_status_cb=self._on_robot_status
        )

        self.frame_ready.connect(self._show_frame)
        self.clear_viewer.connect(self._show_empty)
        self.robot_status_signal.connect(self.ui._on_robot_status)

    def get_ros_node(self):
        return self.ros

    def _on_ai_target(self, msg):
        try:
            data     = json.loads(msg.data)
            robot_name = data["robot_name"]
            active   = data.get("active")

            with self.lock:
                old_ai            = self._ai_robot_name
                self._ai_robot_name = robot_name if active else None
                viewed            = self._viewed_name

            if viewed in (robot_name, old_ai):
                self._resubscribe(viewed)
        except Exception as e:
            self.ros.get_logger().warn(f"[ai_target 오류] {e}")

    def _on_robot_status(self, msg: String):
        try:
            data = json.loads(msg.data)
            self.robot_status_signal.emit(
                data["name"],
                data["ip"],
                data["online"]
            )
        except Exception as e:
            self.ros.get_logger().warn(f"[robot_status 오류] {e}")

    def on_view(self, robot_name):
        with self.lock:
            prev_name = self._viewed_name

        if prev_name and prev_name != robot_name:
            self.ros.send_viewer_request(prev_name, "off")

        with self.lock:
            self._viewed_name = robot_name

        self.ros.send_viewer_request(robot_name, "on")

        title_widget = self.ui.viewer_layout.itemAt(0).widget()
        if title_widget:
            title_widget.setText(f"  VIEWER — ({robot_name})")

        self.clear_viewer.emit()

        self._resubscribe(robot_name)

    def _resubscribe(self, robot_name):
        if robot_name is None:
            return

        with self.lock:
            if self._image_sub:
                self.ros.destroy_sub(self._image_sub)
                self._image_sub = None
            ai_robot = self._ai_robot_name

        topic = '/ai/image_result' if robot_name == ai_robot \
            else f'/{robot_name}/image/compressed'

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

    def _show_empty(self):
        """뷰어를 검은 화면으로 초기화 (잔상 제거)"""
        self.ui.viewer.clear()
        self.ui.viewer.setText("CAMERA VIEW")