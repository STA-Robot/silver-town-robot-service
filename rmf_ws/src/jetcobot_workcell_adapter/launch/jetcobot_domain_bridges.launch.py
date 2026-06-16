import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    package_share = get_package_share_directory("jetcobot_workcell_adapter")
    default_jetcobot1_config = os.path.join(
        package_share,
        "config",
        "jetcobot1_domain_bridge.yaml",
    )

    jetcobot1_config = LaunchConfiguration("jetcobot1_config")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "jetcobot1_config",
                default_value=default_jetcobot1_config,
            ),
            Node(
                package="domain_bridge",
                executable="domain_bridge",
                name="jetcobot1_domain_bridge",
                output="screen",
                arguments=[jetcobot1_config],
            ),
        ]
    )
