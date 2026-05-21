import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    package_share = get_package_share_directory("pinky_rmf_adapter")
    default_pinky1_config = os.path.join(
        package_share, "config", "pinky1_domain_bridge.yaml"
    )
    default_pinky2_config = os.path.join(
        package_share, "config", "pinky2_domain_bridge.yaml"
    )

    pinky1_config = LaunchConfiguration("pinky1_config")
    pinky2_config = LaunchConfiguration("pinky2_config")

    return LaunchDescription(
        [
            DeclareLaunchArgument("pinky1_config", default_value=default_pinky1_config),
            DeclareLaunchArgument("pinky2_config", default_value=default_pinky2_config),
            Node(
                package="domain_bridge",
                executable="domain_bridge",
                name="pinky1_domain_bridge",
                output="screen",
                arguments=[pinky1_config],
            ),
            Node(
                package="domain_bridge",
                executable="domain_bridge",
                name="pinky2_domain_bridge",
                output="screen",
                arguments=[pinky2_config],
            ),
        ]
    )
