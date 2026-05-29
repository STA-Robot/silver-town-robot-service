import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from std_msgs.msg import String

from udpReceiver import UDPReceiver
from msgHandler import StateHandler


class FollowerNode(Node):
    def __init__(self):
        super().__init__('follower_node')

        self.pub       = self.create_publisher(Twist,  '/cmd_vel',      10)
        self.event_pub = self.create_publisher(String, '/follow_event', 10)

        self._is_ended    = False
        self._was_timeout = False

        self.state_handler = StateHandler(logger=self.get_logger())

        # 이벤트 드리븐: 메시지 도착 즉시 _on_udp_message() 호출
        self.udp = UDPReceiver(
            port=9998,
            logger=self.get_logger(),
            on_message=self._on_udp_message
        )

        # timeout 감시 + Recovery 호출 전용 타이머
        self.timeout_timer = self.create_timer(0.5, self._check_timeout)

        self.get_logger().info("Follower Node Started")

    # UDP 메시지 콜백 
    def _on_udp_message(self, msg):
        if self._is_ended:
            return

        if self._was_timeout:
            self.get_logger().info("UDP 수신 재개")
            self._was_timeout = False

        twist = Twist()
        event = self.state_handler.handle(msg, twist)

        if event == "done":
            self._on_end()
            return

        self.pub.publish(twist)

    # timeout 감시 + Recovery 
    def _check_timeout(self):
        if self._is_ended:
            return

        if self.udp.is_timeout(1.0):# UDP 1초 이상 안 오면
            if not self._was_timeout:
                self.get_logger().warn("UDP timeout → STOP")
                self._was_timeout = True
            self.pub.publish(Twist())
            return

        # UDP는 살아있지만 FOLLOW 메시지가 끊긴 경우 → Recovery 시도
        # (STOP/END 상태일 땐 controller.target_id가 None이므로 자동으로 None 반환)
        result = self.state_handler.controller.compute_recovery()
        if result is not None:
            linear, angular = result
            twist = Twist()
            twist.linear.x  = linear
            twist.angular.z = angular
            self.pub.publish(twist)

    # END 처리 
    def _on_end(self):
        self.pub.publish(Twist())           # 즉시 정지

        e      = String()
        e.data = "done"
        self.event_pub.publish(e)
        self.get_logger().info("[EVENT] done 발행 → FOLLOW 완전 비활성화")

        self.udp.close()
        self.timeout_timer.cancel()
        self._is_ended = True

    #노드 종료 
    def destroy_node(self):
        if not self._is_ended:
            self.udp.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = FollowerNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()