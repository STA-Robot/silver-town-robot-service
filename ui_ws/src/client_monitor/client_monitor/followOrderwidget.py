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

    # init_ui는 이전 답변 그대로 (robot_combo 포함)

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