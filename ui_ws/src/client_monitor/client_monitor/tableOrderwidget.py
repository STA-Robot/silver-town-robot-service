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

        # 1. 헤더
        header = QLabel("Table-1")
        header.setStyleSheet("background-color: black; color: white; padding-left: 20px;")
        header.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        header.setFont(QFont("Arial", 16, QFont.Bold))
        header.setFixedHeight(80)

        # 2. 버튼 영역
        btn_area = QWidget()
        btn_area.setStyleSheet("background-color: #333333;")
        btn_layout = QHBoxLayout(btn_area)
        btn_layout.setContentsMargins(50, 50, 50, 50)
        btn_layout.setSpacing(40)

        # 버튼 스타일 (공통)
        btn_style = """
        QPushButton {
            color: white;
            font-weight: bold;
            font-size: 20px;
            border-radius: 8px;
            padding: 15px;
        }
        QPushButton:hover {
            background-color: #555555;
        }
        QPushButton:pressed {
            background-color: #222222;
        }
        QPushButton:checked {
            border: 3px solid black;
        }
        """

        # 버튼 생성
        self.btn_call = QPushButton("호출")
        self.btn_return = QPushButton("반환")

        # 토글 가능하게 설정
        self.btn_call.setCheckable(True)
        self.btn_return.setCheckable(True)

        # 색상 적용
        self.btn_call.setStyleSheet(btn_style + "QPushButton { background-color: #00A000; }")
        self.btn_return.setStyleSheet(btn_style + "QPushButton { background-color: #D00000; }")

        # 클릭 시 하나만 선택되도록
        self.btn_call.clicked.connect(self.on_call_clicked)
        self.btn_return.clicked.connect(self.on_return_clicked)

        btn_layout.addWidget(self.btn_call)
        btn_layout.addWidget(self.btn_return)


        main_layout.addWidget(self.header)
        main_layout.addWidget(btn_area)
        self.setLayout(main_layout)

    def on_call_clicked(self):
        self.btn_return.setChecked(False)
        self.header.setText("Table-1 (요청 중...)")
        self.table_call_node.send_request(
            table_id="table_1",
            waypoint="table_1",
            wait_sec=5,
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