import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
import socket
import threading

class Follower(Node):
    def __init__(self):
        super().__init__('follower')
        self.pub = self.create_publisher(Twist, '/cmd_vel', 10)# 어떤 pinky인지 알려면?

        # UDP 수신 소켓
        self.recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.recv_sock.bind(("0.0.0.0", 9998))
        self.recv_sock.settimeout(1.0)

        # 공유 변수
        self.latest_msg = None
        self.lock = threading.Lock()

        # 백그라운드 수신 스레드
        self.recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self.recv_thread.start()

        self.get_logger().info("UDP 수신 대기 중... 포트 9998")

        # ── 각속도 P 제어 ──────────────────────────
        self.ANGULAR_GAIN   = 0.0015   # ↓ 0.002 → 0.0015 (급회전 방지)
        self.DEAD_ZONE      = 20       # ↑ 5 → 20px (작은 떨림 무시)
        self.MAX_ANGULAR    = 0.20     # 신규: 최대 회전속도 제한

        # ── 선속도 P 제어 (I제어 → P제어로 교체) ───
        self.Kp             = 1.0      # P gain
        self.MAX_SPEED      = 0.15     # ↓ 0.3 → 0.15 (좁은 공간)
        self.MIN_SPEED      = 0.05     # 신규: 최소 전진속도
        self.TARGET_H_RATIO = 0.80     # ↑ 0.55 → 0.85 (더 가까이 따라붙기)20cm
        self.H_DEAD_ZONE    = 0.04    # 신규: ±3% 이내면 정지

        self.FRAME_WIDTH    = 640
        self.FRAME_HEIGHT   = 480

        # 재매칭용 마지막 위치
        self.last_cx        = None
        self.last_cy        = None
        self.target_id      = None

        self.timer = self.create_timer(0.05, self.loop)

    def _recv_loop(self):
        self.get_logger().info("UDP 수신 시작")
        while True:
            try:
                data, _ = self.recv_sock.recvfrom(1024)#pinky에 id값으로 구분
                with self.lock:
                    self.latest_msg = data.decode()
            except socket.timeout:
                continue
            except Exception as e:
                self.get_logger().error(f"UDP 수신 에러: {e}")
                break

    def loop(self):
        with self.lock:
            msg = self.latest_msg
            self.latest_msg = None

        if msg is None:
            return

        twist = Twist()

        if msg == "None":
            self.get_logger().warn("감지 없음 - 정지")
            twist.linear.x  = 0.0
            twist.angular.z = 0.0

        else:
            try:
                parts = msg.split(",")
                cx, cy, h, track_id = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
            except (ValueError, IndexError):
                self.get_logger().error(f"파싱 실패: {msg}")
                return

            # 최초 타겟 지정
            if self.target_id is None:
                self.target_id = track_id
                self.get_logger().info(f"[타겟 고정] ID={track_id}")

            # ID 재매칭
            if track_id != self.target_id:
                if self.last_cx is not None:
                    dist = ((cx - self.last_cx)**2 + (cy - self.last_cy)**2) ** 0.5
                    if dist < 150:
                        self.get_logger().info(f"[재매칭] ID {self.target_id} → {track_id} (거리={dist:.1f}px)")
                        self.target_id = track_id
                    else:
                        self.get_logger().warn(f"[다른 사람] ID={track_id} 무시 (거리={dist:.1f}px)")
                        return
                else:
                    return

            self.last_cx = cx
            self.last_cy = cy

            # ── 각속도 P 제어 ──────────────────────
            error_x = cx - (self.FRAME_WIDTH / 2)

            if abs(error_x) > self.DEAD_ZONE:
                raw_angular     = -error_x * self.ANGULAR_GAIN
                twist.angular.z = max(-self.MAX_ANGULAR, min(self.MAX_ANGULAR, raw_angular))
            else:
                twist.angular.z = 0.0

            # ── 선속도 P 제어 ──────────────────────
            h_ratio = h / self.FRAME_HEIGHT
            error_h = self.TARGET_H_RATIO - h_ratio

            if error_h > self.H_DEAD_ZONE:          # 멀면 전진
                raw_speed      = self.Kp * error_h
                twist.linear.x = max(self.MIN_SPEED, min(raw_speed, self.MAX_SPEED))
            elif error_h < -self.H_DEAD_ZONE:        # 너무 가까우면 후진
                raw_speed      = self.Kp * error_h
                twist.linear.x = max(-self.MAX_SPEED, min(raw_speed, -self.MIN_SPEED))
            else:                                    # 적정거리면 정지
                twist.linear.x = 0.0

            self.get_logger().info(
                f"v_04_ID={track_id} cx={cx} err_x={error_x:.0f} "
                f"h_ratio={h_ratio:.2f} err_h={error_h:.2f} "
                f"lin={twist.linear.x:.2f} ang={twist.angular.z:.3f}"
            )

        self.pub.publish(twist)

    def destroy_node(self):
        self.recv_sock.close()
        super().destroy_node()

def main(args=None):
    rclpy.init(args=args)
    node = Follower()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == "__main__":
    main()