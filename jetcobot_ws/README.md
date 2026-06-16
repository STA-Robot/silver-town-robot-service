# jetcobot_ws

JetCobot ROS 2 워크스페이스입니다. `jetcobot_manager`가 RMF/workcell 명령을 받고, 별도 `pick_place_action_server`의 `jetcobot_msgs/action/PickPlace` action으로 pick-and-place를 요청합니다.

## 패키지 구성

| 패키지 | 역할 |
| --- | --- |
| `jetcobot_description` | URDF, RViz display 설정 |
| `jetcobot_moveit_config` | MoveIt 설정, `/move_action`, RViz launch |
| `jetcobot_driver` | 실제 하드웨어용 `/arm_controller/follow_joint_trajectory`, `/gripper_controller/follow_joint_trajectory` action server |
| `jetcobot_manager` | `/command`를 받아 `/pick_place` action goal 전송, `/state` publish |
| `jetcobot_msgs` | JetCobot command/state/action 인터페이스 |

## 실행 구조

RMF/workcell 명령은 manager가 상태를 관리하면서 `PickPlace` action server에 goal 하나로 전달합니다.

```text
/command
  -> jetcobot_manager
  -> /pick_place
  -> pick_place_action_server
  -> JetCobot pick-and-place flow
```

`/state`는 action server가 아니라 manager가 publish하므로 RMF 쪽 상태 추적 지점은 계속 manager 하나입니다.

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
  jetcobot_msgs \
  jetcobot_manager \
  jetcobot_driver \
  jetcobot_moveit_config
source install/setup.bash
```

## 전체 실행 흐름

분산 실행 시 노트북과 Raspberry Pi에서 같은 ROS 네트워크 설정을 사용해야 합니다.
JetCobot local domain은 RMF domain과 분리하며, 기본 예시는 `ROS_DOMAIN_ID=34`를
사용합니다. 이 domain 안에서는 arm manager가 `/command`, `/state`를 그대로
사용하고, RMF domain에서는 `domain_bridge`가 이를 `/jetcobot1/command`,
`/jetcobot1/state`로 remap합니다.

```bash
export ROS_DOMAIN_ID=34
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
| `arm_manager_config_file` | installed `arm_manager.yaml` | PickPlace action/state mapping 설정 |
| `command_topic` | `/command` | Workcell command 입력 |
| `state_topic` | `/state` | Workcell state 출력 |
| `pick_place_action` | `/pick_place` | PickPlace action 이름 |

RMF와 함께 사용할 때도 JetCobot local domain의 launch 인자는 기본값을 유지한다.
즉, `command_topic:=/command`, `state_topic:=/state`로 두고 RMF workspace의
`jetcobot1_domain_bridge.yaml`이 아래처럼 remap한다.

```text
RMF domain 31 /jetcobot1/command -> JetCobot domain 34 /command
JetCobot domain 34 /state        -> RMF domain 31 /jetcobot1/state
```

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
ros2 topic pub --once /command jetcobot_msgs/msg/ArmCommand \
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

PickPlace action 이름과 feedback state mapping은 `src/jetcobot_manager/config/arm_manager.yaml`에서 수정합니다.

```yaml
pick_place:
  action_name: /pick_place
  server_timeout: 5.0
  seconds_estimate: 30.0
  state_map:
    GO_READY: homing
    SEARCHING: aligning
    SERVO: aligning
    OFFSET_MOVE: picking
    DESCENDING: picking
    GRIPPING: picking
    LIFTING: picking
    SERVO_FAILED: blocked
```
