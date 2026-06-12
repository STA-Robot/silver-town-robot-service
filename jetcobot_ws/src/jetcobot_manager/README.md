# jetcobot_manager

RMF/workcell 명령을 JetCobot arm 동작으로 변환하는 ROS 2 Python 패키지입니다.

`arm_manager` 노드는 `jetcobot_workcell_msgs/msg/WorkcellCommand`를 `/command`에서 받고, `jetcobot_workcell_msgs/action/PickPlace` action server(`/pick_place`)에 pick-and-place goal을 보냅니다. RMF/workcell 관점의 실행 상태와 결과는 manager가 `jetcobot_workcell_msgs/msg/WorkcellState`로 `/state`에 publish합니다.

## 빌드

```bash
cd jetcobot_ws
colcon build --packages-select jetcobot_workcell_msgs jetcobot_manager
source install/setup.bash
```

실제 pick-and-place 실행에는 `jetcobot_workcell_msgs/action/PickPlace`를 쓰는 `pick_place_action_server`가 같은 ROS graph에 떠 있어야 합니다.

## 실행

```bash
ros2 run jetcobot_manager arm_manager --ros-args \
  -p arm_name:=jetcobot1 \
  -p command_topic:=/command \
  -p state_topic:=/state \
  -p pick_place_action:=/pick_place
```

기본 config 파일은 설치된 `jetcobot_manager/config/arm_manager.yaml`입니다. 다른 파일을 쓰려면:

```bash
ros2 run jetcobot_manager arm_manager --ros-args \
  -p config_file:=/path/to/arm_manager.yaml
```

## Command

지원하는 `command_type`:

| command_type | 동작 |
| --- | --- |
| `pick_and_place` | `PickPlace` action goal을 보내고 feedback/result를 manager 상태로 publish합니다. |
| `stop` | 현재 실행 중인 `PickPlace` goal cancel을 요청하고 상태를 `blocked`로 바꿉니다. |
| `reset` | 현재 goal을 cancel하고 내부 상태를 초기화한 뒤 `idle`로 돌아갑니다. |

예시:

```bash
ros2 topic pub --once /command jetcobot_workcell_msgs/msg/WorkcellCommand \
  "{arm_name: 'jetcobot1', command_id: 'cmd-001', command_type: 'pick_and_place', mission_id: 'mission-001'}"
```

## State

이 노드는 service response를 반환하지 않고 `/state`를 계속 publish합니다. RMF 쪽에서는 command id를 기준으로 active 상태와 마지막 처리 상태를 구분해야 합니다.

```text
command_active == true && active_command_id == 내가 보낸 command_id
  -> 내가 보낸 명령이 현재 실행 중

last_command_id == 내가 보낸 command_id
  -> 내가 보낸 명령의 최근 상태는 last_command_status
```
