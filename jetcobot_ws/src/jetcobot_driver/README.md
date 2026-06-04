# jetcobot_driver

실제 JetCobot / MyCobot280 하드웨어를 `pymycobot`으로 제어하기 위한 ROS 2 Python 드라이버입니다.

JetCobot 관련 런타임은 두 ROS 2 패키지로 나뉩니다.

- `trajectory_action_server`: `/arm_controller/follow_joint_trajectory`, `/gripper_controller/follow_joint_trajectory` action goal을 받아 실제 로봇에 관절/그리퍼 명령을 보냅니다.
- `jetcobot_manager`: RMF 또는 상위 workcell 노드가 보내는 `/command`를 받아 pick-and-place 시퀀스를 실행하고, 결과를 `/state`로 publish합니다. Arm target은 `MoveGroup` action(`/move_action`)으로 보내고, gripper target은 `/gripper_controller/follow_joint_trajectory`로 직접 보냅니다.

## 빌드

Raspberry Pi bringup launch까지 사용할 때는 manager와 메시지 패키지를 함께 빌드합니다.

```bash
cd jetcobot_ws
colcon build --packages-select jetcobot_workcell_msgs jetcobot_manager jetcobot_driver
source install/setup.bash
```

하드웨어 trajectory action server만 단독으로 확인할 때는 driver 패키지만 빌드할 수 있습니다.

```bash
cd jetcobot_ws
colcon build --packages-select jetcobot_driver
source install/setup.bash
```

## Raspberry Pi에서 실행

기본 드라이버만 실행:

```bash
ros2 launch jetcobot_driver pi_bringup.launch.py port:=/dev/ttyJETCOBOT
```

사용 가능한 주요 launch 인자:

```bash
ros2 launch jetcobot_driver pi_bringup.launch.py \
  port:=/dev/ttyJETCOBOT \
  baud:=1000000 \
  speed:=25 \
  gripper_speed:=80 \
  joint_state_rate:=20.0 \
  wait_for_motion:=true \
  motion_timeout:=15.0 \
  joint_tolerance_deg:=3.0 \
  poll_interval:=0.2 \
  gripper_wait_seconds:=1.0
```

`wait_for_motion:=true`일 때 arm trajectory goal은 `pymycobot.get_angles()`로 실제 관절 각도를 읽고, 목표가 `joint_tolerance_deg` 안에 들어온 것을 확인한 뒤 성공 처리합니다. `wait_for_motion:=false`로 설정하면 하드웨어에 명령을 보낸 시점에 성공 처리합니다.

그리퍼 goal은 실제 그리퍼 위치 피드백을 읽지 않고, `wait_for_motion:=true`일 때 `gripper_wait_seconds`만큼 기다린 뒤 성공 처리합니다.

## Arm Manager 함께 실행

RMF/workcell 연동용 arm manager까지 함께 실행하려면:

```bash
ros2 launch jetcobot_driver pi_bringup.launch.py \
  port:=/dev/ttyJETCOBOT \
  use_arm_manager:=true \
  arm_name:=jetcobot1
```

arm manager의 기본 통신 경로:

- command 입력: `/command`
- state 출력: `/state`
- MoveIt action client: `/move_action`
- 설정 파일: `jetcobot_manager/config/arm_manager.yaml`

필요하면 launch 인자로 바꿀 수 있습니다.

```bash
ros2 launch jetcobot_driver pi_bringup.launch.py \
  use_arm_manager:=true \
  arm_name:=jetcobot1 \
  command_topic:=/command \
  state_topic:=/state \
  move_group_action:=/move_action \
  arm_manager_config_file:=/path/to/arm_manager.yaml
```

## RMF 요청 처리 흐름

RMF 또는 상위 노드는 `jetcobot_workcell_msgs/msg/WorkcellCommand` 메시지를 `/command`로 publish합니다.

요청 메시지 필드:

```text
std_msgs/Header header
string arm_name
string command_id
string command_type
string mission_id
string[] item_type_guids
string payload_json
```

현재 arm manager가 실제로 처리하는 `command_type`은 다음과 같습니다.

| command_type | 동작 |
| --- | --- |
| `pick_and_place` | `arm_manager.yaml`의 `pick_and_place_sequence`를 순서대로 실행합니다. Arm step은 MoveIt `MoveGroup` goal로 `/move_action`에 전송하고, gripper step은 `/gripper_controller/follow_joint_trajectory`에 전송합니다. |
| `stop` | 현재 실행 중인 MoveGroup 또는 gripper trajectory goal이 있으면 cancel 요청을 보내고, arm manager 상태를 `blocked`로 바꿉니다. |
| `reset` | 현재 goal을 cancel하고 내부 상태를 초기화한 뒤 `idle`로 돌아갑니다. |

`arm_name`이 비어 있으면 모든 arm manager가 받을 수 있고, 값이 있으면 같은 `arm_name`을 가진 manager만 처리합니다.

현재 구현에서 `mission_id`는 상태 메시지에 그대로 전달되어 추적용으로 쓰이고, `item_type_guids`와 `payload_json`은 아직 동작 분기에 사용하지 않습니다.

`pick_and_place` 같은 작업 명령은 다음 경우 실행하지 않고 `last_command_status: rejected`를 publish합니다. `stop`과 `reset`은 정지/복구 명령이라 이 검증보다 먼저 처리됩니다.

- `command_id`가 비어 있음
- emergency 상태임
- 다른 command가 이미 실행 중임
- 지원하지 않는 `command_type`임

`pick_and_place` 요청 예시:

```bash
ros2 topic pub --once /command jetcobot_workcell_msgs/msg/WorkcellCommand \
  "{arm_name: 'jetcobot1', command_id: 'cmd-001', command_type: 'pick_and_place', mission_id: 'mission-001'}"
```

## RMF로 돌려주는 상태

arm manager는 요청에 대한 별도 service response를 반환하지 않습니다. 대신 `jetcobot_workcell_msgs/msg/WorkcellState`를 `/state`로 계속 publish합니다.

상태 메시지 필드:

```text
std_msgs/Header header
string arm_name
string state
bool available
bool emergency
bool command_active
string active_command_id
string last_command_id
string last_command_status
string mission_id
float32 progress
float32 seconds_remaining
string message
```

주요 상태 값:

| 필드 | 의미 |
| --- | --- |
| `state` | 현재 arm 상태입니다. 코드 기본값은 `idle`, `reserved`, `picking`, `placing`, `blocked`이며, YAML sequence에 따라 `homing` 같은 상태 문자열도 publish될 수 있습니다. |
| `available` | 새 작업을 받을 수 있으면 `true`입니다. 현재 구현에서는 emergency가 아니고, active command가 없고, state가 `idle`일 때만 `true`입니다. |
| `command_active` | 현재 실행 중인 command가 있으면 `true`입니다. |
| `active_command_id` | 현재 실행 중인 command id입니다. 실행 중인 명령이 없으면 빈 문자열입니다. |
| `last_command_id` | 가장 최근에 처리 또는 상태 갱신된 command id입니다. |
| `last_command_status` | `last_command_id`에 대한 상태입니다. `accepted`, `succeeded`, `failed`, `rejected`, `canceled` 중 하나가 될 수 있습니다. |
| `progress` | pick-and-place sequence 진행률입니다. `0.0`에서 `1.0` 사이 값입니다. |
| `seconds_remaining` | 설정값 `seconds_per_step_estimate`와 남은 step 수로 계산한 예상 남은 시간입니다. |
| `message` | 사람이 읽을 수 있는 현재 상태/오류 설명입니다. |

RMF 쪽에서는 `last_command_status`만 단독으로 보면 안 됩니다. 반드시 command id를 같이 비교해야 합니다.

권장 판단 방식:

```text
command_active == true && active_command_id == 내가 보낸 command_id
  -> 내가 보낸 명령이 현재 실행 중

last_command_id == 내가 보낸 command_id
  -> 내가 보낸 명령의 최근 상태는 last_command_status

command_active == false && last_command_id == 내가 보낸 command_id
  -> 내가 보낸 명령이 완료/실패/취소/거절된 상태로 판단 가능
```

예를 들어 실행 중 상태는 다음처럼 publish될 수 있습니다.

```text
command_active: true
active_command_id: "cmd-001"
last_command_id: "cmd-001"
last_command_status: "accepted"
state: "homing"
progress: 0.5
```

완료 후에는 다음처럼 바뀝니다.

```text
command_active: false
active_command_id: ""
last_command_id: "cmd-001"
last_command_status: "succeeded"
state: "idle"
progress: 1.0
```

실행 중에 다른 command가 들어오면 기존 command는 계속 실행되고, 새 command는 거절될 수 있습니다.

```text
command_active: true
active_command_id: "cmd-001"
last_command_id: "cmd-002"
last_command_status: "rejected"
message: "command already active: cmd-001"
```

이 경우 `cmd-001`은 아직 실행 중이고, `cmd-002`만 거절된 것입니다.

## 중복 명령 처리

같은 `command_id`가 현재 active command와 같으면 arm manager는 새 동작을 시작하지 않고 현재 state만 다시 publish합니다.

이미 완료된 command id가 최근 완료 cache에 남아 있으면 역시 재실행하지 않고 현재 state만 publish합니다. cache 크기는 `recent_command_cache_size` 파라미터로 정합니다.

## Pick-and-place 시퀀스 설정

`jetcobot_manager/config/arm_manager.yaml`에서 joint target과 실행 순서를 정의합니다.

```yaml
pick_and_place_sequence:
  - target: ready
    state: homing
    message: moving to ready pose
  - target: home
    state: homing
    message: returning home
```

각 step의 `target`은 `joint_targets`에 정의되어 있어야 합니다. `group: arm` target은 MoveIt `moveit_msgs/action/MoveGroup` goal의 `goal_constraints`로 변환해 `/move_action`에 보냅니다. `group: gripper` target은 `control_msgs/action/FollowJointTrajectory` goal로 변환해 `/gripper_controller/follow_joint_trajectory`에 보냅니다.

현재 기본 YAML은 smoke test용 home/ready 중심 값입니다. 실제 pick/place 위치는 현장 캘리브레이션 후 `pick_approach`, `place_approach`, gripper step 등을 활성화해서 사용해야 합니다.

## Arm trajectory smoke test

```bash
ros2 action send_goal /arm_controller/follow_joint_trajectory \
  control_msgs/action/FollowJointTrajectory \
  "{trajectory: {joint_names: [joint2_to_joint1, joint3_to_joint2, joint4_to_joint3, joint5_to_joint4, joint6_to_joint5, joint6output_to_joint6], points: [{positions: [0.0, 0.2, -0.2, 0.0, 0.0, 0.0], time_from_start: {sec: 2}}]}}"
```

## Gripper smoke test

열기:

```bash
ros2 action send_goal /gripper_controller/follow_joint_trajectory \
  control_msgs/action/FollowJointTrajectory \
  "{trajectory: {joint_names: [gripper_controller], points: [{positions: [0.1], time_from_start: {sec: 1}}]}}"
```

닫기:

```bash
ros2 action send_goal /gripper_controller/follow_joint_trajectory \
  control_msgs/action/FollowJointTrajectory \
  "{trajectory: {joint_names: [gripper_controller], points: [{positions: [-0.4], time_from_start: {sec: 1}}]}}"
```

## Joint States

드라이버는 최신으로 알고 있는 관절 위치를 `/joint_states`로 publish합니다.

`wait_for_motion`이 켜져 있고 arm goal이 실행 중일 때는 `pymycobot.get_angles()`로 실제 arm 각도를 읽어 `/joint_states`를 갱신합니다. 그리퍼 위치는 실제 피드백이 아니라 마지막으로 보낸 target position을 기준으로 publish합니다.
