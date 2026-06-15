import rclpy
import time
import threading
from typing import Optional
from rclpy.node import Node
from geometry_msgs.msg import Twist
from std_msgs.msg import String

from .msgHandler import StateHandler


class FollowerNode(Node):
    def __init__(self,on_end_callback=None):
        super().__init__('follower_node')

        self.lock = threading.Lock()
        # State flags
        self._robot_name: Optional[str]  = None
        self._last_recv_time: float = 0.0
        self._is_ended    = False
        self._was_timeout = False
        self._has_received = False
        self.state_handler:   Optional[StateHandler] = None

        # robot_name별 퍼블리셔 캐시
        self._cmd_vel_pubs:      dict[str, object] = {}
        self._follow_event_pubs: dict[str, object] = {}
        # timeout 감시 + Recovery 호출 전용 타이머
        self.timeout_timer = self.create_timer(0.5, self._check_timeout)
        self._on_end_callback = on_end_callback 
        self.get_logger().info("Follower Node Ready (waiting follow_start)")

    def on_start(self, robot_name: str):
        with self.lock:
            self._robot_name     = robot_name
            self._is_ended       = False
            self._was_timeout    = False
            self._has_received   = False
            self._last_recv_time = 0.0
            self.state_handler   = StateHandler()
            # 퍼블리셔 동적 생성 (최초 1회)
            if robot_name not in self._cmd_vel_pubs:
                self._cmd_vel_pubs[robot_name] = self.create_publisher(
                    Twist, f'/{robot_name}/cmd_vel', 10   # /pinky1/cmd_vel
                )
            if robot_name not in self._follow_event_pubs:
                self._follow_event_pubs[robot_name] = self.create_publisher(
                    String, f'/{robot_name}/follow_event', 10  # /pinky1/follow_event
                )


    def on_udp_message(self,robot_name:String, cmd: String):
        with self.lock:
            if self._is_ended or self._robot_name != robot_name:
                return
            self._has_received   = True
            self._last_recv_time = time.time()
            if self._was_timeout:
                self.get_logger().info(f"[Follow] {robot_name} 수신 재개")
                self._was_timeout = False

            twist = Twist()
            event = self.state_handler.handle(cmd, twist)
            pub   = self._cmd_vel_pubs.get(robot_name)

        if event == "done":
            self._on_end(robot_name, reason="done")
            return

        if pub is not None:
            pub.publish(twist)

    # timeout 감시 + Recovery 
    def _check_timeout(self):
        with self.lock:
            if self._is_ended or not self._has_received or self._robot_name is None:
                return
            robot_name = self._robot_name
            elapsed    = time.time() - self._last_recv_time
            pub        = self._cmd_vel_pubs.get(robot_name)

        if elapsed > 1.0:
            if not self._was_timeout:
                self.get_logger().warn(f"[Follow] {robot_name} timeout → STOP")
                with self.lock:
                    self._was_timeout = True
            if pub is not None:
                pub.publish(Twist())

      
    # END 처리 
    def _on_end(self, robot_name: str, reason: str = "done"):
        with self.lock:
            if self._is_ended:
                return
            self._is_ended   = True
            self._robot_name = None
            pub_event = self._follow_event_pubs.get(robot_name)
            pub_cmd   = self._cmd_vel_pubs.get(robot_name)

        if pub_cmd is not None:
            pub_cmd.publish(Twist())  # 정지

        if pub_event is not None:
            msg = String()
            msg.data = reason   # "done" | "stop"
            pub_event.publish(msg)  # /pinky1/follow_event

        if self._on_end_callback is not None:
            self._on_end_callback(robot_name)

        self.get_logger().info(f"[FollowerNode] {robot_name} END ({reason})")

    #노드 종료 
    def destroy_node(self):
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = FollowerNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()