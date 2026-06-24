
import math
from PyQt5.QtWidgets import QWidget, QSizePolicy
from PyQt5.QtGui import (
    QPainter, QPixmap, QImage, QColor, QPen, QBrush, QFont, QTransform
)
from PyQt5.QtCore import Qt, QPointF, QRectF


# 로봇별 색상 팔레트
_ROBOT_COLORS = [
    QColor("#e74c3c"),   # 빨강
    QColor("#2ecc71"),   # 초록
    QColor("#3498db"),   # 파랑
    QColor("#f39c12"),   # 주황
]


class MapWidget(QWidget):

    def __init__(self, map_image_path: str, map_yaml: dict,
             robot_names: list, hd_scale: int = 1, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(100, 100)

        # ── 맵 원본 픽스맵 (90도 시계 방향 회전) ────────────
        _raw = QPixmap(map_image_path)
        _transform = QTransform().rotate(90)
        self._orig_pixmap = _raw.transformed(_transform, Qt.SmoothTransformation)
        self._map_w = self._orig_pixmap.width()   # 회전 후 가로 (원본 세로)
        self._map_h = self._orig_pixmap.height()  # 회전 후 세로 (원본 가로)

        # ── YAML 파라미터 ────────────────────────────────────
        self._hd_scale = hd_scale
        self._resolution = float(map_yaml.get("resolution", 0.05)) / self._hd_scale
        origin = map_yaml.get("origin", [0.0, 0.0, 0.0])
        self._origin_x = float(origin[0])
        self._origin_y = float(origin[1])

        # ── 로봇 pose 저장소 ─────────────────────────────────
        # { robot_name: (world_x, world_y, yaw_rad) | None }
        self._poses: dict = {name: None for name in robot_names}

        # 이름 → 색상 매핑
        self._colors: dict = {}
        for i, name in enumerate(robot_names):
            self._colors[name] = _ROBOT_COLORS[i % len(_ROBOT_COLORS)]

    # ── 외부에서 호출 ─────────────────────────────────────────

    def update_pose(self, robot_name: str,
                    world_x: float, world_y: float, yaw: float):
        """RobotPoseSubscriber 가 수신한 pose 를 갱신하고 repaint."""
        if robot_name in self._poses:
            self._poses[robot_name] = (world_x, world_y, yaw)
            self.update()   # paintEvent 트리거

    def clear_pose(self, robot_name: str):
        """로봇이 오프라인이 됐을 때 표시 제거."""
        if robot_name in self._poses:
            self._poses[robot_name] = None
            self.update()

    # ── 좌표 변환 ──────────────────────────────────────────────

    def _world_to_pixel(self, wx: float, wy: float):
        orig_map_h = self._map_w   # 회전 후 map_w == 원본 map_h

        raw_px = (wx - self._origin_x) / self._resolution        # ← 수정
        raw_py = orig_map_h - (wy - self._origin_y) / self._resolution

        # 시계방향 90도 변환
        px = orig_map_h - raw_py
        py = raw_px
        return px, py

    def _scale_factors(self):
        """현재 위젯 크기 기준 map 스케일 및 오프셋 계산 (letterbox)."""
        if self._map_w == 0 or self._map_h == 0:
            return 1.0, 0.0, 0.0

        w_ratio = self.width()  / self._map_w
        h_ratio = self.height() / self._map_h
        scale   = min(w_ratio, h_ratio)

        draw_w  = self._map_w * scale
        draw_h  = self._map_h * scale
        offset_x = (self.width()  - draw_w) / 2
        offset_y = (self.height() - draw_h) / 2
        return scale, offset_x, offset_y

    def _pixel_to_widget(self, px: float, py: float):
        """map 픽셀 → 위젯 화면 좌표."""
        scale, ox, oy = self._scale_factors()
        return px * scale + ox, py * scale + oy

    # ── 렌더링 ─────────────────────────────────────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)


        # 1) 배경 맵 그리기 (letterbox)
        scale, ox, oy = self._scale_factors()
        draw_w = int(self._map_w * scale)
        draw_h = int(self._map_h * scale)
        painter.drawPixmap(
            int(ox), int(oy), draw_w, draw_h,
            self._orig_pixmap
        )

        # 2) 각 로봇 오버레이
        for name, pose in self._poses.items():
            if pose is None:
                continue
            wx, wy, yaw = pose
            px, py = self._world_to_pixel(wx, wy)
            sx, sy = self._pixel_to_widget(px, py)
            self._draw_robot(painter, sx, sy, yaw, name, self._colors[name])

        painter.end()

    def _draw_robot(self, painter: QPainter,
                    sx: float, sy: float, yaw: float,
                    name: str, color: QColor):
        """원 + 방향선 + 이름 라벨."""
        R = 20
        L = 14 # 방향선 길이 (px)

        # 원
        painter.setBrush(QBrush(color))
        painter.setPen(QPen(Qt.white, 1.5))
        painter.drawEllipse(QRectF(sx - R, sy - R, R * 2, R * 2))
        #painter.drawRect(QRectF(sx - size/2, sy - size/2, size, size))

        # 방향 화살표
        # 시계방향 90도 회전 시 yaw도 -90도 보정
        rotated_yaw = yaw - math.pi / 2
        dx =  math.cos(rotated_yaw) * L
        dy = -math.sin(rotated_yaw) * L
        painter.setPen(QPen(Qt.white, 2, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(
            int(sx), int(sy),
            int(sx + dx), int(sy + dy)
        )

        # 이름 라벨
        painter.setPen(QPen(color.darker(130)))
        font = QFont("Arial", 8, QFont.Bold)
        painter.setFont(font)
        painter.drawText(
            QRectF(sx - 40, sy + R + 2, 80, 14),
            Qt.AlignHCenter | Qt.AlignTop,
            name
        )