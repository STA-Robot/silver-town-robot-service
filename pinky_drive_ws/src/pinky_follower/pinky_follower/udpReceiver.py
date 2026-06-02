import socket
import threading
import time

from pinky_follower.loggerMixin import LoggerMixin


class UDPReceiver(LoggerMixin):
    def __init__(self, ip="0.0.0.0", port=9998, logger=None, on_message=None):
        self.set_logger(logger)
        self.on_message = on_message

        self.ip   = ip
        self.port = port

        self.last_recv_time = time.time()
        self.lock           = threading.Lock()
        self.running        = False
        self.thread         = None

        self._start_socket()
        self._start_thread()


    def _start_socket(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.ip, self.port))
        self.sock.settimeout(1.0)

    def _start_thread(self):
        self.running = True
        self.thread  = threading.Thread(target=self._recv_loop, daemon=True)
        self.thread.start()

    def _recv_loop(self):
        self._log_info("UDP 수신 시작")
        while self.running:
            try:
                data, _ = self.sock.recvfrom(1024)
                msg     = data.decode().strip()

                with self.lock:
                    self.last_recv_time = time.time()

                if self.on_message and msg:
                    self.on_message(msg)

            except socket.timeout:
                continue
            except Exception as e:
                if self.running:  # close() 호출로 인한 에러는 무시
                    self._log_error(f"[UDP ERROR] {e}")
                break

    def is_timeout(self, timeout=1.0):
        with self.lock:
            return (time.time() - self.last_recv_time) > timeout

    def reset(self):
        self._log_info("UDP reset 시작")

        # 기존 정리
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)

        # last_recv_time 리셋 (timeout 오탐 방지)
        with self.lock:
            self.last_recv_time = time.time()

        # 재시작
        self._start_socket()
        self._start_thread()
        self._log_info("UDP reset 완료")

    def close(self):
        self._log_info("UDP 종료")
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass