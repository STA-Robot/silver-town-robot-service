import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    maps_share = get_package_share_directory("pinky_rmf_maps")
    default_building_map = os.path.join(
        maps_share, "maps", "rmf-test.building.yaml"
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "building_map_file",
                default_value=default_building_map,
            ),
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            DeclareLaunchArgument("use_schedule_node", default_value="true"),
            DeclareLaunchArgument("use_task_dispatcher", default_value="true"),
            DeclareLaunchArgument("use_building_map_server", default_value="true"),
            Node(
                package="rmf_traffic_ros2",
                executable="rmf_traffic_schedule",
                name="rmf_traffic_schedule",
                output="screen",
                condition=IfCondition(LaunchConfiguration("use_schedule_node")),
                parameters=[{"use_sim_time": LaunchConfiguration("use_sim_time")}],
            ),
            Node(
                package="rmf_task_ros2",
                executable="rmf_task_dispatcher",
                name="rmf_task_dispatcher",
                output="screen",
                condition=IfCondition(LaunchConfiguration("use_task_dispatcher")),
                parameters=[{"use_sim_time": LaunchConfiguration("use_sim_time")}],
            ),
            Node(
                package="rmf_building_map_tools",
                executable="building_map_server",
                name="building_map_server",
                output="screen",
                arguments=[LaunchConfiguration("building_map_file")],
                condition=IfCondition(LaunchConfiguration("use_building_map_server")),
                parameters=[{"use_sim_time": LaunchConfiguration("use_sim_time")}],
            ),
        ]
    )
