import sys
import rclpy
from PyQt5.QtWidgets import QApplication
from ui_ws.src.client_monitor.client_monitor.table_call_client import TableCallClient
from ui_ws.src.client_monitor.client_monitor.tableOrderwidget import TableOrderWidget


def main():
    # ROS 시작
    rclpy.init()

    # PyQt 시작
    app = QApplication(sys.argv)

    # ROS 노드 생성
    ros_node = TableCallClient()

    # UI 생성 (Node 주입)
    window = TableOrderWidget(ros_node)
    window.show()

    # UI 실행
    exit_code = app.exec_()

    # 종료 처리
    ros_node.destroy_node()
    rclpy.shutdown()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()