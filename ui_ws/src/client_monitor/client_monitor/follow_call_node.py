# follow_call_node.py
import rclpy
from rclpy.node import Node
from task_msgs.srv import FollowCall


class FollowerCall(Node):
    def __init__(self):
        super().__init__('follow_call_client')
        self.client = self.create_client(FollowCall, '/follow_call')
        self.timer = self.create_timer(1.0, self.check_service)

    def check_service(self):
        if self.client.wait_for_service(timeout_sec=0.1):
            self.get_logger().info("서비스 연결됨")
            self.timer.cancel()
        else:
            self.get_logger().info("서비스 기다리는 중...")

    def send_request(self, robot_name, callback=None):
        req = FollowCall.Request()
        req.robot_name = robot_name

        future = self.client.call_async(req)
        future.add_done_callback(lambda f: self._on_response(f, callback))
        return future

    def _on_response(self, future, callback=None):
        response = None
        try:
            response = future.result()
            self.get_logger().info(
                f"follow_call 응답 - accepted={response.accepted}, "
                f"mission_id={response.mission_id}, message={response.message}"
            )
        except Exception as e:
            self.get_logger().error(f"follow_call 서비스 호출 실패: {e}")

        if callback:
            callback(response)