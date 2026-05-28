# AIController.py
import socket
import cv2
import numpy as np

from stateContoller import StateController, State, Event
from aicore.gestureRecognizer import get_gesture
from aicore.targetTracker     import get_person_target, TrackDebugInfo, tracker as global_tracker
from visualizer               import draw
from comm                     import send_command

#  UDP 설정 
LISTEN_IP   = "0.0.0.0"
LISTEN_PORT = 9999

recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
recv_sock.bind((LISTEN_IP, LISTEN_PORT))
recv_sock.settimeout(3.0)

fsm      = StateController()
prev_msg = None  # 직전 전송 메시지 추적 (중복 전송 방지)

# 메인 루프
while True:
    try:
        frame_bytes, addr = recv_sock.recvfrom(65507)
        frame = cv2.imdecode(np.frombuffer(frame_bytes, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            continue

        # 제스처 인식
        event, g_dbg = get_gesture(frame)

        # FSM 상태 전환 (제스처 이벤트)
        fsm.dispatch(event)

        # FOLLOW 진입 시 트래커 완전 초기화
        if fsm.did_change() and fsm.state == State.FOLLOW:
            global_tracker.reset()

        # 상태별 처리
        t_dbg   = TrackDebugInfo()
        cmd     = None  

        if fsm.state in (State.FOLLOW, State.LOST):
            # LOST 상태에서도 감지 시도 — 재발견 가능성 있음
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
                # 정상 감지: "FOLLOW,cx,cy,h,id"
                if fsm.state == State.LOST:
                    fsm.dispatch(Event.FOLLOW)  # 재발견 → FSM 복귀
                cmd = msg      # 항상 전송

        else:
            # STOP / END 상태 — 전환 시 1회만 전송
            if fsm.did_change():
                cmd = fsm.state

        # 전송 판단 
        if cmd is not None:
            is_follow = cmd.startswith("FOLLOW")

            if is_follow:
                send_command(cmd)
                prev_msg = cmd  
            else:
                # STOP / LOST / END — 이전과 같으면 전송 생략
                if cmd != prev_msg:
                    send_command(cmd)
                    prev_msg = cmd
                else:
                    pass  

        # 가시화
        frame = draw(frame, fsm.state, g_dbg, t_dbg)
        cv2.imshow("AI_SERVER", frame)

    except socket.timeout:
        print("[WAIT] frame 없음")
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}")

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

recv_sock.close()
cv2.destroyAllWindows()