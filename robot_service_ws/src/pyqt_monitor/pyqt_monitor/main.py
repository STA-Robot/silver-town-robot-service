# main.py
import sys
import threading

import rclpy
from PyQt5.QtWidgets import QApplication
from pyqt_monitor.QTlayout import ControlUI


def main():
    rclpy.init()

    app = QApplication(sys.argv)
    window = ControlUI()
    window.show()

    # ROS2 spin → 별도 스레드 (PyQt 메인루프와 충돌 방지)
    spin_thread = threading.Thread(
        target=rclpy.spin,
        args=(window.viewer_ctrl,),  # ViewerController 노드
        daemon=True
    )
    spin_thread.start()

    exit_code = app.exec_()

    window.viewer_ctrl.destroy_node()
    rclpy.shutdown()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()