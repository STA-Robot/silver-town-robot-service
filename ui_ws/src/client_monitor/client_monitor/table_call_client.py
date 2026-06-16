# table_call_client.py

import rclpy
from rclpy.node import Node
from task_msgs.srv import TableCall


class TableCallClient(Node):
    def __init__(self):
        super().__init__('table_call_client')
        # 파라미터 선언
        self.declare_parameter('table_id', 'tent_1')
        self.declare_parameter('waypoint', 'tent_1')
        self.declare_parameter('wait_seconds', 20)

        # 값 가져오기
        self.table_id = self.get_parameter('table_id').value
        self.waypoint = self.get_parameter('waypoint').value
        self.wait_seconds = self.get_parameter('wait_seconds').value

        self.client = self.create_client(TableCall, '/table_call')

        while not self.client.wait_for_service(timeout_sec=1.0):
            self.get_logger().info('서비스 기다리는 중...')

    def send_request(self, table_id=None, waypoint=None, wait_sec=None):
        req = TableCall.Request()

        req.table_id = table_id if table_id else self.table_id
        req.table_waypoint = waypoint if waypoint else self.waypoint
        req.wait_seconds = wait_sec if wait_sec else self.wait_seconds

        return self.client.call_async(req)