import socket

PI_IP = "192.168.4.1"
PI_PORT = 9998

send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def send_command(msg: str):
    send_sock.sendto(msg.encode(), (PI_IP, PI_PORT))
    print("[SEND]", msg)