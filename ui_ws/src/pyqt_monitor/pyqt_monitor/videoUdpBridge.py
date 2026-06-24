import struct
import socket

CHUNK_SIZE = 60000

class VideoUdpBridge:

    def __init__(self, unity_port: int = 9100):  # IP 없이 생성
        self._addr     = None  # 연결 전까지 None
        self._port     = unity_port
        self._sock     = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._frame_id = 0

    def set_unity_ip(self, ip: str):
        self._addr = (ip, self._port)
        print(f"[VideoUDP] Unity IP 설정: {ip}")

    def send(self, robot_name: str, jpeg_bytes: bytes):
        header = f"{robot_name}|".encode()
        packet = header + jpeg_bytes
        if len(packet) < 65507:
            self._sock.sendto(packet, self._addr)
            