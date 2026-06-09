
import socket
import threading
import time
import json

import yaml
import os
from ament_index_python.packages import get_package_share_directory

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String



class VideoReceiverNode(Node):

    def __init__(self):
        super().__init__('video_receiver_node')

        # ── config 로드 ────────────────────────────────────────
        self.declare_parameter('server_ip', '0.0.0.0')
        self.declare_parameter('video_port', 9999)
        self.bind_ip = self.get_parameter('server_ip').value
        self.port = self.get_parameter('video_port').value

        config_path = os.path.join(
                    get_package_share_directory('common_video'),
                    'config',
                    'video_config.yaml'
                )

        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        self.robot_map = {r['robot_ip']: r['robot_name'] for r in cfg['robots']}
        # ── 상태 ──────────────────────────────────────────────
        self.lock   = threading.Lock()

         # 최신 수신 시간 저장 (타임아웃 체크용)
        self.last_recv_time: dict[str, float] = {
            ip: 0.0 for ip in self.robot_map
        }

        # 현재 발행 활성화된 로봇 IP 집합
        # GUI 요청 / AI 요청 각각 별도 set → 합집합이 실제 active
        self._gui_active: set[str] = set()
        self._ai_active:  set[str] = set()

        # ── ROS2 퍼블리셔 (ip별) ──────────────────────────────
        # 토픽명: /192_168_1_10/image_raw  (점→언더스코어)
        self.image_pubs: dict[str, object] = {
            ip: self.create_publisher(
                CompressedImage,
                f'/robot_{ip.replace(".", "_")}/image/compressed',
                10
            )
            for ip in self.robot_map
        }

        # ── ROS2 구독 ─────────────────────────────────────────
        # GUI 보기 버튼 요청
        self.create_subscription(
            String, '/viewer_request', self._on_viewer_request, 10
        )
        # AI 추론 대상 (TaskManager)
        self.create_subscription(
            String, '/ai_target', self._on_ai_target, 10
        )

        # ── UDP 수신 스레드 ────────────────────────────────────
        self._running = True
        self._recv_thread = threading.Thread(
            target=self._recv_loop, daemon=True
        )
        self._recv_thread.start()

        self.get_logger().info(
            f"[VideoReceiverNode] 수신 시작 — {self.bind_ip}:{self.port}"
        )

    # ── 활성 로봇 set ─────────────────────────────────────────

    def _active_robots(self) -> set[str]:
        return self._gui_active | self._ai_active

    # ── ROS2 콜백 ─────────────────────────────────────────────

    def _on_viewer_request(self, msg: String):
    #보기버튼 → "192.168.1.10:on" or "192.168.1.10:off"
        try:
            robot_ip, action = msg.data.split(":")
            if robot_ip not in self.robot_map:
                return
            if action == "on":
                self._gui_active.add(robot_ip)
                self.get_logger().info(f"[Viewer] {robot_ip} 활성화")
            elif action == "off":
                self._gui_active.discard(robot_ip)
                self.get_logger().info(f"[Viewer] {robot_ip} 비활성화")
        except Exception as e:
            self.get_logger().warn(f"[viewer_request 파싱 오류] {e}")

    def _on_ai_target(self, msg: String):
 
        try:
            data     = json.loads(msg.data)
            robot_ip = data["ip"]
            active   = data.get("active", True)

            if robot_ip not in self.robot_map:
                return

            if active:
                self._ai_active.add(robot_ip)
                self.get_logger().info(f"[AI] {robot_ip} 활성화")
            else:
                self._ai_active.discard(robot_ip)
                self.get_logger().info(f"[AI] {robot_ip} 비활성화")

        except Exception as e:
            self.get_logger().warn(f"[ai_target 파싱 오류] {e}")

    # ── UDP 수신 루프 ─────────────────────────────────────────

    def _recv_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.bind_ip, self.port))
        sock.settimeout(1.0)

        while self._running:
            try:
                data, addr = sock.recvfrom(65507)
                robot_ip   = addr[0]

                if robot_ip not in self.robot_map:
                    continue

                # 수신 시간 갱신
                with self.lock:
                    self.last_recv_time[robot_ip] = time.time()
 
                # active + 구독자 있을 때만 발행
                if robot_ip not in self._active_robots():
                    continue
 
                pub = self.image_pubs[robot_ip]
                if pub.get_subscription_count() == 0:
                    continue
 
                # UDP JPEG 바이트 → CompressedImage 그대로 실음 (변환 없음)
                ros_msg          = CompressedImage()
                ros_msg.header.stamp = self.get_clock().now().to_msg() #타임 스탬프
                ros_msg.format   = "jpeg"#명시적으로 표시 
                ros_msg.data     = bytes(data)  
                pub.publish(ros_msg)
            except socket.timeout:
                continue
            except Exception as e:
                self.get_logger().error(f"[recv_loop] {e}")

        sock.close()

    # ── 유틸 ──────────────────────────────────────────────────

    def is_timeout(self, robot_ip: str, timeout=2.0) -> bool:
        with self.lock:
            return (time.time() - self.last_recv_time.get(robot_ip, 0.0)) > timeout

    def destroy_node(self):
        self._running = False
        self._recv_thread.join(timeout=1.0)
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = VideoReceiverNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()