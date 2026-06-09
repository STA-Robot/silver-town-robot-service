
import json
import threading
from typing import Optional

import cv2
import numpy as np

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String

from PyQt5.QtCore import QObject, pyqtSignal, Qt
from PyQt5.QtGui  import QImage, QPixmap


class ViewerController(QObject, Node):

    frame_ready = pyqtSignal(object)  # np.ndarray → 메인스레드 UI 갱신

    def __init__(self, ui):
        QObject.__init__(self)
        Node.__init__(self, 'viewer_controller_node')

        self.ui   = ui
        self.lock = threading.Lock()

        self._viewed_ip:   Optional[str]    = None
        self._ai_robot_ip: Optional[str]    = None
        self._image_sub:   Optional[object] = None

        # AI 추론 대상 모니터링
        self.create_subscription(
            String, '/ai_target', self._on_ai_target, 10
        )

        # VideoReceiver 활성화 요청 발행
        self._viewer_req_pub = self.create_publisher(
            String, '/viewer_request', 10
        )

        self.frame_ready.connect(self._show_frame)
        self.get_logger().info("[ViewerController] 시작")

    # ── AI 추론 대상 수신 ──────────────────────────────────────

    def _on_ai_target(self, msg: String):
        try:
            data     = json.loads(msg.data)
            robot_ip = data["ip"]
            active   = data.get("active", True)

            with self.lock:
                old_ai            = self._ai_robot_ip
                self._ai_robot_ip = robot_ip if active else None
                viewed            = self._viewed_ip

            # 보고 있는 로봇의 AI 상태가 바뀌면 구독 재설정
            if viewed in (robot_ip, old_ai):
                self._resubscribe(viewed)

        except Exception as e:
            self.get_logger().warn(f"[ai_target 파싱 오류] {e}")

    # ── GUI 보기버튼 클릭 ──────────────────────────────────────

    def on_view(self, robot_ip: str):
        with self.lock:
            prev_ip = self._viewed_ip

        if prev_ip and prev_ip != robot_ip:
            self._send_viewer_request(prev_ip, "off")

        with self.lock:
            self._viewed_ip = robot_ip

        self._send_viewer_request(robot_ip, "on")

        title_widget = self.ui.viewer_layout.itemAt(0).widget()
        if title_widget:
            title_widget.setText(f"  VIEWER — ({robot_ip})")

        self._resubscribe(robot_ip)

    # ── 구독 재설정 ────────────────────────────────────────────

    def _resubscribe(self, robot_ip: Optional[str]):
        if robot_ip is None:
            return

        with self.lock:
            if self._image_sub is not None:
                self.destroy_subscription(self._image_sub)
                self._image_sub = None
            ai_robot = self._ai_robot_ip

        # 추론 중인 로봇이면 AI 결과 구독, 아니면 raw compressed 구독
        if robot_ip == ai_robot:
            topic = '/ai/image_result'
        else:
            topic = f'/robot_{robot_ip.replace(".", "_")}/image/compressed'

        sub = self.create_subscription(
            CompressedImage, topic, self._on_frame, 10
        )
        with self.lock:
            self._image_sub = sub

        self.get_logger().info(f"[Viewer] 구독: {topic}")

    # ── 영상 수신 콜백 ─────────────────────────────────────────

    def _on_frame(self, ros_msg: CompressedImage):
        # CompressedImage → numpy (imdecode 한 번만, bridge 없음)
        frame = cv2.imdecode(
            np.frombuffer(ros_msg.data, np.uint8),
            cv2.IMREAD_COLOR
        )
        if frame is None:
            return
        self.frame_ready.emit(frame)

    # ── PyQt UI 업데이트 (메인스레드) ──────────────────────────

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

    # ── viewer_request 발행 ────────────────────────────────────

    def _send_viewer_request(self, robot_ip: str, action: str):
        msg      = String()
        msg.data = f"{robot_ip}:{action}"
        self._viewer_req_pub.publish(msg)

    def destroy_node(self):
        with self.lock:
            if self._image_sub:
                self.destroy_subscription(self._image_sub)
        super().destroy_node()