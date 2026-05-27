import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, TimerAction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    adapter_share = get_package_share_directory("pinky_rmf_adapter")
    maps_share = get_package_share_directory("rmf_maps")
    orchestrator_share = get_package_share_directory("task_orchestrator")

    adapter_launch = os.path.join(
        adapter_share, "launch", "pinky_fleet_adapter.launch.py"
    )
    core_launch = os.path.join(
        get_package_share_directory("rmf_bringup"),
        "launch",
        "rmf_core.launch.py",
    )
    orchestrator_launch = os.path.join(
        orchestrator_share, "launch", "task_orchestrator.launch.py"
    )
    default_config = os.path.join(adapter_share, "config", "pinky_adapter.yaml")
    default_nav_graph = os.path.join(maps_share, "nav_graphs", "0.yaml")
    default_building_map = os.path.join(
        maps_share, "maps", "rmf-test.building.yaml"
    )
    default_orchestrator_config = os.path.join(
        orchestrator_share, "config", "task_orchestrator.yaml"
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument("config_file", default_value=default_config),
            DeclareLaunchArgument("nav_graph_file", default_value=default_nav_graph),
            DeclareLaunchArgument(
                "building_map_file",
                default_value=default_building_map,
            ),
            DeclareLaunchArgument("use_rmf_core", default_value="true"),
            DeclareLaunchArgument("use_schedule_node", default_value="true"),
            DeclareLaunchArgument("use_task_dispatcher", default_value="true"),
            DeclareLaunchArgument("use_building_map_server", default_value="true"),
            DeclareLaunchArgument("adapter_start_delay", default_value="2.0"),
            DeclareLaunchArgument(
                "task_orchestrator_config",
                default_value=default_orchestrator_config,
            ),
            DeclareLaunchArgument("use_fleet_adapter", default_value="true"),
            DeclareLaunchArgument("use_task_orchestrator", default_value="true"),
            DeclareLaunchArgument("task_orchestrator_log_level", default_value="info"),
            DeclareLaunchArgument("server_uri", default_value=""),
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(core_launch),
                condition=IfCondition(LaunchConfiguration("use_rmf_core")),
                launch_arguments={
                    "building_map_file": LaunchConfiguration("building_map_file"),
                    "use_schedule_node": LaunchConfiguration("use_schedule_node"),
                    "use_task_dispatcher": LaunchConfiguration("use_task_dispatcher"),
                    "use_building_map_server": LaunchConfiguration(
                        "use_building_map_server"
                    ),
                    "use_sim_time": LaunchConfiguration("use_sim_time"),
                }.items(),
            ),
            TimerAction(
                period=LaunchConfiguration("adapter_start_delay"),
                actions=[
                    IncludeLaunchDescription(
                        PythonLaunchDescriptionSource(adapter_launch),
                        condition=IfCondition(
                            LaunchConfiguration("use_fleet_adapter")
                        ),
                        launch_arguments={
                            "config_file": LaunchConfiguration("config_file"),
                            "nav_graph_file": LaunchConfiguration("nav_graph_file"),
                            "server_uri": LaunchConfiguration("server_uri"),
                            "use_sim_time": LaunchConfiguration("use_sim_time"),
                        }.items(),
                    ),
                    IncludeLaunchDescription(
                        PythonLaunchDescriptionSource(orchestrator_launch),
                        condition=IfCondition(
                            LaunchConfiguration("use_task_orchestrator")
                        ),
                        launch_arguments={
                            "config_file": LaunchConfiguration(
                                "task_orchestrator_config"
                            ),
                            "log_level": LaunchConfiguration(
                                "task_orchestrator_log_level"
                            ),
                        }.items(),
                    ),
                ],
            ),
        ]
    )
