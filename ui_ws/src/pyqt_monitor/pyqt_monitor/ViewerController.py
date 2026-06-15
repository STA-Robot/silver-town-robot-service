import json
import threading
import time
from typing import Optional

import cv2
import numpy as np

from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String

from PyQt5.QtCore import QObject, pyqtSignal, Qt
from PyQt5.QtGui  import QImage, QPixmap

from .visualizer import draw
from ai_controller.aicore.gestureRecognizer import GestureDebugInfo
from ai_controller.aicore.targetTracker import TrackDebugInfo


class ViewerRosNode(Node):
    """ROS2 통신 전담 — image/compressed + robot_status만"""

    def __init__(self, on_frame_cb, on_robot_status_cb):
        super().__init__('viewer_controller_node')

        self._image_subs: dict[str, object] = {}
        self._on_frame_cb        = on_frame_cb
        self._on_robot_status_cb = on_robot_status_cb

        # /ai_target 구독 제거
        self.create_subscription(String, '/robot_status', self._on_robot_status, 10)
        self._viewer_req_pub = self.create_publisher(String, '/viewer_request', 10)

    def _on_robot_status(self, msg: String):
        self._on_robot_status_cb(msg)

    def subscribe_image(self, robot_name: str):
        # 버그수정: topic을 인자로 받지 않고 robot_name으로 내부 생성
        topic = f'/{robot_name}/image/compressed'
        sub = self.create_subscription(
            CompressedImage, topic, self._on_frame_cb, 10
        )
        self.get_logger().info(f"[Viewer] 영상 구독: {topic}")
        return sub

    def destroy_sub(self, sub):
        if sub:
            self.destroy_subscription(sub)

    def send_viewer_request(self, robot_name: str, action: str):
        msg = String()
        msg.data = f"{robot_name}:{action}"
        self._viewer_req_pub.publish(msg)


class ViewerController(QObject):
    """PyQt UI 전담"""

    frame_ready         = pyqtSignal(object)
    clear_viewer        = pyqtSignal()
    robot_status_signal = pyqtSignal(str, str, bool)

    def __init__(self, ui):
        QObject.__init__(self)

        self.ui   = ui
        self.lock = threading.Lock()

        self._viewed_name: Optional[str]    = None
        self._image_sub:   Optional[object] = None

        # ai_debug 캐시: robot_name → 최신 debug dict
        # 데이터 있으면 AI 추론 중, 없으면 raw 영상
        self._latest_debug: dict[str, tuple[dict, float]] = {}
        self.ros = ViewerRosNode(
            on_frame_cb=self._on_frame,
            on_robot_status_cb=self._on_robot_status,
        )

        # /ai_target 대신 ai_debug 직접 구독 (ViewerController 담당)
        self._subscribe_ai_debug('pinky1')
        self._subscribe_ai_debug('pinky2')

        self.frame_ready.connect(self._show_frame)
        self.clear_viewer.connect(self._show_empty)
        self.robot_status_signal.connect(self.ui._on_robot_status)

    def get_ros_node(self):
        return self.ros

    # ── ai_debug 구독 ─────────────────────────────────────────
    # ViewerController에서 직접 구독 (같은 패키지, 통신 불필요)

    def _subscribe_ai_debug(self, robot_name: str):
        def cb(msg: String):
            try:
                data = json.loads(msg.data)
                with self.lock:
                    self._latest_debug[robot_name] = (data, time.time())  # 시간 같이 저장
            except Exception as e:
                self.ros.get_logger().warn(f"[ai_debug 파싱 오류] {e}")

        # ViewerRosNode를 통해 create_subscription (ROS2 노드가 필요)
        self.ros.create_subscription(
            String,
            f'/{robot_name}/ai_debug',
            cb,
            10
        )
        self.ros.get_logger().info(f"[Viewer] ai_debug 구독: /{robot_name}/ai_debug")

    # ── /robot_status 콜백 ────────────────────────────────────

    def _on_robot_status(self, msg: String):
        try:
            data = json.loads(msg.data)
            self.robot_status_signal.emit(
                data["name"], data["ip"], data["online"]
            )
        except Exception as e:
            self.ros.get_logger().warn(f"[robot_status 오류] {e}")

    # ── view 버튼 클릭 ────────────────────────────────────────

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
        self._resubscribe(robot_name)

    def _resubscribe(self, robot_name: str):
        """항상 /{robot_name}/image/compressed 구독 — 토픽 전환 없음"""
        if robot_name is None:
            return

        with self.lock:
            if self._image_sub:
                self.ros.destroy_sub(self._image_sub)
                self._image_sub = None

        # 항상 같은 영상 토픽, 오버레이는 _on_frame에서 판단
        sub = self.ros.subscribe_image(robot_name)
        with self.lock:
            self._image_sub = sub

    # ── 프레임 수신 ───────────────────────────────────────────

    def _on_frame(self, ros_msg: CompressedImage):
        frame = cv2.imdecode(
            np.frombuffer(ros_msg.data, np.uint8), cv2.IMREAD_COLOR
        )
        if frame is None:
            return

        with self.lock:
            viewed = self._viewed_name
            cache  = self._latest_debug.get(viewed)  # (data, timestamp) or None

        debug = None
        if cache is not None:
            data, ts = cache
            # 0.5초 이상 ai_debug 안 오면 추론 종료로 판단
            if time.time() - ts < 0.5:
                debug = data #debug를 none으로 해야되는거 아닌가?

        if debug is not None:
            frame = self._apply_debug_overlay(frame, debug)

        self.frame_ready.emit(frame)

    def _apply_debug_overlay(self, frame, data: dict):
        """JSON → GestureDebugInfo / TrackDebugInfo 복원 → visualizer.draw()"""
        g = data.get("gesture", {})
        t = data.get("track",   {})

        g_dbg = GestureDebugInfo(
            label=g.get("label"),
            conf= g.get("conf",  0.0),
            box=  tuple(g["box"]) if g.get("box") else None,
        )

        t_dbg = TrackDebugInfo(
            found=      t.get("found",       False),
            is_lost=    t.get("is_lost",     False),
            lost_frames=t.get("lost_frames", 0),
            box=        tuple(t["box"])       if t.get("box")       else None,
            torso_box=  tuple(t["torso_box"]) if t.get("torso_box") else None,
            cx=         t.get("cx",       0),
            cy=         t.get("cy",       0),
            h=          t.get("h",        0),
            h_ratio=    t.get("h_ratio",  0.0),
            track_id=   t.get("track_id", -1),
            sim=        t.get("sim",      0.0),
        )

        return draw(frame, data.get("state", "STOP"), g_dbg, t_dbg)

    # ── Qt 슬롯 ───────────────────────────────────────────────

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
        self.ui.viewer.clear()
        self.ui.viewer.setText("CAMERA VIEW")