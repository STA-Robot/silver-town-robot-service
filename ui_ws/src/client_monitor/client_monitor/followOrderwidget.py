from PyQt5.QtWidgets import (
    QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QComboBox, QSpinBox
)
from PyQt5.QtCore import Qt, QObject, pyqtSignal
from client_monitor.follow_call_node import FollowerCall


class FollowResultBridge(QObject):
    received = pyqtSignal(object)  # FollowCall.Response 또는 None


class FollowOrderwidget(QWidget):
    def __init__(self):
        super().__init__()
        self.follow_call_node = FollowerCall()
        self.result_bridge = FollowResultBridge()
        self.result_bridge.received.connect(self.on_follow_result)
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("운반 요청")
        self.setFixedSize(800, 400)

        main_layout = QVBoxLayout()
        top_layout = QHBoxLayout()

        requester_layout = QVBoxLayout()
        requester_layout.addWidget(QLabel("요청자"))
        self.requester_combo = QComboBox()
        self.requester_combo.addItems(["선택해 주세요", "김영희 요양사", "이철수 요양사"])
        requester_layout.addWidget(self.requester_combo)
        top_layout.addLayout(requester_layout)

        # 추가: /follow_call 서비스 호출에 robot_name이 필요해서 새로 넣음
        robot_layout = QVBoxLayout()
        robot_layout.addWidget(QLabel("로봇"))
        self.robot_combo = QComboBox()
        self.robot_combo.addItems(["pinky1", "pinky2"])
        robot_layout.addWidget(self.robot_combo)
        top_layout.addLayout(robot_layout)

        item_layout = QVBoxLayout()
        item_layout.addWidget(QLabel("품목"))
        self.item_combo = QComboBox()
        self.item_combo.addItems(["선택해 주세요", "북 놀이", "공 놀이"])
        item_layout.addWidget(self.item_combo)
        top_layout.addLayout(item_layout)

        quantity_layout = QVBoxLayout()
        quantity_layout.addWidget(QLabel("수량"))
        self.quantity_spin = QSpinBox()
        self.quantity_spin.setRange(1, 10)
        quantity_layout.addWidget(self.quantity_spin)
        top_layout.addLayout(quantity_layout)

        self.btn_request = QPushButton("운반요청")
        self.btn_request.setStyleSheet(
            "background-color: red; color: white; font-size: 20px; height: 50px;"
        )
        self.btn_request.clicked.connect(self.on_request)  # 누락됐던 연결 추가

        self.result_label = QLabel("")
        self.result_label.setAlignment(Qt.AlignCenter)

        main_layout.addLayout(top_layout)
        main_layout.addSpacing(20)
        main_layout.addWidget(self.btn_request)
        main_layout.addWidget(self.result_label)

        self.setLayout(main_layout)

    def on_request(self):
        requester = self.requester_combo.currentText()
        robot_name = self.robot_combo.currentText()
        item = self.item_combo.currentText()
        quantity = self.quantity_spin.value()

        self._last_request_info = (requester, robot_name, item, quantity)
        self.result_label.setText("요청 전송 중...")
        self.follow_call_node.send_request(
            robot_name=robot_name,
            callback=self.result_bridge.received.emit
        )

    def on_follow_result(self, response):
        requester, robot_name, item, quantity = self._last_request_info
        if response is None:
            self.result_label.setText("운반 요청 실패: 응답 없음")
        elif response.accepted:
            self.result_label.setText(
                f"{requester}님이 {robot_name} 로봇으로 {item} {quantity}개 요청 (미션: {response.mission_id})"
            )
        else:
            self.result_label.setText(f"운반 요청 거부됨: {response.message}")