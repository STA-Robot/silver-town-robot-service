"""
RobotPoseSubscriber.py
──────────────────────
config 에 있는 로봇마다 /{robot_name}/pose 토픽을 구독한다.

지원 메시지 타입:
  - geometry_msgs/msg/Pose
  - geometry_msgs/msg/PoseStamped
  - geometry_msgs/msg/PoseWithCovarianceStamped   (AMCL 출력)
  - nav_msgs/msg/Odometry

수신한 pose → quaternion → yaw 변환 후 ControlUI._on_robot_pose() 시그널 emit.
"""

import math
import threading
import rclpy
from rclpy.node import Node

# ── 지원 메시지 타입 import (없으면 skip) ──────────────────────
_SUPPORTED = {}
try:
    from geometry_msgs.msg import Pose as _Pose
    _SUPPORTED["Pose"] = _Pose
except ImportError:
    pass
try:
    from geometry_msgs.msg import PoseStamped as _PS
    _SUPPORTED["PoseStamped"] = _PS
except ImportError:
    pass
try:
    from geometry_msgs.msg import PoseWithCovarianceStamped as _PWCS
    _SUPPORTED["PoseWithCovarianceStamped"] = _PWCS
except ImportError:
    pass
try:
    from nav_msgs.msg import Odometry as _Odom
    _SUPPORTED["Odometry"] = _Odom
except ImportError:
    pass

from PyQt5.QtCore import QObject, pyqtSignal


def _quat_to_yaw(q) -> float:
    """quaternion → yaw (라디안)."""
    siny = 2.0 * (q.w * q.z + q.x * q.y)
    cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.atan2(siny, cosy)


def _extract_pose(msg):
    """
    다양한 메시지 타입에서 (x, y, yaw) 추출.
    Returns None 이면 지원하지 않는 타입.
    """
    t = type(msg).__name__

    if t == "Pose":
        p = msg.position
        return p.x, p.y, _quat_to_yaw(msg.orientation)

    elif t == "PoseStamped":
        p = msg.pose.position
        return p.x, p.y, _quat_to_yaw(msg.pose.orientation)

    elif t == "PoseWithCovarianceStamped":
        p = msg.pose.pose.position
        return p.x, p.y, _quat_to_yaw(msg.pose.pose.orientation)

    elif t == "Odometry":
        p = msg.pose.pose.position
        return p.x, p.y, _quat_to_yaw(msg.pose.pose.orientation)

    return None


class _PoseNode(Node):
    """
    내부 ROS2 Node.
    각 로봇 이름마다 여러 메시지 타입으로 /{name}/pose 구독을 시도한다.
    """

    def __init__(self, robot_names: list, callback):
        super().__init__("robot_pose_subscriber")
        self._cb = callback

        for name in robot_names:
            topic = f"/{name}/pose"
            self._try_subscribe(name, topic)

    def _try_subscribe(self, robot_name: str, topic: str):
        """지원 타입 순서대로 구독 시도 (첫 번째 성공한 타입 사용)."""
        # 우선순위: PoseWithCovarianceStamped > Odometry > PoseStamped > Pose
        priority = [
            "PoseWithCovarianceStamped",
            "Odometry",
            "PoseStamped",
            "Pose",
        ]
        for type_name in priority:
            if type_name not in _SUPPORTED:
                continue
            msg_type = _SUPPORTED[type_name]
            self.create_subscription(
                msg_type,
                topic,
                lambda msg, rn=robot_name: self._on_msg(rn, msg),
                10
            )
            self.get_logger().info(
                f"[PoseSubscriber] {topic} 구독 ({type_name})"
            )
            # 모든 타입 구독 (어느 타입으로 퍼블리시되더라도 수신)
            # break 없이 전부 등록 → 실제 발행되는 타입만 콜백 호출됨

    def _on_msg(self, robot_name: str, msg):
        result = _extract_pose(msg)
        if result:
            self._cb(robot_name, *result)


class RobotPoseSubscriber(QObject):
    """
    QObject 래퍼.
    ControlUI 에서 생성하고, pose_received 시그널로 UI 업데이트.

    사용:
        self.pose_sub = RobotPoseSubscriber(robot_names, self)
        self.pose_sub.pose_received.connect(self._on_robot_pose)
    """

    # (robot_name, world_x, world_y, yaw)
    pose_received = pyqtSignal(str, float, float, float)

    # def __init__(self, robot_names: list, parent=None):
    #     super().__init__(parent)
    #     self._robot_names = robot_names

    #     self._node = _PoseNode(robot_names, self._on_pose)
    #     self._thread = threading.Thread(
    #         target=rclpy.spin, args=(self._node,), daemon=True
    #     )
    #     self._thread.start()

    def _on_pose(self, robot_name: str, x: float, y: float, yaw: float):
        """ROS 스레드 → Qt 메인 스레드로 시그널 emit."""
        self.pose_received.emit(robot_name, x, y, yaw)

    def destroy(self):
        self._node.destroy_node()