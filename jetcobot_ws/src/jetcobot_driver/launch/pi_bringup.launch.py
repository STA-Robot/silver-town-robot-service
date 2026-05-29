from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    port = LaunchConfiguration("port")
    baud = LaunchConfiguration("baud")
    speed = LaunchConfiguration("speed")
    gripper_speed = LaunchConfiguration("gripper_speed")
    joint_state_rate = LaunchConfiguration("joint_state_rate")
    wait_for_motion = LaunchConfiguration("wait_for_motion")
    motion_timeout = LaunchConfiguration("motion_timeout")
    joint_tolerance_deg = LaunchConfiguration("joint_tolerance_deg")
    poll_interval = LaunchConfiguration("poll_interval")
    gripper_wait_seconds = LaunchConfiguration("gripper_wait_seconds")
    use_arm_manager = LaunchConfiguration("use_arm_manager")
    arm_name = LaunchConfiguration("arm_name")
    arm_manager_config_file = LaunchConfiguration("arm_manager_config_file")
    command_topic = LaunchConfiguration("command_topic")
    state_topic = LaunchConfiguration("state_topic")
    move_group_action = LaunchConfiguration("move_group_action")

    return LaunchDescription(
        [
            DeclareLaunchArgument("port", default_value="/dev/ttyJETCOBOT"),
            DeclareLaunchArgument("baud", default_value="1000000"),
            DeclareLaunchArgument("speed", default_value="25"),
            DeclareLaunchArgument("gripper_speed", default_value="80"),
            DeclareLaunchArgument("joint_state_rate", default_value="20.0"),
            DeclareLaunchArgument("wait_for_motion", default_value="true"),
            DeclareLaunchArgument("motion_timeout", default_value="15.0"),
            DeclareLaunchArgument("joint_tolerance_deg", default_value="3.0"),
            DeclareLaunchArgument("poll_interval", default_value="0.2"),
            DeclareLaunchArgument("gripper_wait_seconds", default_value="1.0"),
            DeclareLaunchArgument("use_arm_manager", default_value="false"),
            DeclareLaunchArgument("arm_name", default_value="jetcobot1"),
            DeclareLaunchArgument(
                "arm_manager_config_file",
                default_value=PathJoinSubstitution(
                    [
                        FindPackageShare("jetcobot_driver"),
                        "config",
                        "arm_manager.yaml",
                    ]
                ),
            ),
            DeclareLaunchArgument("command_topic", default_value="/command"),
            DeclareLaunchArgument("state_topic", default_value="/state"),
            DeclareLaunchArgument("move_group_action", default_value="/move_action"),
            Node(
                package="jetcobot_driver",
                executable="trajectory_action_server",
                name="jetcobot_trajectory_driver",
                output="screen",
                parameters=[
                    {
                        "port": port,
                        "baud": baud,
                        "speed": speed,
                        "gripper_speed": gripper_speed,
                        "joint_state_rate": joint_state_rate,
                        "wait_for_motion": wait_for_motion,
                        "motion_timeout": motion_timeout,
                        "joint_tolerance_deg": joint_tolerance_deg,
                        "poll_interval": poll_interval,
                        "gripper_wait_seconds": gripper_wait_seconds,
                    }
                ],
            ),
            Node(
                package="jetcobot_driver",
                executable="arm_manager",
                name="jetcobot_arm_manager",
                output="screen",
                condition=IfCondition(use_arm_manager),
                parameters=[
                    {
                        "arm_name": arm_name,
                        "command_topic": command_topic,
                        "state_topic": state_topic,
                        "move_group_action": move_group_action,
                        "config_file": arm_manager_config_file,
                    }
                ],
            ),
        ]
    )
