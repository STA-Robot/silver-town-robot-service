import os
os.environ.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
os.environ["QT_QPA_PLATFORM"] = "xcb"

import sys
from ament_index_python.packages import get_package_share_directory
import yaml
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QGridLayout, QTableWidget, QTableWidgetItem, QFrame, QScrollArea,
    QHeaderView, QSizePolicy
)
from PyQt5.QtCore import Qt

from .ViewerController import ViewerController
from .robotStateSubscriber import RobotStateSubscriber

common_path = get_package_share_directory('common_video')
config_path = os.path.join(common_path, 'config', 'video_config.yaml')


class RobotItem(QWidget):
    def __init__(self, robot_name):
        super().__init__()

        layout = QHBoxLayout()
        layout.setContentsMargins(10, 5, 10, 5)

        self.id_label      = QLabel(f"id: {robot_name}")
        self.state_label   = QLabel("state: -")
        self.battery_label = QLabel("battery: -")

        self.view_btn = QPushButton("view")
        self.view_btn.setEnabled(False)
        self._set_style(online=False)

        layout.addWidget(self.id_label)
        layout.addWidget(self.state_label)
        layout.addWidget(self.battery_label)
        layout.addWidget(self.view_btn)

        self.setLayout(layout)
        self.setStyleSheet("border-bottom: 1px solid gray; background-color: #ffffff;")

    def _set_style(self, online: bool):
        if online:
            self.view_btn.setStyleSheet(
                "background-color: #3b3bb3; color: white; "
                "padding: 5px 15px; border-radius: 3px;"
            )
        else:
            self.view_btn.setStyleSheet(
                "background-color: gray; color: white; "
                "padding: 5px 15px; border-radius: 3px;"
            )

    def set_online(self, online: bool):
        self.view_btn.setEnabled(online)
        self._set_style(online)

    def update_state(self, state: str, battery: float,
                     available: bool, emergency: bool):
        """/{ros_name}/state 수신 시 라벨 업데이트"""
        self.state_label.setText(f"state: {state}")

        pct = int(battery * 100)
        self.battery_label.setText(f"battery: {pct}%")

        # 배터리 색상
        if pct <= 20:
            self.battery_label.setStyleSheet("color: red; font-weight: bold;")
        elif pct <= 50:
            self.battery_label.setStyleSheet("color: orange;")
        else:
            self.battery_label.setStyleSheet("color: green;")

        # 행 배경색
        if emergency:
            self.setStyleSheet(
                "border-bottom: 1px solid gray; background-color: #ffe0e0;"  # 빨강
            )
        elif not available:
            self.setStyleSheet(
                "border-bottom: 1px solid gray; background-color: #fff8e0;"  # 노랑
            )
        else:
            self.setStyleSheet(
                "border-bottom: 1px solid gray; background-color: #ffffff;"  # 흰색
            )


class ControlUI(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("통합 관제 시스템")
        self.resize(1920, 1080)

        main_layout = QGridLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # ── MAP ───────────────────────────────────────────────
        self.map_frame  = QFrame()
        self.map_frame.setStyleSheet("border: 1px solid #bcbcbc; background-color: #e8dfcf;")
        self.map_layout = QVBoxLayout()
        self.map_layout.setContentsMargins(0, 0, 0, 0)

        map_title = QLabel("  MAP")
        map_title.setStyleSheet("background: black; color: white; font-weight: bold; font-size: 14px;")
        map_title.setFixedHeight(30)

        self.map_canvas = QLabel("MAP VIEW")
        self.map_canvas.setAlignment(Qt.AlignCenter)
        self.map_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.map_layout.addWidget(map_title)
        self.map_layout.addWidget(self.map_canvas)
        self.map_frame.setLayout(self.map_layout)

        # ── EVENT LOG ─────────────────────────────────────────
        self.event_frame  = QFrame()
        self.event_frame.setStyleSheet("border: 1px solid #bcbcbc; background-color: white;")
        self.event_layout = QVBoxLayout()
        self.event_layout.setContentsMargins(0, 0, 0, 0)

        event_title = QLabel("  EVENT LOG")
        event_title.setStyleSheet("background: black; color: white; font-weight: bold; font-size: 14px;")
        event_title.setFixedHeight(30)

        self.event_table = QTableWidget(0, 2)
        self.event_table.setHorizontalHeaderLabels(["Event Description", "Time"])
        header = self.event_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.event_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.event_table.setStyleSheet("border: none;")

        self.event_layout.addWidget(event_title)
        self.event_layout.addWidget(self.event_table)
        self.event_frame.setLayout(self.event_layout)

        # ── ROBOT STATE ───────────────────────────────────────
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        self.robots = cfg["robots"]

        # ViewerController, RobotStateSubscriber 생성
        self.viewer_ctrl  = ViewerController(self)
        self.state_sub    = RobotStateSubscriber(self)

        self.robot_frame  = QFrame()
        self.robot_frame.setStyleSheet("border: 1px solid #bcbcbc; background-color: white;")
        self.robot_layout = QVBoxLayout()
        self.robot_layout.setContentsMargins(0, 0, 0, 0)

        robot_title = QLabel("  ROBOT STATE")
        robot_title.setStyleSheet("background: black; color: white; font-weight: bold; font-size: 14px;")
        robot_title.setFixedHeight(30)

        self.robot_list_container = QVBoxLayout()
        self.robot_list_container.setContentsMargins(0, 0, 0, 0)
        self.robot_list_container.setSpacing(0)

        # config 기준 버튼 생성 (기본 비활성화)
        self.robot_items: dict[str, RobotItem] = {}
        self.robot_ips:   dict[str, str]       = {}

        for robot in self.robots:
            name = robot["robot_name"]
            item = RobotItem(name)
            self.robot_list_container.addWidget(item)
            self.robot_items[name] = item

        self.robot_list_container.addStretch()

        scroll_widget = QWidget()
        scroll_widget.setLayout(self.robot_list_container)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(scroll_widget)
        scroll_area.setStyleSheet("border: none;")

        self.robot_layout.addWidget(robot_title)
        self.robot_layout.addWidget(scroll_area)
        self.robot_frame.setLayout(self.robot_layout)

        # ── VIEWER ────────────────────────────────────────────
        self.viewer_frame  = QFrame()
        self.viewer_frame.setStyleSheet("border: 1px solid #bcbcbc; background-color: gray;")
        self.viewer_layout = QVBoxLayout()
        self.viewer_layout.setContentsMargins(0, 0, 0, 0)

        viewer_title = QLabel("  VIEWER (CAMERA)")
        viewer_title.setStyleSheet("background: black; color: white; font-weight: bold; font-size: 14px;")
        viewer_title.setFixedHeight(30)

        self.viewer = QLabel("CAMERA VIEW")
        self.viewer.setStyleSheet("background-color: #2b2b2b; color: white;")
        self.viewer.setAlignment(Qt.AlignCenter)
        self.viewer.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.viewer.setMinimumSize(1, 1)

        self.viewer_layout.addWidget(viewer_title)
        self.viewer_layout.addWidget(self.viewer)
        self.viewer_frame.setLayout(self.viewer_layout)

        # ── GRID 배치 ─────────────────────────────────────────
        main_layout.addWidget(self.map_frame,    0, 0)
        main_layout.addWidget(self.robot_frame,  1, 1)
        main_layout.addWidget(self.event_frame,  1, 0)
        main_layout.addWidget(self.viewer_frame, 0, 1)

        main_layout.setColumnStretch(0, 3)
        main_layout.setColumnStretch(1, 2)
        main_layout.setRowStretch(0, 3)
        main_layout.setRowStretch(1, 2)

        self.setLayout(main_layout)
        self.setStyleSheet("background-color: #f0f0f0;")

    # ── 로봇 상태 수신 (VideoReceiver → 온/오프라인) ──────────

    def _on_robot_status(self, robot_name: str, robot_ip: str, online: bool):
        item = self.robot_items.get(robot_name)
        if item is None:
            return

        if online:
            self.robot_ips[robot_name] = robot_ip
            item.set_online(True)
            try:
                item.view_btn.clicked.disconnect()
            except (TypeError, RuntimeError):
                pass
            item.view_btn.clicked.connect(
                lambda _, name=robot_name: self.viewer_ctrl.on_view(name)
            )
            self.add_event_log(f"{robot_name} 온라인 ({robot_ip})", self._now())
        else:
            item.set_online(False)
            self.robot_ips.pop(robot_name, None)
            self.add_event_log(f"{robot_name} 오프라인", self._now())

    # ── 로봇 state 수신 (RobotStateSubscriber → 라벨 업데이트) ─

    def _on_robot_state(self, robot_name: str, state: str,
                        battery: float, available: bool, emergency: bool):
        item = self.robot_items.get(robot_name)
        if item is None:
            return

        item.update_state(state, battery, available, emergency)

        # 비상정지 이벤트 로그
        # if emergency:
        #     self.add_event_log(f"{robot_name} 비상정지!", self._now())

    # ── 이벤트 로그 ───────────────────────────────────────────

    def add_event_log(self, description: str, timestamp: str):
        row = self.event_table.rowCount()
        self.event_table.insertRow(row)
        time_item = QTableWidgetItem(timestamp)
        time_item.setTextAlignment(Qt.AlignCenter)
        self.event_table.setItem(row, 0, QTableWidgetItem(description))
        self.event_table.setItem(row, 1, time_item)
        self.event_table.scrollToBottom()

    def _now(self) -> str:
        return datetime.now().strftime("%H:%M:%S")