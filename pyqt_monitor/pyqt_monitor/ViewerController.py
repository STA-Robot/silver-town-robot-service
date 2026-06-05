# pyqt_monitor/pyqt_monitor/ViewerController.py
import sys
import os
import cv2
import yaml
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui  import QImage, QPixmap
from visualizer import draw as draw_visualizer

# ── 프로젝트 루트 경로 ────────────────────────────────────────
_root = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
for _p in [
    os.path.join(_root, "ai_ws", "ai_ws"),
    os.path.join(_root, "videoReceiv"),
]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ai_ws.ai_ws.AIController import get_active_robot, get_latest_debug
from videoReceiv.videoRecevier import get_frame

class ViewerController:
    """
    QTlayout.py 에서 view_btn 클릭 시 on_view(ip) 를 직접 호출.
    ViewerController는 IP만 받아서 프레임 조회 + 표시만 담당.
    """
    def __init__(self, ui):
        self.ui        = ui
        self.viewed_ip = None

        # 33ms 타이머 — 프레임 갱신
        self.timer = QTimer()
        self.timer.timeout.connect(self._update)
        self.timer.start(33)

    def on_view(self, robot_ip: str):
        """
        QTlayout에서 view_btn 클릭 시 직접 호출.
        robot_ip만 받아서 viewed_ip 업데이트.
        """
        self.viewed_ip = robot_ip

        # 뷰어 타이틀 갱신
        title = self.ui.viewer_layout.itemAt(0).widget()
        if title:
            title.setText(f"  VIEWER — ({robot_ip})")

    def _update(self):
        if self.viewed_ip is None:
            return

        active_ip = get_active_robot()
        is_ai     = (self.viewed_ip == active_ip)

        frame = get_frame(self.viewed_ip)
        if frame is None:
            self.ui.viewer.setText("NO SIGNAL")
            return

        if is_ai:
            dbg = get_latest_debug()

            if dbg is not None:
                frame = draw_visualizer(
                    frame.copy(),
                    dbg.state,
                    dbg.gesture,
                    dbg.track
                )

        self._show_frame(frame)

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
