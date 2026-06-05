# videoReceiver.py
import socket
import threading
import time
import cv2
import numpy as np
import yaml


class VideoReceiver:
    #송신자 IP로 어느 로봇인지 식별 → latest_frames 딕셔너리로 관리.
    def __init__(self, config_path="config/config.yaml"):
        with open(config_path) as f:
            cfg = yaml.safe_load(f)

        server_cfg   = cfg["server"]
        self.port    = server_cfg["video_port"]
        self.bind_ip = server_cfg["ip"]

        # 등록된 로봇 IP 목록 (허용 목록)
        self.robot_map = {
            r["robot_ip"]: r["robot_name"] for r in cfg["robots"]
        }  # {"192.168.1.10": "robot_1", ...}

        # 최신 프레임 저장 {robot_ip: {"frame": np.ndarray, "time": float}}
        self.latest_frames = {ip: {"frame": None, "time": 0.0}
                              for ip in self.robot_map}
        self.lock = threading.Lock()

        self.running = True
        self.thread  = threading.Thread(target=self._recv_loop, daemon=True)
        self.thread.start()
        print(f"[VideoReceiver] 수신 시작 — port={self.port}")

    def _recv_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.bind_ip, self.port))
        sock.settimeout(1.0)

        while self.running:
            try:
                data, addr = sock.recvfrom(65507)
                robot_ip   = addr[0]

                # 등록되지 않은 IP 무시
                if robot_ip not in self.robot_map:
                    continue

                frame = cv2.imdecode(
                    np.frombuffer(data, np.uint8),
                    cv2.IMREAD_COLOR
                )
                if frame is None:
                    continue

                with self.lock:
                    self.latest_frames[robot_ip]["frame"] = frame
                    self.latest_frames[robot_ip]["time"]  = time.time()

            except socket.timeout:
                continue
            except Exception as e:
                print(f"[VideoReceiver ERROR] {e}")

        sock.close()

    def get_frame(self, robot_ip: str):
        with self.lock:
            entry = self.latest_frames.get(robot_ip)
            if entry:
                return entry["frame"]
        return None

    def is_timeout(self, robot_ip: str, timeout=2.0) -> bool:
        with self.lock:
            entry = self.latest_frames.get(robot_ip)
            if entry:
                return (time.time() - entry["time"]) > timeout
        return True

    def get_robot_id(self, robot_ip: str) -> str:
        return self.robot_map.get(robot_ip, "unknown")

    def close(self):
        self.running = False
        if self.thread.is_alive():
            self.thread.join(timeout=1.0)