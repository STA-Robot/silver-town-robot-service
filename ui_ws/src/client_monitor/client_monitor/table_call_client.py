# table_call_client.py

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
        self.timer = self.create_timer(1.0, self.check_service)
        

    def check_service(self):
        if self.client.wait_for_service(timeout_sec=0.1):
            self.get_logger().info("서비스 연결됨")
            self.timer.cancel()
        else:
            self.get_logger().info("서비스 기다리는 중...")

    def send_request(self, table_id=None, waypoint=None, wait_sec=None, callback=None):
        req = TableCall.Request()
        req.table_id = table_id if table_id else self.table_id
        req.table_waypoint = waypoint if waypoint else self.waypoint
        req.wait_seconds = wait_sec if wait_sec else self.wait_seconds

        future = self.client.call_async(req)
        future.add_done_callback(lambda f: self._on_response(f, callback))
        return future

    def _on_response(self, future, callback=None):
        response = None
        try:
            response = future.result()
            self.get_logger().info(
                f"table_call 응답 - accepted={response.accepted}, "
                f"mission_id={response.mission_id}, message={response.message}"
            )
        except Exception as e:
            self.get_logger().error(f"table_call 서비스 호출 실패: {e}")

        if callback:
            callback(response)