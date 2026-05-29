# jetcobot_driver

Minimal ROS 2 Python driver for sending MoveIt `FollowJointTrajectory` goals to a
real JetCobot / MyCobot280 through `pymycobot`.

## Build

```bash
cd jetcobot_ws
colcon build --packages-select jetcobot_driver
source install/setup.bash
```

## Launch On The Raspberry Pi

```bash
ros2 launch jetcobot_driver pi_bringup.launch.py port:=/dev/ttyJETCOBOT
```

Optional launch arguments:

```bash
ros2 launch jetcobot_driver pi_bringup.launch.py \
  port:=/dev/ttyJETCOBOT \
  baud:=1000000 \
  speed:=25 \
  gripper_speed:=80 \
  joint_state_rate:=20.0
```

## Smoke Test Arm Goal

```bash
ros2 action send_goal /arm_controller/follow_joint_trajectory \
  control_msgs/action/FollowJointTrajectory \
  "{trajectory: {joint_names: [joint2_to_joint1, joint3_to_joint2, joint4_to_joint3, joint5_to_joint4, joint6_to_joint5, joint6output_to_joint6], points: [{positions: [0.0, 0.2, -0.2, 0.0, 0.0, 0.0], time_from_start: {sec: 2}}]}}"
```

## Smoke Test Gripper Goal

Open:

```bash
ros2 action send_goal /gripper_controller/follow_joint_trajectory \
  control_msgs/action/FollowJointTrajectory \
  "{trajectory: {joint_names: [gripper_controller], points: [{positions: [0.1], time_from_start: {sec: 1}}]}}"
```

Close:

```bash
ros2 action send_goal /gripper_controller/follow_joint_trajectory \
  control_msgs/action/FollowJointTrajectory \
  "{trajectory: {joint_names: [gripper_controller], points: [{positions: [-0.4], time_from_start: {sec: 1}}]}}"
```

## Joint States

The driver publishes command-echo state on `/joint_states`. It does not poll
hardware angles.
