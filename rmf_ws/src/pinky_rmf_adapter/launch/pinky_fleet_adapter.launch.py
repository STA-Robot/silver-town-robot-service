import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _as_bool(value: str) -> bool:
    return value.lower() in ("1", "true", "yes", "on")


def _launch_adapter(context, *args, **kwargs):
    del args, kwargs

    cli_args = [
        "--config_file",
        LaunchConfiguration("config_file"),
        "--nav_graph",
        LaunchConfiguration("nav_graph_file"),
        "--server_uri",
        LaunchConfiguration("server_uri"),
    ]

    if _as_bool(LaunchConfiguration("use_sim_time").perform(context)):
        cli_args.append("--use_sim_time")

    return [
        Node(
            package="pinky_rmf_adapter",
            executable="pinky_fleet_adapter",
            output="screen",
            arguments=cli_args,
        )
    ]


def generate_launch_description():
    adapter_share = get_package_share_directory("pinky_rmf_adapter")
    maps_share = get_package_share_directory("rmf_maps")

    default_config = os.path.join(adapter_share, "config", "pinky_adapter.yaml")
    default_nav_graph = os.path.join(maps_share, "nav_graphs", "0.yaml")

    return LaunchDescription(
        [
            DeclareLaunchArgument("config_file", default_value=default_config),
            DeclareLaunchArgument("nav_graph_file", default_value=default_nav_graph),
            DeclareLaunchArgument("server_uri", default_value=""),
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            OpaqueFunction(function=_launch_adapter),
        ]
    )
