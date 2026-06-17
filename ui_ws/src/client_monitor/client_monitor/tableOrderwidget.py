from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
from PyQt5.QtCore import Qt, QObject, pyqtSignal
from PyQt5.QtGui import QFont
from client_monitor.table_call_client import TableCallClient


class CallResultBridge(QObject):
    received = pyqtSignal(object)  # TableCall.Response 또는 None


class TableOrderWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.table_call_node = TableCallClient()
        self.result_bridge = CallResultBridge()
        self.result_bridge.received.connect(self.on_call_result)
        self.setWindowTitle("테이블 오더")
        self.resize(600, 400)
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.header = QLabel("Table-1")          # self.header로 저장
        self.header.setStyleSheet("background-color: black; color: white; padding-left: 20px;")
        self.header.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.header.setFont(QFont("Arial", 16, QFont.Bold))
        self.header.setFixedHeight(80)

        # ... (버튼 영역은 기존과 동일) ...

        main_layout.addWidget(self.header)
        main_layout.addWidget(btn_area)
        self.setLayout(main_layout)

    def on_call_clicked(self):
        self.btn_return.setChecked(False)
        self.header.setText("Table-1 (요청 중...)")
        self.table_call_node.send_request(
            table_id="tent_1",
            waypoint="tent_1",
            wait_sec=20,
            callback=self.result_bridge.received.emit
        )

    def on_call_result(self, response):
        if response is None:
            self.header.setText("Table-1 (호출 실패: 응답 없음)")
        elif response.accepted:
            self.header.setText(f"Table-1 (호출됨 / {response.mission_id})")
        else:
            self.header.setText(f"Table-1 (거부됨: {response.message})")

    def on_return_clicked(self):
        self.btn_call.setChecked(False)