from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    moveit_launch_dir = PathJoinSubstitution([
        FindPackageShare("jetcobot_moveit_config"),
        "launch",
    ])

    return LaunchDescription([
        DeclareLaunchArgument("use_rviz", default_value="true"),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                PathJoinSubstitution([moveit_launch_dir, "static_virtual_joint_tfs.launch.py"])
            )
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                PathJoinSubstitution([moveit_launch_dir, "rsp.launch.py"])
            )
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                PathJoinSubstitution([moveit_launch_dir, "move_group.launch.py"])
            )
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                PathJoinSubstitution([moveit_launch_dir, "moveit_rviz.launch.py"])
            ),
            condition=IfCondition(LaunchConfiguration("use_rviz")),
        ),
    ])
