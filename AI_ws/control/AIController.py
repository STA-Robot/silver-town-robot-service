# AIController.py
from dataclasses import dataclass
import threading
from typing import Optional
import yaml
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from stateContoller import StateController, State, Event
from aicore.gestureRecognizer import get_gesture,GestureDebugInfo
from aicore.targetTracker import get_person_target, TrackDebugInfo, tracker as global_tracker
from videoReceiv import VideoReceiver
from comm import send_command

# ── 설정 로드 ─────────────────────────────────────────────────
# with open("config.yaml") as f:
#     cfg = yaml.safe_load(f)

# server_cfg   = cfg["server"]
# COMMAND_PORT = server_cfg["command_port"]

# ── VideoReceiver (mainWindow과 공유) ─────────────────────────
video_receiver = VideoReceiver()

@dataclass
class AIDebugInfo:
    state: str
    gesture: Optional[GestureDebugInfo]
    track: Optional[TrackDebugInfo]

# ── 공유 상태 (mainWindow에서 읽어감) ────────────────────────
_active_robot_ip  = None
_latest_debug: Optional[AIDebugInfo] = None
_state_lock       = threading.Lock()

fsm      = StateController()
prev_msg = None

def get_active_robot() -> str:
    """mainWindow에서 현재 추론 대상 IP 조회"""
    with _state_lock:
        return _active_robot_ip

def get_latest_debug() -> Optional[AIDebugInfo]:
    with _state_lock:
        return _latest_debug

def set_active_robot(ip: str):
    """
    TaskManager ROS2 토픽 수신 시 호출.
    추론 대상 로봇 IP 지정 + 상태 초기화.
    """
    global prev_msg
    with _state_lock:
        global _active_robot_ip
        if _active_robot_ip == ip:
            return
        print(f"[AIController] 추론 대상: {_active_robot_ip} → {ip}")
        _active_robot_ip = ip
        prev_msg         = None
        global_tracker.reset()
        fsm.__init__()


# ── TaskManager 토픽 구독 (ROS2) ─────────────────────────────
class AITargetSubscriber(Node):
    def __init__(self):
        super().__init__('ai_controller_node')

        self.current_ip = None

        self.sub = self.create_subscription(
            String, '/ai_target', self._on_target, 10
        )

        self.timer = self.create_timer(0.1, self.process)# 10fps

    def _on_target(self, msg: String):
        robot_ip = msg.data.strip()
        self.current_ip = robot_ip  
        set_active_robot(robot_ip)

    
    def process(self):
        global prev_msg, _latest_debug

        if self.current_ip is None:
            return

        if video_receiver.is_timeout(self.current_ip):
            return

        frame = video_receiver.get_frame(self.current_ip)
        if frame is None:
            return

        # 기존 AI 로직 그대로
        event, g_dbg = get_gesture(frame)
        fsm.dispatch(event)

        if fsm.did_change() and fsm.state == State.FOLLOW:
            global_tracker.reset()

        t_dbg = TrackDebugInfo()
        cmd   = None

        if fsm.state in (State.FOLLOW, State.LOST):
            msg, t_dbg = get_person_target(frame)

            if msg == "END":
                fsm.dispatch(Event.END)
                cmd = "END"
            elif msg == "LOST":
                fsm.dispatch(Event.LOST)
                cmd = "LOST"
            elif msg == "STOP":
                cmd = "STOP"
            else:
                if fsm.state == State.LOST:
                    fsm.dispatch(Event.FOLLOW)
                cmd = msg
        else:
            if fsm.did_change():
                cmd = fsm.state

        with _state_lock:
            _latest_debug = AIDebugInfo(
                state=fsm.state,
                gesture=g_dbg,
                track=t_dbg
            )

        if cmd is not None:
            is_follow = isinstance(cmd, str) and cmd.startswith("FOLLOW")

            if is_follow or cmd != prev_msg:
                send_command(cmd)
                prev_msg = cmd

def main(args=None):
    rclpy.init(args=args)
    node = AITargetSubscriber()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()