import sys
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSpacerItem, QSizePolicy
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

class TableOrderWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("테이블 오더")
        self.resize(600, 400)
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. 헤더 영역 (검은색, 좌측 정렬)
        header = QLabel("Table-1")
        header.setStyleSheet("background-color: black; color: white; padding-left: 20px;")
        header.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        header.setFont(QFont("Arial", 16, QFont.Bold))
        header.setFixedHeight(80)  # 설계서 비율 반영

        # 2. 버튼 영역 (짙은 회색 배경)
        btn_area = QWidget()
        btn_area.setStyleSheet("background-color: #333333;")
        btn_layout = QHBoxLayout(btn_area)
        btn_layout.setContentsMargins(50, 50, 50, 50)
        btn_layout.setSpacing(40)

        # 버튼 스타일 (색상 및 형태)
        btn_style_common = "color: white; font-weight: bold; font-size: 20px; border-radius: 8px; padding: 15px;"
        
        btn_call = QPushButton("호출")
        btn_call.setStyleSheet(btn_style_common + "background-color: #00A000;") # 녹색
        
        btn_return = QPushButton("반환")
        btn_return.setStyleSheet(btn_style_common + "background-color: #D00000;") # 빨간색

        btn_layout.addWidget(btn_call)
        btn_layout.addWidget(btn_return)

        main_layout.addWidget(header)
        main_layout.addWidget(btn_area)
        
        self.setLayout(main_layout)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TableOrderWidget()
    window.show()
    sys.exit(app.exec_())