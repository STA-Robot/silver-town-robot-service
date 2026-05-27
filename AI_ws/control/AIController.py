# AIController.py
import socket
import cv2
import numpy as np

from stateContoller import StateController, State
from aicore.gestureRecognizer import get_gesture
from aicore.targetTracker     import get_person_target, TrackDebugInfo, tracker as global_tracker
from visualizer        import draw
from comm import send_command

# ── UDP 설정 ──────────────────────────────────────────────────
LISTEN_IP   = "192.168.4.2"
LISTEN_PORT = 9999

recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
recv_sock.bind((LISTEN_IP, LISTEN_PORT))
recv_sock.settimeout(3.0)

fsm          = StateController()
prev_state   = fsm.state   # 이전 상태 추적용

# ── 메인 루프 ─────────────────────────────────────────────────
while True:
    try:
        frame_bytes, addr = recv_sock.recvfrom(65507)
        frame = cv2.imdecode(np.frombuffer(frame_bytes, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            continue

        # 1. 제스처 인식
        event, g_dbg = get_gesture(frame)

        # 2. FSM 상태 전환
        fsm.dispatch(event)

        # FOLLOW 진입 시 트래커 완전 초기화
        if fsm.did_change() and fsm.state == State.FOLLOW:
            global_tracker.reset()

        # 3. 상태별 처리
        t_dbg = TrackDebugInfo()

        if fsm.state == State.FOLLOW:
            msg, t_dbg = get_person_target(frame)

            if msg == "LOST":
                #LOST 시 FSM도 END로 전환
                fsm.dispatch("END")
                send_command("END")
            elif msg != "None":
                send_command(f"FOLLOW,{msg}")
            # msg=="None"(일시적 미검출)은 전송 없음

        else:
            # 상태가 바뀐 프레임에서만 명령 1회 전송
            if fsm.did_change():
                send_command(fsm.state)

        prev_state = fsm.state

        # 4. 가시화
        frame = draw(frame, fsm.state, g_dbg, t_dbg)
        cv2.imshow("AI_SERVER", frame)

    except socket.timeout:
        print("[WAIT] frame 없음")
    except Exception as e:
        # 예상 외 예외도 잡아서 서버 유지
        print(f"[ERROR] {type(e).__name__}: {e}")

    # waitKey는 try 밖 — timeout 예외 때도 q 입력 받을 수 있어야 함
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

recv_sock.close()
cv2.destroyAllWindows()