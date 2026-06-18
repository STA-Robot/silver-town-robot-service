

import threading
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String

from .stateController import StateController, State, Event
from ai_controller.aicore.gestureRecognizer import get_gesture
from ai_controller.aicore.targetTracker import get_person_target, TrackDebugInfo,tracker as global_tracker
from .visualizer import draw as draw_visualizer



class AIControllerNode(Node):

    def __init__(self):
        super().__init__('ai_controller_node')

        self.lock = threading.Lock()

        self._image_subs:  dict[str, object] = {}
        self._result_pubs: dict[str, object] = {}  # 추가
        self._follower_node = None                  # 추가 (set_follower 전에 초기화)
        self.prev_msg: Optional[str] = None
        self.fsm = StateController()

        self._active_robots: set[str] = set()  # 
        self._subscribe_image('pinky1')
        self._subscribe_image('pinky2')

        self.get_logger().info("[AIControllerNode] 시작")

    def set_follower(self, follower_node):
        self._follower_node = follower_node

    def _subscribe_image(self, robot_name: str):
        if robot_name in self._image_subs:
            return

        def make_callback(name):
            def cb(msg):
                self._on_frame(name, msg)
            return cb

        sub = self.create_subscription(
            CompressedImage,
            f'/{robot_name}/image/compressed',
            make_callback(robot_name),
            10
        )
        self._image_subs[robot_name] = sub

        # 수정: 단수 self.result_pub → dict self._result_pubs[robot_name]
        self._result_pubs[robot_name] = self.create_publisher(
            CompressedImage, f'/{robot_name}/result/compressed', 10
        )

        self.get_logger().info(f"[AI] 구독 등록: /{robot_name}/image/compressed")

    def _on_frame(self, robot_name: str, ros_msg: CompressedImage):
        frame = cv2.imdecode(
            np.frombuffer(ros_msg.data, np.uint8), cv2.IMREAD_COLOR
        )
        if frame is None:
            return
         # 첫 프레임 수신 시 on_start 호출
        if robot_name not in self._active_robots:
            self._active_robots.add(robot_name)
            self.get_logger().info(f"[AI] {robot_name} 첫 프레임 → on_start")
            if self._follower_node is not None:
                self._follower_node.on_start(robot_name)
                
        event, g_dbg = get_gesture(frame)
        self.fsm.dispatch(event)

        changed = self.fsm.did_change()
        if changed and self.fsm.state == State.FOLLOW:
            global_tracker.reset()

        t_dbg = TrackDebugInfo()
        cmd   = None

        if self.fsm.state in (State.FOLLOW, State.LOST):
            msg_str, t_dbg = get_person_target(frame)

            if msg_str == "END":
                self.fsm.dispatch(Event.END)
                cmd = "END"
            elif msg_str == "LOST":
                self.fsm.dispatch(Event.LOST)
                cmd = "LOST"
            elif msg_str == "STOP":
                cmd = "STOP"
            else:
                if self.fsm.state == State.LOST:
                    self.fsm.dispatch(Event.FOLLOW)
                cmd = msg_str
        else:
            if changed:
                cmd = self.fsm.state

        if cmd is not None:
            is_follow = isinstance(cmd, str) and cmd.startswith("FOLLOW")
            is_lost   = cmd == "LOST"
            if is_follow or is_lost or cmd != self.prev_msg:
                self.prev_msg = cmd
                if self._follower_node is not None:
                    self._follower_node.on_udp_message(robot_name, cmd)

        # 수정: self.result_pubs → self._result_pubs
        pub = self._result_pubs.get(robot_name)
        if pub is None or pub.get_subscription_count() == 0:
            return

        annotated = draw_visualizer(frame.copy(), self.fsm.state, g_dbg, t_dbg)
        ok, buf = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            return

        result_msg             = CompressedImage()
        result_msg.header.stamp = self.get_clock().now().to_msg()
        result_msg.format      = "jpeg"
        result_msg.data        = buf.tobytes()
        pub.publish(result_msg)


def main(args=None):
    rclpy.init(args=args)

    from ai_controller.followerNode import FollowerNode

    ai_node     = AIControllerNode()
    follow_node = FollowerNode()
    ai_node.set_follower(follow_node)

    executor = rclpy.executors.MultiThreadedExecutor()
    executor.add_node(ai_node)
    executor.add_node(follow_node)

    try:
        executor.spin()
    finally:
        ai_node.destroy_node()
        follow_node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()