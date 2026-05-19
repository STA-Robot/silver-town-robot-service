import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _as_bool(value: str) -> bool:
    return value.lower() in ("1", "true", "yes", "on")


def _launch_nodes(context, *args, **kwargs):
    del args, kwargs

    config_file = LaunchConfiguration("config_file").perform(context)
    robot_name = LaunchConfiguration("robot_name").perform(context)
    drive_namespace = LaunchConfiguration("drive_namespace").perform(context)
    legacy_namespace = LaunchConfiguration("namespace").perform(context)
    robot_namespace = LaunchConfiguration("robot_namespace").perform(context)
    rmf_level = LaunchConfiguration("rmf_level").perform(context)
    use_sim_time = LaunchConfiguration("use_sim_time").perform(context)

    if not drive_namespace and legacy_namespace:
        drive_namespace = legacy_namespace
    if not drive_namespace:
        drive_namespace = f"/{robot_name}/drive"

    node_args = ["--config-file", config_file, "--robot-name", robot_name]
    if robot_namespace:
        node_args.extend(["--robot-namespace", robot_namespace])
    if rmf_level:
        node_args.extend(["--rmf-level", rmf_level])

    return [
        Node(
            package="pinky_drive_manager",
            executable="drive_manager_node",
            name="drive_manager",
            namespace=drive_namespace,
            output="screen",
            arguments=node_args,
            parameters=[{"use_sim_time": _as_bool(use_sim_time)}],
        )
    ]


def generate_launch_description():
    package_share = get_package_share_directory("pinky_drive_manager")
    default_config = os.path.join(package_share, "config", "pinky_drive_manager.yaml")

    return LaunchDescription(
        [
            DeclareLaunchArgument("config_file", default_value=default_config),
            DeclareLaunchArgument("robot_name", default_value="pinky1"),
            DeclareLaunchArgument("drive_namespace", default_value=""),
            DeclareLaunchArgument("namespace", default_value=""),
            DeclareLaunchArgument("robot_namespace", default_value=""),
            DeclareLaunchArgument("rmf_level", default_value=""),
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            OpaqueFunction(function=_launch_nodes),
        ]
    )
