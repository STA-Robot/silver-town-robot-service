
import json
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
from ai_controller.aicore.targetTracker import get_person_target, tracker as global_tracker
from .visualizer import draw as draw_visualizer



class AIControllerNode(Node):

    def __init__(self):
        super().__init__('ai_controller_node')

        self.lock = threading.Lock()

        # ── 상태 ───────────────────────────────────────────────
        self._current_name:   Optional[str]         = None
        self._image_subs:   dict[str, object] = {}   # robot_name별 구독 캐시
        self.prev_msg:      Optional[str]         = None
        self.fsm = StateController()

         # ── AI 추론 대상 구독 ──────────────────────────────────
        #pinky1,pinky2두개에 구독 
        self._subscribe_image('pinky1')
        self._subscribe_image('pinky2')

        self.get_logger().info("[AIControllerNode] 시작")

    def set_follower(self, follower_node):
        self._follower_node = follower_node    

    def _subscribe_image(self, robot_name: str):
        #robot_name 토픽 구독 등록 (중복 방지)
        if robot_name in self._image_subs:
            return
        topic = f'/{robot_name}/image/compressed'
        # 클로저로 robot_name 캡처
        def make_callback(name):
            def cb(msg):
                self._on_frame(name, msg)
            return cb

        sub = self.create_subscription(
            CompressedImage, topic, make_callback(robot_name), 10
        )
        self._image_subs[robot_name] = sub

         # 디버그 발행 (GUI용)
        topic = f'/{robot_name}/result/compressed'
        self.result_pub = self.create_publisher(CompressedImage,topic, 10)

        self.get_logger().info(f"[AI] 구독 등록: {topic}")    

    def _start_inference(self, robot_name: str):
        with self.lock:
            if self._current_name == robot_name:
                return
            self.get_logger().info(f"[AI] 추론 대상: {self._current_name} → {robot_name}")
            self._current_name = robot_name
            self.prev_msg      = None
            global_tracker.reset()
            self.fsm.reset()

        if self._follower_node is not None:
            self._follower_node.on_start(robot_name)

    def _stop_inference(self):
        with self.lock:
            self.get_logger().info(f"[AI] 추론 중단: {self._current_name}")
            self._current_name = None
            self.prev_msg      = None
            global_tracker.reset()
            self.fsm.reset()


    # ── 추론 콜백 ──────────────────────────────────────────────

    def _on_frame(self,robot_name:str, ros_msg: CompressedImage):
        # current_name 필터: 발행 중인 로봇 프레임만 처리
        with self.lock:
            if self._current_name != robot_name:
                return

        frame = cv2.imdecode(
            np.frombuffer(ros_msg.data, np.uint8), cv2.IMREAD_COLOR
        )
        if frame is None:
            return

        # ── 제스처 인식 ────────────────────────────────────────
        event, g_dbg = get_gesture(frame)
        self.fsm.dispatch(event)

        changed = self.fsm.did_change()
        if changed and self.fsm.state == State.FOLLOW:
            global_tracker.reset()

        t_dbg = None
        cmd   = None

        # ── 타겟 추적 ──────────────────────────────────────────
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

        # ── 중복 필터 후 FollowerNode 직접 호출 ───────────────
        if cmd is not None:
            is_follow = isinstance(cmd, str) and cmd.startswith("FOLLOW")
            is_lost   = cmd == "LOST"
            if is_follow or is_lost or cmd != self.prev_msg:
                self.prev_msg = cmd
                if self._follower_node is not None:
                    self._follower_node.on_udp_message(robot_name, cmd)

        # ── 디버그 발행 (구독자 있을 때만) ────────────────────
        pub = self.result_pubs.get(robot_name)
        if pub is None or pub.get_subscription_count() == 0:
            return
                
        annotated = draw_visualizer(
            frame.copy(),       # 원본 frame 보존
            self.fsm.state,
            g_dbg,
            t_dbg
        )

        # annotated numpy → JPEG bytes → CompressedImage
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
    follow_node = FollowerNode(
        on_end_callback=lambda robot_name: ai_node._stop_inference()
    )
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