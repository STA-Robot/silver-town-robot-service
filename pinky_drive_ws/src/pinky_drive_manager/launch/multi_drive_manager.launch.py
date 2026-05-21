import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _as_bool(value: str) -> bool:
    return value.lower() in ("1", "true", "yes", "on")


def _launch_nodes(context, *args, **kwargs):
    del args, kwargs

    config_file = LaunchConfiguration("config_file").perform(context)
    robot_names_arg = LaunchConfiguration("robot_names").perform(context)
    rmf_level = LaunchConfiguration("rmf_level").perform(context)
    use_sim_time = LaunchConfiguration("use_sim_time").perform(context)

    robot_names = [
        robot_name.strip()
        for robot_name in robot_names_arg.split(",")
        if robot_name.strip()
    ]

    actions = [
        LogInfo(
            msg=(
                "multi_drive_manager.launch.py는 같은 ROS_DOMAIN_ID 안에서 "
                "여러 drive_manager를 디버그할 때만 사용하세요. 기본 domain bridge "
                "구조에서는 각 Pinky domain에서 drive_manager.launch.py를 하나씩 실행합니다."
            )
        )
    ]

    for robot_name in robot_names:
        node_args = ["--config-file", config_file, "--robot-name", robot_name]
        if rmf_level:
            node_args.extend(["--rmf-level", rmf_level])

        actions.append(
            Node(
                package="pinky_drive_manager",
                executable="drive_manager_node",
                name=f"drive_manager_{robot_name}",
                output="screen",
                arguments=node_args,
                parameters=[{"use_sim_time": _as_bool(use_sim_time)}],
            )
        )

    return actions


def generate_launch_description():
    package_share = get_package_share_directory("pinky_drive_manager")
    default_config = os.path.join(package_share, "config", "pinky_drive_manager.yaml")

    return LaunchDescription(
        [
            DeclareLaunchArgument("config_file", default_value=default_config),
            DeclareLaunchArgument("robot_names", default_value="pinky1,pinky2"),
            DeclareLaunchArgument("rmf_level", default_value=""),
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            OpaqueFunction(function=_launch_nodes),
        ]
    )
