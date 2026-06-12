
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
                    get_package_share_directory('visionDataHub'),
                    'config',
                    'video_config.yaml'
                )

        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        self.robots: dict[str, dict] = {
            r["robot_name"]: {
                "robot_ip":   r["robot_ip"],
                "robot_ip": r["robot_port"],
            }
            for r in cfg["robots"]
        }
        # ── 상태 ──────────────────────────────────────────────
        self.lock   = threading.Lock()

         # 최신 수신 시간 저장 (타임아웃 체크용)
        self.last_recv_time: dict[str, float] = {
            name: 0.0 for name in self.robots
        }

        # 현재 온라인 로봇 {robot_name: current_ip}
        self.online_robots: dict[str, str] = {}
        # 현재 발행 활성화된 로봇 IP 집합
        # GUI 요청 / AI 요청 각각 별도 set → 합집합이 실제 active
        self._gui_active: set[str] = set()
        self._ai_active:  set[str] = set()

        # ── ROS2 퍼블리셔 (ip별) ──────────────────────────────
        # 토픽명: /192_168_1_10/image_raw  (점→언더스코어)
        self.image_pubs: dict[str, object] = {
            name: self.create_publisher(
                CompressedImage,
                f'/{name}/image/compressed',
                10
            )
            for name in self.robots
        }
         # 로봇 온/오프라인 상태 퍼블리셔
        self.status_pub = self.create_publisher(String, '/robot_status', 10)

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
        #GUI 보기버튼 → "pinky1:on" or "pinky1:off" 
        try:
            robot_name, action = msg.data.split(":")
            if robot_name not in self.robots:
                return
            if action == "on":
                self._gui_active.add(robot_name)
                self.get_logger().info(f"[Viewer] {robot_name} 활성화")
            elif action == "off":
                self._gui_active.discard(robot_name)
                self.get_logger().info(f"[Viewer] {robot_name} 비활성화")
        except Exception as e:
            self.get_logger().warn(f"[viewer_request 파싱 오류] {e}")

    def _on_ai_target(self, msg: String):
      
        try:
            data       = json.loads(msg.data)
            robot_name = data["robot_name"]
            active     = data.get("active",True)#start일때 True로 end일때 False 보내고 있음
 
            if robot_name not in self.robots:
                return
 
            if active:
                self._ai_active.add(robot_name)
                # 최신 IP 갱신
                with self.lock:
                    self.robots[robot_name]["robot_ip"] = data.get(
                        "robot_ip", self.robots[robot_name]["robot_ip"]
                    )
                self.get_logger().info(f"[AI] {robot_name} 활성화")
            else:
                self._ai_active.discard(robot_name)
                self.get_logger().info(f"[AI] {robot_name} 비활성화")
        except Exception as e:
            self.get_logger().warn(f"[ai_target 파싱 오류] {e}")
            
    def _publish_status(self, robot_name: str, robot_ip: str, online: bool):
            msg = String()
            msg.data = json.dumps({
                "name":   robot_name,
                "ip":     robot_ip,
                "online": online
            })
            self.status_pub.publish(msg)


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

                # 패킷 파싱: "robot_name|jpeg_bytes"
                if b"|" not in data[:20]:
                    continue
 
                header, jpeg = data.split(b"|", 1)
                robot_name   = header.decode().strip()
 
                if robot_name not in self.robots:
                    self.get_logger().warn(f"[미등록 로봇] {robot_name}")
                    continue
 
                now = time.time()

                with self.lock:
                    self.last_recv_time[robot_name] = now
                    was_online = robot_name in self.online_robots
                    prev_ip    = self.online_robots.get(robot_name)
                    ip_changed = was_online and prev_ip != robot_ip
 
                    # 최신 IP 항상 갱신
                    self.robots[robot_name]["robot_ip"]    = robot_ip
                    self.online_robots[robot_name]   = robot_ip
 
                # 온라인 첫 수신 or IP 변경 → status 발행
                if not was_online:
                    self._publish_status(robot_name, robot_ip, True)
                    self.get_logger().info(f"[온라인] {robot_name} ({robot_ip})")
                elif ip_changed:
                    self._publish_status(robot_name, robot_ip, True)
                    self.get_logger().info(
                        f"[IP변경] {robot_name} {prev_ip} → {robot_ip}"
                    )

 
                # active + 구독자 있을 때만 발행
                if robot_name not in self._active_robots():
                    continue
 
                pub = self.image_pubs.get(robot_name)
                if pub is None or pub.get_subscription_count() == 0:
                    continue
 
                # UDP JPEG 바이트 → CompressedImage 그대로 실음 (변환 없음)
                ros_msg          = CompressedImage()
                ros_msg.header.stamp = self.get_clock().now().to_msg() #타임 스탬프
                ros_msg.format   = "jpeg"#명시적으로 표시 
                ros_msg.data     = bytes(jpeg)  
                pub.publish(ros_msg)
            except socket.timeout:
                self._check_offline()
                continue
            except Exception as e:
                self.get_logger().error(f"[recv_loop] {e}")

        sock.close()
    # ── 오프라인 감지 ─────────────────────────────────────────
 
    def _check_offline(self):
        now = time.time()
        with self.lock:
            online_copy = dict(self.online_robots)
            recv_copy   = dict(self.last_recv_time)
 
        for robot_name, current_ip in online_copy.items():
            last = recv_copy.get(robot_name, 0.0)
            if now - last > 2.0:
                with self.lock:
                    self.online_robots.pop(robot_name, None)
                self._publish_status(robot_name, current_ip, False)
                self.get_logger().info(f"[오프라인] {robot_name} ({current_ip})")

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