import sys
import os
import yaml

from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QGridLayout, QTableWidget, QTableWidgetItem, QFrame, QScrollArea, QHeaderView, QSizePolicy
)
from PyQt5.QtCore import Qt

from pyqt_monitor.ViewerController import ViewerController

_root = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_config_path     = os.path.join(_root, "videoReceiv", "config.yaml")

class RobotItem(QWidget):
    def __init__(self, robot_id):
        super().__init__()

        layout = QHBoxLayout()
        # 리스트 아이템 내부 여백 최소화
        layout.setContentsMargins(10, 5, 10, 5)

        self.id_label = QLabel(f"id: {robot_id}")
        self.state_label = QLabel("state")
        self.battery_label = QLabel("battery")

        self.view_btn = QPushButton("view")
        self.view_btn.setStyleSheet("background-color: #3b3bb3; color: white; padding: 5px 15px; border-radius: 3px;")

        layout.addWidget(self.id_label)
        layout.addWidget(self.state_label)
        layout.addWidget(self.battery_label)

        layout.addWidget(self.view_btn)
    
        self.setLayout(layout)
        # 기본 테두리 스타일 유지
        self.setStyleSheet("border-bottom: 1px solid gray; background-color: #ffffff;")


class ControlUI(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("통합 관제 시스템")
        self.resize(1920, 1080)

        # 메인 레이아웃 간격 조정 (여백을 주어 컴포넌트 간 구분감 확보)
        main_layout = QGridLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # ---------------------------
        # 1. MAP 영역
        # ---------------------------
        self.map_frame = QFrame()
        self.map_frame.setStyleSheet("border: 1px solid #bcbcbc; background-color: #e8dfcf;")
        self.map_layout = QVBoxLayout()
        self.map_layout.setContentsMargins(0, 0, 0, 0)

        map_title = QLabel("  MAP")
        map_title.setStyleSheet("background: black; color: white; font-weight: bold; font-size: 14px;")
        map_title.setFixedHeight(30)

        self.map_canvas = QLabel("MAP VIEW")
        self.map_canvas.setAlignment(Qt.AlignCenter)
        # 화면 변화에 유연하게 대응하도록 사이즈 정책 설정
        self.map_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.map_layout.addWidget(map_title)
        self.map_layout.addWidget(self.map_canvas)
        self.map_frame.setLayout(self.map_layout)

        # ---------------------------
        # 2. EVENT LOG (요청 수정 반영 영역)
        # ---------------------------
        self.event_frame = QFrame()
        self.event_frame.setStyleSheet("border: 1px solid #bcbcbc; background-color: white;")
        self.event_layout = QVBoxLayout()
        self.event_layout.setContentsMargins(0, 0, 0, 0)

        event_title = QLabel("  EVENT LOG")
        event_title.setStyleSheet("background: black; color: white; font-weight: bold; font-size: 14px;")
        event_title.setFixedHeight(30)

        # 열(Column) 개수를 다시 2개로 설정합니다.
        self.event_table = QTableWidget(0, 2)
        # 이름(Name)을 빼고 직관적인 2개 헤더로 지정합니다.
        self.event_table.setHorizontalHeaderLabels(["Event Description", "Time"]) 
        
        # 컬럼별 너비 비율 설정
        header = self.event_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)          # ROS 로그가 들어올 공간 (가장 넓게 꽉 채우기!)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents) # 시간은 글자 크기에 맞춤
        
        self.event_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.event_table.setStyleSheet("border: none;") 

        self.event_layout.addWidget(event_title)
        self.event_layout.addWidget(self.event_table)
        self.event_frame.setLayout(self.event_layout)

        # ---------------------------
        # 3. ROBOT STATE
        # ---------------------------
        # config.yaml 에서 로봇 목록 로드
        with open(_config_path) as f:
            cfg = yaml.safe_load(f)
        self.robots = cfg["robots"]  # [{id, ip, domain_id}, ...]
        # ViewerController 생성
        self.viewer_ctrl = ViewerController(self)

        self.robot_frame = QFrame()
        self.robot_frame.setStyleSheet("border: 1px solid #bcbcbc; background-color: white;")
        self.robot_layout = QVBoxLayout()
        self.robot_layout.setContentsMargins(0, 0, 0, 0)

        robot_title = QLabel("  ROBOT STATE")
        robot_title.setStyleSheet("background: black; color: white; font-weight: bold; font-size: 14px;")
        robot_title.setFixedHeight(30)

        self.robot_list_container = QVBoxLayout()
        self.robot_list_container.setContentsMargins(0, 0, 0, 0)
        self.robot_list_container.setSpacing(0)

        # 예시 로봇 4개 등록
        for robot in self.robots:
            item = RobotItem(robot["id"])
            item.view_btn.clicked.connect(lambda _, ip=robot["ip"]: self.viewer_ctrl.on_view(ip))
            self.robot_list_container.addWidget(item)
        
        # 스크롤 영역 내부가 남을 때 아이템들을 위로 밀착시키기 위한 Stretch
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

        # ---------------------------
        # 4. VIEWER
        # ---------------------------
        self.viewer_frame = QFrame()
        self.viewer_frame.setStyleSheet("border: 1px solid #bcbcbc; background-color: gray;")
        self.viewer_layout = QVBoxLayout()
        self.viewer_layout.setContentsMargins(0, 0, 0, 0)

        viewer_title = QLabel("  VIEWER (CAMERA)")
        viewer_title.setStyleSheet("background: black; color: white; font-weight: bold; font-size: 14px;")
        viewer_title.setFixedHeight(30)

        self.viewer = QLabel("CAMERA VIEW")
        self.viewer.setStyleSheet("background-color: #2b2b2b; color: white;")
        self.viewer.setAlignment(Qt.AlignCenter)
        self.viewer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.viewer_layout.addWidget(viewer_title)
        self.viewer_layout.addWidget(self.viewer)
        self.viewer_frame.setLayout(self.viewer_layout)

        # ---------------------------
        # GRID 배치 및 비율 설정
        # ---------------------------
        main_layout.addWidget(self.map_frame, 0, 0)
        main_layout.addWidget(self.robot_frame, 1, 1)
        main_layout.addWidget(self.event_frame, 1, 0)
        main_layout.addWidget(self.viewer_frame, 0, 1)

        # 지정하신 3:2 비율이 전체 화면 해상도 변화 시에도 엄격히 유지됩니다.
        main_layout.setColumnStretch(0, 3)
        main_layout.setColumnStretch(1, 2)
        main_layout.setRowStretch(0, 3)
        main_layout.setRowStretch(1, 2)

        self.setLayout(main_layout)
        # 전체 백그라운드 색상 지정 (컴포넌트 간 틈새 색상)
        self.setStyleSheet("background-color: #f0f0f0;") 


        # (테스트용 임시 코드) 함수가 잘 작동하는지 가짜 로그 20개 넣어보기
        for i in range(20):
            self.add_event_log(f"로봇 {i%4}호기가 임무를 성공적으로 수행 중입니다. 상태 이상 없음.", f"17:15:{i:02d}")

    def add_event_log(self, description, timestamp):
        # 1. 새 행(Row) 생성
        current_row_count = self.event_table.rowCount()
        self.event_table.insertRow(current_row_count) 
       
        
        time_item = QTableWidgetItem(timestamp)
        time_item.setTextAlignment(Qt.AlignCenter)
        
        # 3. 각각의 방 번호에 맞게 데이터를 정확히 배달합니다.
        self.event_table.setItem(current_row_count, 0, QTableWidgetItem(description)) # 1번 방: ROS 로그 내용 (좌측 정렬)
        self.event_table.setItem(current_row_count, 1, time_item)                     # 2번 방: 시간 (가운데 정렬)
        
        # 4. 스크롤을 맨 아래로 이동 (새 로그 추적)
        self.event_table.scrollToBottom()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ControlUI()
    window.show()
    sys.exit(app.exec_())