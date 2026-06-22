import json
from rclpy.node import Node
from std_msgs.msg import String
from PyQt5.QtCore import QObject, pyqtSignal


class TaskEventBridge(QObject):
     
    event_received = pyqtSignal(dict)
    def __init__(self, ui):
        QObject.__init__(self)
        self.ui = ui
        self.ros=TaskEventSubscriberNode(self)
        
        self.event_received.connect(self.ui._on_task_event_received)

    def get_ros_node(self):
        return self.ros


class TaskEventSubscriberNode(Node):

    def __init__(self, bridge: TaskEventBridge):
        super().__init__('task_event_subscriber_node')
        self._bridge = bridge
        self.create_subscription(
            String,
            '/task_events',
            self._on_task_event,
            10,
        )

    def _on_task_event(self, msg: String):
        try:
            data = json.loads(msg.data)
        except json.JSONDecodeError as e:
            self.get_logger().warn(f"task_events JSON 파싱 실패: {e} / raw={msg.data}")
            return

        if "robot_name" not in data or "event" not in data:
            self.get_logger().warn(f"task_events 필수 필드 누락: {data}")
            return

        self._bridge.event_received.emit(data)