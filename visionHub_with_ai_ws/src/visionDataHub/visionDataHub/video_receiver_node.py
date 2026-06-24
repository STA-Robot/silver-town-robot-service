import socket
import threading
import time
import json
import yaml
import os

from ament_index_python.packages import get_package_share_directory
from robot_active_msgs.msg import RobotActive
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String


class VideoReceiverNode(Node):

    def __init__(self):
        super().__init__('video_receiver_node')

        self.declare_parameter('server_ip', '0.0.0.0')
        self.declare_parameter('video_port', 9999)
        self.bind_ip = self.get_parameter('server_ip').value
        self.port    = self.get_parameter('video_port').value

        config_path = os.path.join(
            get_package_share_directory('visionDataHub'),
            'config', 'video_config.yaml'
        )
        with open(config_path) as f:
            cfg = yaml.safe_load(f)

        self.robots: dict[str, dict] = {
            r["robot_name"]: {
                "robot_ip":   r["robot_ip"],
                "robot_port": r["robot_port"],  # 버그수정: 중복 키 제거
            }
            for r in cfg["robots"]
        }

        self.lock = threading.Lock()
        self.last_recv_time: dict[str, float] = {n: 0.0 for n in self.robots}
        self.online_robots:  dict[str, str]   = {}

        # 발행 게이트: GUI 요청 / Follow 요청 각각 관리
        self._gui_active:    set[str] = set()  # viewer_request ON
        self._follow_active: set[str] = set()  # follow_command start

        self._result_subs: dict[str, object] = {}
        self._result_cache: dict[str, bytes] = {}  # 최신 result 프레임

        # ── 퍼블리셔 ──────────────────────────────────────────
        self.image_pubs: dict[str, object] = {
            name: self.create_publisher(
                CompressedImage, f'/{name}/image/compressed', 10
            )
            for name in self.robots
        }

        self.viewer_pubs: dict[str, object] = {
            name: self.create_publisher(
                CompressedImage, f'/{name}/viewer/compressed', 10
            )
            for name in self.robots
        }

        self.status_pub = self.create_publisher(RobotActive, '/robot_status', 10)

        # ── 구독 ──────────────────────────────────────────────
        # GUI 보기 요청: "pinky1:on" / "pinky1:off"
        self.create_subscription(RobotActive, '/viewer_request', self._on_viewer_request, 10)
        # Follow 요청: {"robot_name":"pinky1","command":"start"/"stop"}
        self.create_subscription(String, '/follow_command', self._on_follow_command,  10)

        # /pinky1/follow_event, /pinky2/follow_event
        for robot_name in self.robots:
            self.create_subscription(String,f'/{robot_name}/follow_event',self._make_follow_event_cb(robot_name),10)

        # ── UDP 수신 스레드 ────────────────────────────────────
        self._running = True
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

        self.get_logger().info(f"[VideoReceiverNode] 수신 시작 — {self.bind_ip}:{self.port}")

    # ── 발행 대상 판단 ────────────────────────────────────────

    def _should_publish(self, robot_name: str) -> bool:
        """GUI 요청 OR Follow 요청이 있는 온라인 로봇만 발행"""
        return robot_name in (self._gui_active | self._follow_active)

    # ── /viewer_request 콜백 ─────────────────────────────────
    # MonitorNode(pyqt_monitor) → "pinky1:on" / "pinky1:off"

    def _on_viewer_request(self, msg: RobotActive):
        try:
            robot_name = msg.name
            action = msg.action
            if robot_name not in self.robots:
                return
            if action == "on":
                self._gui_active.add(robot_name)
                if robot_name in self._follow_active:
                    self._subscribe_result(robot_name)
                else:
                # raw UDP 영상 발행 (일반)
                    self._unsubscribe_result(robot_name)
                self.get_logger().info(f"[Viewer] {robot_name} 활성화")
            elif action == "off":
                self._gui_active.discard(robot_name)
                self._unsubscribe_result(robot_name)
                with self.lock:
                    self._result_cache.pop(robot_name, None)
                self.get_logger().info(f"[Viewer] {robot_name} 비활성화")
        except Exception as e:
            self.get_logger().warn(f"[viewer_request 파싱 오류] {e}")

    # ── /follow_command 콜백 ──────────────────────────────────
    # pinky_drive_manager → {"robot_name":"pinky1","command":"start"/"stop"}

    def _on_follow_command(self, msg: String):
        try:
            data       = json.loads(msg.data)
            robot_name = data["robot"]
            command    = data["command"]  # "start" | "stop"

            if robot_name not in self.robots:
                self.get_logger().warn(f"[follow_command] 미등록 로봇: {robot_name}")
                return

            if command == "start":
                self._follow_active.add(robot_name)
                if robot_name in self._gui_active:
                    self._subscribe_result(robot_name)
                self.get_logger().info(f"[Follow] {robot_name} 영상 발행 시작")

        except Exception as e:
            self.get_logger().warn(f"[follow_command 파싱 오류] {e}")

    def _make_follow_event_cb(self, robot_name: str):
        def cb(msg: String):
            if msg.data not in ("done", "stop"):
                return
            self._follow_active.discard(robot_name)
            with self.lock:
                self._result_cache.pop(robot_name, None)
            # view 중이면 result 구독 해제 → raw로 자동 전환
            if robot_name in self._gui_active:
                self._unsubscribe_result(robot_name)
                self.get_logger().info(f"[Follow] {robot_name} 종료 → raw 전환")
            else:
                self.get_logger().info(f"[Follow] {robot_name} 종료")
        return cb

     # ── result 구독/해제 ──────────────────────────────────────

    def _subscribe_result(self, robot_name: str):
        if robot_name in self._result_subs:
            return

        def make_cb(name):
            def cb(msg: CompressedImage):
                # result 프레임 캐시
                with self.lock:
                    self._result_cache[name] = bytes(msg.data)
            return cb

        topic = f'/{robot_name}/result/compressed'
        sub = self.create_subscription(
            CompressedImage, topic, make_cb(robot_name), 10
        )
        self._result_subs[robot_name] = sub
        self.get_logger().info(f"[VideoReceiver] result 구독: {topic}")

    def _unsubscribe_result(self, robot_name: str):
        sub = self._result_subs.pop(robot_name, None)
        if sub:
            self.destroy_subscription(sub)

    # ── 상태 발행 ─────────────────────────────────────────────

    def _publish_status(self, robot_name: str, robot_ip: str, online: bool):
        msg = RobotActive()
        msg.name = robot_name
        msg.ip = robot_ip
        msg.online = online
        self.status_pub.publish(msg)

    def _publish_viewer(self, robot_name: str, jpeg: bytes):
        if robot_name not in self._gui_active:
            return

        pub = self.viewer_pubs.get(robot_name)
        if pub is None or pub.get_subscription_count() == 0:
            return

        # follow 중이고 result 캐시 있으면 result 발행
        with self.lock:
            result_frame = self._result_cache.get(robot_name)

        use_result = (robot_name in self._follow_active) and (result_frame is not None)
        payload    = result_frame if use_result else jpeg

        ros_msg = CompressedImage()
        ros_msg.header.stamp = self.get_clock().now().to_msg()
        ros_msg.format = "jpeg"
        ros_msg.data   = payload
        pub.publish(ros_msg)
        self.get_logger().debug(
            f"[Viewer] {robot_name} → {'result' if use_result else 'raw'}"
        )

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

                if b"|" not in data[:64]:
                    continue

                header, jpeg = data.split(b"|", 1) #jpeg에 | 포함되면 깨짐
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
                    self.robots[robot_name]["robot_ip"] = robot_ip
                    self.online_robots[robot_name]      = robot_ip

                if not was_online:
                    self._publish_status(robot_name, robot_ip, True)
                    self.get_logger().info(f"[온라인] {robot_name} ({robot_ip})")
                elif ip_changed:
                    self._publish_status(robot_name, robot_ip, True)
                    self.get_logger().info(f"[IP변경] {robot_name} {prev_ip} → {robot_ip}")

   
                # AI용 raw 발행 (follow_active 로봇만)
                if robot_name in self._follow_active:
                    pub = self.image_pubs.get(robot_name)
                    if pub and pub.get_subscription_count() > 0:
                        ros_msg = CompressedImage()
                        ros_msg.header.stamp = self.get_clock().now().to_msg()
                        ros_msg.format = "jpeg"
                        ros_msg.data   = bytes(jpeg)
                        pub.publish(ros_msg)

                # viewer용 발행 (gui_active 로봇만, result/raw 판단 포함)
                self._publish_viewer(robot_name, bytes(jpeg))

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
            if now - recv_copy.get(robot_name, 0.0) > 2.0:
                with self.lock:
                    self.online_robots.pop(robot_name, None)
                # 오프라인 시 발행 active에서도 제거
                self._gui_active.discard(robot_name)
                self._follow_active.discard(robot_name)
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