
import threading
from typing import Optional
import cv2
import numpy as np

from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from robot_active_msgs.msg import RobotActive

from PyQt5.QtCore import QObject, pyqtSignal, Qt
from PyQt5.QtGui  import QImage, QPixmap

# ViewerRosNode — follow_command 구독 불필요, viewer 토픽만
class ViewerRosNode(Node):
    def __init__(self, on_frame_cb, on_robot_status_cb):
        super().__init__('viewer_controller_node')
        self._on_frame_cb        = on_frame_cb
        self._on_robot_status_cb = on_robot_status_cb
        self._current_sub = None

        self.create_subscription(RobotActive, '/robot_status', self._on_robot_status, 10)
        self._viewer_req_pub = self.create_publisher(RobotActive, '/viewer_request', 10)

    def _on_robot_status(self, msg):
        self._on_robot_status_cb(msg)

    def subscribe_viewer(self, robot_name: str):
        if self._current_sub:
            self.destroy_subscription(self._current_sub)
            self._current_sub = None

        topic = f'/{robot_name}/viewer/compressed'
        self._current_sub = self.create_subscription(
            CompressedImage, topic, self._on_frame_cb, 10
        )
        self.get_logger().info(f"[Viewer] 구독: {topic}")

    def send_viewer_request(self, robot_name: str, action: str):
        msg = RobotActive()
        msg.name = robot_name
        msg.action = action
      
        self._viewer_req_pub.publish(msg)


# ViewerController — _ai_robot, _follow_command 완전 제거
class ViewerController(QObject):

    frame_ready         = pyqtSignal(object)
    clear_viewer        = pyqtSignal()
    robot_status_signal = pyqtSignal(str, str, bool)

    def __init__(self, ui):
        QObject.__init__(self)
        self.ui   = ui
        self.lock = threading.Lock()
        self._viewed_name: Optional[str] = None

        self.ros = ViewerRosNode(
            on_frame_cb=self._on_frame,
            on_robot_status_cb=self._on_robot_status,
        )

        self.frame_ready.connect(self._show_frame)
        self.clear_viewer.connect(self._show_empty)
        self.robot_status_signal.connect(self.ui._on_robot_status)

    def get_ros_node(self):
        return self.ros

    def on_view(self, robot_name: str):
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
        # viewer 토픽 구독 (raw/result 판단은 VideoReceiverNode가)
        self.ros.subscribe_viewer(robot_name)

    def _on_frame(self, ros_msg: CompressedImage):
        frame = cv2.imdecode(
            np.frombuffer(ros_msg.data, np.uint8), cv2.IMREAD_COLOR
        )
        if frame is None:
            return
        self.frame_ready.emit(frame)

    def _on_robot_status(self, msg: RobotActive):
        try:
            self.robot_status_signal.emit(
            msg.name,
            msg.ip,
            msg.online
            )
        except Exception as e:
            print(f"[robot_status 오류] {e}")

    def _show_frame(self, frame):
        print(f"[frame] {frame}")
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
        self.ui.viewer.clear()
        self.ui.viewer.setText("CAMERA VIEW")