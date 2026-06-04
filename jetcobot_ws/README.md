# jetcobot_ws

JetCobot ROS 2 워크스페이스입니다. MoveIt으로 arm trajectory를 계획하고, `jetcobot_driver`가 실제 JetCobot / MyCobot280 하드웨어에 arm 및 gripper 명령을 전달합니다.

## 패키지 구성

| 패키지 | 역할 |
| --- | --- |
| `jetcobot_description` | URDF, RViz display 설정 |
| `jetcobot_moveit_config` | MoveIt 설정, `/move_action`, RViz launch |
| `jetcobot_driver` | 실제 하드웨어용 `/arm_controller/follow_joint_trajectory`, `/gripper_controller/follow_joint_trajectory` action server |
| `jetcobot_manager` | `/command`를 받아 pick-and-place sequence 실행, `/state` publish |
| `jetcobot_workcell_msgs` | workcell command/state 메시지 |

## 실행 구조

Arm target은 manager가 MoveIt `MoveGroup` action으로 보내고, MoveIt이 planning 후 arm controller action으로 실행합니다.

```text
/command
  -> jetcobot_manager
  -> /move_action
  -> MoveIt move_group
  -> /arm_controller/follow_joint_trajectory
  -> jetcobot_driver
  -> JetCobot arm
```

Gripper target은 MoveIt planning을 거치지 않고 gripper controller action으로 바로 보냅니다.

```text
jetcobot_manager
  -> /gripper_controller/follow_joint_trajectory
  -> jetcobot_driver
  -> JetCobot gripper
```

## 빌드

ROS 2 Jazzy 환경을 source한 뒤 워크스페이스 전체를 빌드합니다.

```bash
cd jetcobot_ws
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build
source install/setup.bash
```

빠르게 런타임 핵심 패키지만 다시 빌드할 때는 다음처럼 선택 빌드할 수 있습니다.

```bash
colcon build --packages-select \
  jetcobot_workcell_msgs \
  jetcobot_manager \
  jetcobot_driver \
  jetcobot_moveit_config
source install/setup.bash
```

## 전체 실행 흐름

분산 실행 시 노트북과 Raspberry Pi에서 같은 ROS 네트워크 설정을 사용해야 합니다. 예를 들어 양쪽 터미널에서 같은 `ROS_DOMAIN_ID`를 설정합니다.

```bash
export ROS_DOMAIN_ID=30
source /opt/ros/jazzy/setup.bash
source /path/to/jetcobot_ws/install/setup.bash
```

### 1. MoveIt 실행

노트북 또는 MoveIt을 돌릴 장비에서 실행합니다.

```bash
cd jetcobot_ws
source install/setup.bash
ros2 launch jetcobot_moveit_config laptop.launch.py use_rviz:=true
```

이 launch는 robot state publisher, static virtual joint TF, MoveIt `move_group`, RViz를 실행합니다. RViz 없이 돌릴 때는 `use_rviz:=false`를 사용합니다.

```bash
ros2 launch jetcobot_moveit_config laptop.launch.py use_rviz:=false
```

### 2. 하드웨어 드라이버와 arm manager 실행

JetCobot이 연결된 Raspberry Pi에서 실행합니다.

```bash
cd jetcobot_ws
source install/setup.bash
ros2 launch jetcobot_driver pi_bringup.launch.py \
  port:=/dev/ttyJETCOBOT \
  use_arm_manager:=true \
  arm_name:=jetcobot1
```

주요 launch 인자:

| 인자 | 기본값 | 설명 |
| --- | --- | --- |
| `port` | `/dev/ttyJETCOBOT` | JetCobot serial device |
| `baud` | `1000000` | Serial baudrate |
| `speed` | `25` | Arm command speed |
| `gripper_speed` | `80` | Gripper command speed |
| `wait_for_motion` | `true` | 목표 도달 대기 여부 |
| `use_arm_manager` | `false` | `jetcobot_manager` 함께 실행 여부 |
| `arm_manager_config_file` | installed `arm_manager.yaml` | Pick-and-place sequence 설정 |
| `command_topic` | `/command` | Workcell command 입력 |
| `state_topic` | `/state` | Workcell state 출력 |
| `move_group_action` | `/move_action` | MoveIt action 이름 |

### 3. 실행 상태 확인

다른 터미널에서 action server와 state topic을 확인합니다.

```bash
source /opt/ros/jazzy/setup.bash
source jetcobot_ws/install/setup.bash

ros2 action list | grep -E 'move_action|follow_joint_trajectory'
ros2 topic echo /state
```

기대되는 action 이름:

```text
/move_action
/arm_controller/follow_joint_trajectory
/gripper_controller/follow_joint_trajectory
```

### 4. Pick-and-place 명령 전송

```bash
ros2 topic pub --once /command jetcobot_workcell_msgs/msg/WorkcellCommand \
  "{arm_name: 'jetcobot1', command_id: 'cmd-001', command_type: 'pick_and_place', mission_id: 'mission-001'}"
```

완료 여부는 `/state`에서 `last_command_id`와 `last_command_status`를 같이 보고 판단합니다.

```text
last_command_id: cmd-001
last_command_status: succeeded
state: idle
available: true
```

실패 시에는 `message` 필드에 어느 단계가 실패했는지 표시됩니다.

## 단독 smoke test

MoveIt과 manager를 거치지 않고 하드웨어 driver action server만 확인할 때 사용합니다. `pi_bringup.launch.py`가 실행 중이어야 합니다.

Arm:

```bash
ros2 action send_goal /arm_controller/follow_joint_trajectory \
  control_msgs/action/FollowJointTrajectory \
  "{trajectory: {joint_names: [joint2_to_joint1, joint3_to_joint2, joint4_to_joint3, joint5_to_joint4, joint6_to_joint5, joint6output_to_joint6], points: [{positions: [0.0, 0.2, -0.2, 0.0, 0.0, 0.0], time_from_start: {sec: 2}}]}}"
```

Gripper open:

```bash
ros2 action send_goal /gripper_controller/follow_joint_trajectory \
  control_msgs/action/FollowJointTrajectory \
  "{trajectory: {joint_names: [gripper_controller], points: [{positions: [0.1], time_from_start: {sec: 1}}]}}"
```

Gripper close:

```bash
ros2 action send_goal /gripper_controller/follow_joint_trajectory \
  control_msgs/action/FollowJointTrajectory \
  "{trajectory: {joint_names: [gripper_controller], points: [{positions: [-0.4], time_from_start: {sec: 1}}]}}"
```

## 설정 파일

Pick-and-place sequence는 `src/jetcobot_manager/config/arm_manager.yaml`에서 수정합니다.

```yaml
pick_and_place_sequence:
  - target: ready
    state: homing
    message: moving to ready pose
  - target: gripper_open
    state: picking
    message: opening gripper
  - target: gripper_close
    state: picking
    message: closing gripper
  - target: home
    state: homing
    message: returning home
```

`group: arm` target은 MoveIt `/move_action`으로 실행되고, `group: gripper` target은 `/gripper_controller/follow_joint_trajectory`로 직접 실행됩니다.
