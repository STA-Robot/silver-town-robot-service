import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node


def generate_launch_description():
    package_share = get_package_share_directory("jetcobot_workcell_adapter")
    default_config = os.path.join(
        package_share,
        "config",
        "workcell_adapter.yaml",
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument("config_file", default_value=default_config),
            DeclareLaunchArgument("log_level", default_value="info"),
            Node(
                package="jetcobot_workcell_adapter",
                executable="workcell_adapter",
                name="jetcobot_workcell_adapter",
                output="screen",
                arguments=[
                    "--config-file",
                    LaunchConfiguration("config_file"),
                    "--ros-args",
                    "--log-level",
                    PythonExpression(
                        [
                            "'jetcobot_workcell_adapter:=' + '",
                            LaunchConfiguration("log_level"),
                            "'",
                        ]
                    ),
                ],
            ),
        ]
    )
