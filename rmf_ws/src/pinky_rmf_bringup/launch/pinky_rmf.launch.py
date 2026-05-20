import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    adapter_share = get_package_share_directory("pinky_rmf_adapter")
    maps_share = get_package_share_directory("pinky_rmf_maps")
    orchestrator_share = get_package_share_directory("pinky_task_orchestrator")

    adapter_launch = os.path.join(
        adapter_share, "launch", "pinky_fleet_adapter.launch.py"
    )
    orchestrator_launch = os.path.join(
        orchestrator_share, "launch", "task_orchestrator.launch.py"
    )
    default_config = os.path.join(adapter_share, "config", "pinky_adapter.yaml")
    default_nav_graph = os.path.join(maps_share, "nav_graphs", "0.yaml")
    default_orchestrator_config = os.path.join(
        orchestrator_share, "config", "task_orchestrator.yaml"
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument("config_file", default_value=default_config),
            DeclareLaunchArgument("nav_graph_file", default_value=default_nav_graph),
            DeclareLaunchArgument(
                "task_orchestrator_config",
                default_value=default_orchestrator_config,
            ),
            DeclareLaunchArgument("use_task_orchestrator", default_value="true"),
            DeclareLaunchArgument("server_uri", default_value=""),
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(adapter_launch),
                launch_arguments={
                    "config_file": LaunchConfiguration("config_file"),
                    "nav_graph_file": LaunchConfiguration("nav_graph_file"),
                    "server_uri": LaunchConfiguration("server_uri"),
                    "use_sim_time": LaunchConfiguration("use_sim_time"),
                }.items(),
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(orchestrator_launch),
                condition=IfCondition(LaunchConfiguration("use_task_orchestrator")),
                launch_arguments={
                    "config_file": LaunchConfiguration("task_orchestrator_config"),
                }.items(),
            ),
        ]
    )
