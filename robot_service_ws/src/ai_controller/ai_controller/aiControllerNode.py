
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
from ai_controller.aicore.gestureRecognizer import get_gesture, GestureDebugInfo
from ai_controller.aicore.targetTracker import get_person_target, TrackDebugInfo, tracker as global_tracker
from .robot_comm import send_command, set_target
from .visualizer import draw as draw_visualizer


class AIControllerNode(Node):

    def __init__(self):
        super().__init__('ai_controller_node')

        self.lock = threading.Lock()

        # ── 상태 ───────────────────────────────────────────────
        self._current_name:   Optional[str]         = None
        self._image_sub:    Optional[object]      = None
        self.prev_msg:      Optional[str]         = None
        self.fsm = StateController()

        # ── 추론 결과 퍼블리셔 (CompressedImage) ──────────────
        self.result_pub = self.create_publisher(
            CompressedImage, '/ai/image_result', 10
        )

        # ── AI 추론 대상 구독 ──────────────────────────────────
        self.create_subscription(
            String, '/ai_target', self._on_ai_target, 10
        )

        self.get_logger().info("[AIControllerNode] 시작")


    # ── TaskManager 콜백 ───────────────────────────────────────

    def _on_ai_target(self, msg: String):
        try:
            data     = json.loads(msg.data)
            robot_name = data["robot_name"]
            robot_ip = data["robot_ip"]
            port     = int(data["robot_port"])
            active   = data.get("active",True)

            if active:
                self._start_inference(robot_name,robot_ip, port)
            else:
                self._stop_inference()
        except Exception as e:
            self.get_logger().error(f"[ai_target 파싱 오류] {e}")

    def _start_inference(self, robot_name: str,robot_ip: str, port: int):
        with self.lock:
            if self._current_name == robot_name:
                return
            self.get_logger().info(f"[AI] 추론 대상: {self._current_name} → {robot_name}")
            self._destroy_image_sub()
            self._current_name = robot_name
            self.prev_msg    = None
            global_tracker.reset()
            self.fsm.reset()
            set_target(robot_ip, port)

        topic = f'/{robot_name}/image/compressed'
        self._image_sub = self.create_subscription(
            CompressedImage, topic, self._on_frame, 10
        )
        self.get_logger().info(f"[AI] 구독 시작: {topic}")

    def _stop_inference(self):
        with self.lock:
            self.get_logger().info(f"[AI] 추론 중단: {self._current_name}")
            self._destroy_image_sub()
            self._current_name   = None
            self.prev_msg      = None
            global_tracker.reset()
            self.fsm.reset()

    def _destroy_image_sub(self):
        if self._image_sub is not None:
            self.destroy_subscription(self._image_sub)
            self._image_sub = None

    # ── 추론 콜백 ──────────────────────────────────────────────

    def _on_frame(self, ros_msg: CompressedImage):
        # CompressedImage → numpy (imdecode 한 번만)
        frame = cv2.imdecode(
            np.frombuffer(ros_msg.data, np.uint8),
            cv2.IMREAD_COLOR
        )
        if frame is None:
            return

        with self.lock:
            if self._current_name is None:
                return

        # ── AI 로직 ────────────────────────────────────────────
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
                self.fsm.dispatch(Event.END);  cmd = "END"
            elif msg_str == "LOST":
                self.fsm.dispatch(Event.LOST); cmd = "LOST"
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
            if is_follow or cmd != self.prev_msg:
                send_command(cmd)
                self.prev_msg = cmd

        # ── 추론 결과 발행 (GUI 구독 중일 때만) ───────────────
        if self.result_pub.get_subscription_count() == 0:
            return

        # visualizer로 바운딩박스·상태·방향 오버레이
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
        self.result_pub.publish(result_msg)


def main(args=None):
    rclpy.init(args=args)
    node = AIControllerNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()