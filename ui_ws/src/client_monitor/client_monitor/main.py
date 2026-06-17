import sys
import threading
import rclpy
from PyQt5.QtWidgets import QApplication

from client_monitor.tableOrderwidget import TableOrderWidget
from client_monitor.followOrderwidget import FollowOrderwidget


def main():
    # ROS 시작
    rclpy.init()

    app = QApplication(sys.argv)
    t_window = TableOrderWidget()
    t_window.show()

    f_window = FollowOrderwidget()
    f_window.show()


    executor = rclpy.executors.MultiThreadedExecutor()
    executor.add_node(t_window.table_call_node)
    executor.add_node(f_window.follow_call_node)

    spin_thread = threading.Thread(
        target=executor.spin,
        daemon=True
    )
    spin_thread.start()

    # UI 실행
    exit_code = app.exec_()

    # 종료 처리
    executor.shutdown()
    t_window.table_call_node.destroy_node()
    f_window.follow_call_node.destroy_node()
    rclpy.shutdown()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()