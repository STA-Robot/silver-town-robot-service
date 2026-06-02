import cv2
import os
import socket
import numpy as np

LISTEN_IP   = "0.0.0.0"
LISTEN_PORT = 9999

recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
recv_sock.bind((LISTEN_IP, LISTEN_PORT))
recv_sock.settimeout(3.0)

save_dir = "captured_frames"
os.makedirs(save_dir, exist_ok=True)

frame_count = 0
save_count  = 0

print(f"UDP 수신 대기 중... ({LISTEN_IP}:{LISTEN_PORT})")
print("스페이스바: 저장 / q: 종료")

while True:
    try:
        frame_bytes, addr = recv_sock.recvfrom(65507)
        frame = cv2.imdecode(np.frombuffer(frame_bytes, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            continue

        # 저장 카운트 화면에 표시
        cv2.putText(frame, f"saved: {save_count}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        cv2.imshow("capture", frame)
        key = cv2.waitKey(1) & 0xFF

        if key == ord(' '):
            path = os.path.join(save_dir, f"frame_{save_count:04d}.jpg")
            cv2.imwrite(path, frame)
            print(f"저장: {path}")
            save_count += 1

        elif key == ord('q'):
            break

        frame_count += 1

    except socket.timeout:
        print("로봇 카메라 수신 대기 중...")
        # q 눌러도 종료 가능하도록
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}")
        break

recv_sock.close()
cv2.destroyAllWindows()
print(f"총 {save_count}장 저장 완료")