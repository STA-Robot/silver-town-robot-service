# pyqt_monitor/pyqt_monitor/ViewerController.py

import cv2
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui  import QImage, QPixmap
from .visualizer import draw as draw_visualizer

from ai_controller.AIController import get_active_robot, get_latest_debug
from common_video.videoRecevier import VideoReceiver 

class ViewerController:

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

        frame = VideoReceiver.get_frame(self.viewed_ip)
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
