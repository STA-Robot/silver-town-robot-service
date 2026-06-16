import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node


def generate_launch_description():
    package_share = get_package_share_directory("task_orchestrator")
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
                package="task_orchestrator",
                executable="task_orchestrator",
                name="task_orchestrator",
                output="screen",
                arguments=[
                    "--config-file",
                    LaunchConfiguration("config_file"),
                    "--ros-args",
                    "--log-level",
                    PythonExpression(
                        [
                            "'task_orchestrator:=' + '",
                            LaunchConfiguration("log_level"),
                            "'",
                        ]
                    ),
                ],
            ),
        ]
    )
