from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    port = LaunchConfiguration("port")
    baud = LaunchConfiguration("baud")
    speed = LaunchConfiguration("speed")
    gripper_speed = LaunchConfiguration("gripper_speed")
    joint_state_rate = LaunchConfiguration("joint_state_rate")

    return LaunchDescription(
        [
            DeclareLaunchArgument("port", default_value="/dev/ttyJETCOBOT"),
            DeclareLaunchArgument("baud", default_value="1000000"),
            DeclareLaunchArgument("speed", default_value="25"),
            DeclareLaunchArgument("gripper_speed", default_value="80"),
            DeclareLaunchArgument("joint_state_rate", default_value="20.0"),
            Node(
                package="jetcobot_driver",
                executable="trajectory_action_server",
                name="jetcobot_trajectory_driver",
                output="screen",
                parameters=[
                    {
                        "port": port,
                        "baud": baud,
                        "speed": speed,
                        "gripper_speed": gripper_speed,
                        "joint_state_rate": joint_state_rate,
                    }
                ],
            ),
        ]
    )
