import os
os.environ.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
os.environ["QT_QPA_PLATFORM"] = "xcb"

import sys
import threading
import rclpy
from PyQt5.QtWidgets import QApplication
from ui_ws.src.pyqt_monitor.pyqt_monitor.QTlayout import ControlUI


def main():
    rclpy.init()

    app    = QApplication(sys.argv)
    window = ControlUI()
    window.show()

    # ViewerController 안의 ROS 노드만 spin
    spin_thread_Viewer = threading.Thread(
        target=rclpy.spin,
        args=(window.viewer_ctrl.get_ros_node(),),
        daemon=True
    )
    spin_thread_Viewer.start()

    pin_thread_state = threading.Thread(
        target=rclpy.spin,
        args=(window.state_sub.get_ros_node(),),
        daemon=True
    )
    pin_thread_state.start()

    exit_code = app.exec_()

    window.viewer_ctrl.ros.destroy_node()
    window.state_sub.destroy()
    rclpy.shutdown()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()