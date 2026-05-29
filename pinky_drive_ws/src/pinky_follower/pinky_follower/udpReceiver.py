import socket
import threading
import time

from loggerMixin import LoggerMixin


class UDPReceiver(LoggerMixin):
    def __init__(self, ip="0.0.0.0", port=9998, logger=None, on_message=None):

        # on_message 메시지 도착 즉시 콜백 함수 (str) → None
        self.set_logger(logger)
        self.on_message = on_message

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((ip, port))
        self.sock.settimeout(1.0)

        self.last_recv_time = time.time()
        self.lock           = threading.Lock()

        self.running = True
        self.thread  = threading.Thread(target=self._recv_loop, daemon=True)
        self.thread.start()

    def _recv_loop(self):
        self._log_info("UDP 수신 시작 ")
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
                self._log_error(f"[UDP ERROR] {e}")
                break

    def is_timeout(self, timeout=1.0):
        with self.lock:
            return (time.time() - self.last_recv_time) > timeout

    def close(self):
        self.running = False
        self.sock.close()