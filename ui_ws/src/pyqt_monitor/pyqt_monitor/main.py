import os
os.environ.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
os.environ["QT_QPA_PLATFORM"] = "xcb"

import sys
import threading
import rclpy
import threading, asyncio
from PyQt5.QtWidgets import QApplication
from pyqt_monitor.QTlayout import ControlUI


def main():
    rclpy.init()

    app = QApplication(sys.argv)
    window = ControlUI()
    window.show()

    # WebSocket 서버 스레드
    def run_ws():
        try:
            asyncio.run(window.ws_bridge.run())
        except Exception as e:
            print(f"[WS ERROR] {e}", flush=True)

    threading.Thread(target=run_ws, daemon=True).start()
    print("[DEBUG] WS 스레드 시작됨")

    executor = rclpy.executors.MultiThreadedExecutor()
    executor.add_node(window.viewer_ctrl.get_ros_node())
    executor.add_node(window.state_sub.get_ros_node())
    executor.add_node(window.task_event.get_ros_node())

    spin_thread = threading.Thread(
        target=executor.spin,
        daemon=True
    )
    spin_thread.start()

    exit_code = app.exec_()

    executor.shutdown()
    window.viewer_ctrl.ros.destroy_node()
    window.state_sub.destroy()
    window.task_event.ros.destroy_node()
    rclpy.shutdown()

    sys.exit(exit_code)


if __name__ == '__main__':
    main()