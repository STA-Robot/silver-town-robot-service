#robot_comm.py
import socket
import atexit

pi_ip = "192.168.4.2"
pi_port = 9998

send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def set_target(ip: str, port: int):
    global pi_ip, pi_port
    pi_ip = ip
    pi_port = port
    
def send_command(msg: str):
    try:
        send_sock.sendto(msg.encode(), (pi_ip, pi_port))
        print("[SEND]", msg)

    except Exception as e:
        print(f"[comm ERROR] {e}")

def _cleanup():
    print("[Socket] closing...")
    send_sock.close()

atexit.register(_cleanup)#정상 종료에만 작동