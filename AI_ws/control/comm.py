import socket
import atexit

PI_IP = "192.168.4.2"
PI_PORT = 9998

send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def send_command(msg: str):
    try:
        send_sock.sendto(msg.encode(), (PI_IP, PI_PORT))
        print("[SEND]", msg)

    except Exception as e:
        print(f"[comm ERROR] {e}")

def _cleanup():
    print("[Socket] closing...")
    send_sock.close()

atexit.register(_cleanup)#정상 종료에만 작동