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

    def send(self, jpeg_bytes: bytes):  # _send → send (ViewerController에서 호출)
        if self._addr is None:  # IP 미설정이면 스킵
            return
        chunks = [jpeg_bytes[i:i + CHUNK_SIZE] for i in range(0, len(jpeg_bytes), CHUNK_SIZE)]
        total  = len(chunks)
        fid    = self._frame_id & 0xFFFFFFFF
        for idx, chunk in enumerate(chunks):
            header = struct.pack('>I H H', fid, idx, total)
            self._sock.sendto(header + chunk, self._addr)
        self._frame_id += 1