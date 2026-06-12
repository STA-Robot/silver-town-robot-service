import rclpy
import json
from rclpy.node import Node
from geometry_msgs.msg import Twist
from std_msgs.msg import String

from pinky_follower.udpReceiver import UDPReceiver
from pinky_follower.msgHandler import StateHandler


class FollowerNode(Node):
    def __init__(self):
        super().__init__('follower_node')
        self.declare_parameter('robot_name', "pinky2")
        self.declare_parameter('robot_ip', "192.168.4.1")
        self.declare_parameter('robot_port', 9998)
 
        self.robot_name = self.get_parameter('robot_name').value
        self.robot_ip = self.get_parameter('robot_ip').value
        self.robot_port = int(self.get_parameter('robot_port').value)
       
        self.target_pub = self.create_publisher(String, '/ai_target', 10)
        self.pub       = self.create_publisher(Twist,  '/cmd_vel',      10)
        self.event_pub = self.create_publisher(String, '/follow_event', 10)
        
        # State flags
        self.running = False
        self._is_ended    = False
        self._was_timeout = False
        self._has_received = False
        self.state_handler = StateHandler(logger=self.get_logger())

        # 이벤트 드리븐: 메시지 도착 즉시 _on_udp_message() 호출
        self.udp = UDPReceiver(
            port=self.robot_port,
            logger=self.get_logger(),
            on_message=self._on_udp_message
        )

        # Control subscriber (START / STOP)
        self.control_sub = self.create_subscription(
            String,
            'follow_command',
            self._on_control_event,
            10
        )

        # timeout 감시 + Recovery 호출 전용 타이머
        self.timeout_timer = self.create_timer(0.5, self._check_timeout)

        self.get_logger().info("Follower Node Ready (waiting follow_start)")

    # CONTROL EVENT (START / STOP)
    def _on_control_event(self, msg: String): 
        if msg.data == "start":
            self.get_logger().info("FOLLOW START")

            self._is_ended = False
            self._was_timeout = False
            self._has_received = False

            self.udp.reset()  # UDP 재연결

            if self.timeout_timer.is_canceled():
                self.timeout_timer.reset()

            self._on_Start_With_IP()
            self.running = True

        # elif msg.data == "stop":          # ← 추가
        #     self.get_logger().info("FOLLOW STOP")
        #     self._on_Stop()


    # START IP Pub 
    def _on_Start_With_IP(self):
        self.get_logger().info("Start_With_IP")
        data={
              "robot_name":self.robot_name,
              "robot_ip":self.robot_ip,
              "robot_port":self.robot_port,
              "active": True 
              }
        msg = String()
        msg.data = json.dumps(data)
        self.target_pub.publish(msg)
        self.get_logger().info(f"Start_With_IP {data}") 

    # UDP 메시지 콜백 
    def _on_udp_message(self, msg):
        self.get_logger().info(f"Start_on_udp_message") 
        if self._is_ended or not self.running:
            return
        self._has_received = True
        if self._was_timeout:
            self.get_logger().info("UDP 수신 재개")
            self._was_timeout = False

        twist = Twist()
        event = self.state_handler.handle(msg, twist)

        if event == "done":
            self._on_end()
            return

        self.pub.publish(twist)
        self.get_logger().info(f"Start_twist {twist}") 

    # timeout 감시 + Recovery 
    def _check_timeout(self):
        if self._is_ended or not self.running:
            return
        if not self._has_received:
            return

        if self.udp.is_timeout(1.0):# UDP 1초 이상 안 오면
            if not self._was_timeout:
                self.get_logger().warn("UDP timeout → STOP")
                self._was_timeout = True
            self.pub.publish(Twist())
            return

      
    # END 처리 
    def _on_end(self):
        self.get_logger().info("FOLLOW DONE")

        self.running = False
        self._is_ended = True

        self.pub.publish(Twist())
        data={
              "robot_name":self.robot_name,
              "robot_ip":self.robot_ip,
              "robot_port":self.robot_port,
              "active": False 
              }
        stop_msg = String()
        stop_msg.data = json.dumps(data)
        self.target_pub.publish(stop_msg)

        msg = String()
        msg.data = "done"
        self.event_pub.publish(msg)

        self.udp.close()
        self.timeout_timer.cancel()

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