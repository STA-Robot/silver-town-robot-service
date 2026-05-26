import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    package_share = get_package_share_directory("pinky_task_orchestrator")
    default_config = os.path.join(
        package_share,
        "config",
        "task_orchestrator.yaml",
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument("config_file", default_value=default_config),
            DeclareLaunchArgument("log_level", default_value="info"),
            Node(
                package="pinky_task_orchestrator",
                executable="pinky_task_orchestrator",
                name="pinky_task_orchestrator",
                output="screen",
                arguments=[
                    "--config-file",
                    LaunchConfiguration("config_file"),
                    "--ros-args",
                    "--log-level",
                    LaunchConfiguration("log_level"),
                ],
            ),
        ]
    )
