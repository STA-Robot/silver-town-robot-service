# Pinky Drive Workspace

이 저장소는 Pinky 로봇을 RMF에서 제어하기 위한 ROS 2 drive interface와
`pinky_drive_manager` MVP 구현을 포함한다.

현재 로컬 개발 환경에서는 코드 작성만 수행하고, 실제 빌드/실행은 Ubuntu ROS 2
환경에서 진행하는 것을 전제로 한다.

## Workspace 구조

```text
src/
  pinky_drive_msgs/          # RMF <-> Pinky drive interface msg/action/srv
  pinky_drive_manager/       # 현재 사용 패키지
  pinky_drive_manager_old/   # 과거 PoC 참조 코드, COLCON_IGNORE 처리됨
```

`pinky_drive_manager_old`는 동일한 패키지명을 가진 PoC 코드라서 colcon 빌드
충돌을 피하기 위해 `COLCON_IGNORE`가 들어 있다. 실제 실행 대상은
`pinky_drive_manager`이다.

## 사전 조건

Ubuntu ROS 2 환경에서 아래가 준비되어 있어야 한다.

- ROS 2와 colcon
- Nav2 stack
- 각 Pinky별 Nav2 `NavigateToPose` action server
- 각 Pinky별 TF: `map_frame -> robot_frame`
- 선택 사항: 배터리 topic, emergency topic

예시는 ROS 2 Jazzy 기준이다. 다른 ROS 2 배포판을 쓰면 `jazzy` 부분을 해당
배포판 이름으로 바꾼다.

```bash
source /opt/ros/jazzy/setup.bash

sudo apt update
sudo apt install -y python3-colcon-common-extensions python3-rosdep

sudo rosdep init 2>/dev/null || true
rosdep update
```

## 의존성 설치와 빌드

```bash
cd pinky_drive_ws
source /opt/ros/jazzy/setup.bash

rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install

source install/setup.bash
```

새 터미널을 열 때마다 아래를 다시 실행한다.

```bash
source /opt/ros/jazzy/setup.bash
cd pinky_drive_ws
source install/setup.bash
```

## 실행 전 확인 사항

drive manager는 RMF-facing API만 제공하고, 실제 이동은 각 로봇 namespace의
Nav2로 위임한다. 기본 설정에서는 `pinky1` 기준 아래 리소스를 기대한다.

| 항목 | 기본 이름 |
|---|---|
| Drive API namespace | `/pinky1/drive` |
| Nav2 action | `/pinky1/navigate_to_pose` |
| TF | `map -> pinky1/base_link` |
| Battery topic | `/pinky1/battery/percent` |
| Emergency topic | `/pinky1/emergency` |
| Follow event topic | `/pinky1/drive/internal/follow_event` |

Nav2와 TF가 준비되지 않으면 drive manager는 `unknown` 상태를 publish한다.

```bash
ros2 action list | grep navigate_to_pose
ros2 run tf2_ros tf2_echo map pinky1/base_link
```

## 단일 로봇 실행

```bash
ros2 launch pinky_drive_manager drive_manager.launch.py \
  robot_name:=pinky1 \
  drive_namespace:=/pinky1/drive \
  robot_namespace:=pinky1 \
  rmf_level:=L1
```

시뮬레이션 시간을 쓰는 경우:

```bash
ros2 launch pinky_drive_manager drive_manager.launch.py \
  robot_name:=pinky1 \
  drive_namespace:=/pinky1/drive \
  robot_namespace:=pinky1 \
  rmf_level:=L1 \
  use_sim_time:=true
```

## 멀티로봇 실행

기본 예시는 `pinky1`, `pinky2` 두 대를 실행한다.

```bash
ros2 launch pinky_drive_manager multi_drive_manager.launch.py \
  robot_names:=pinky1,pinky2 \
  drive_namespace_format:="/{robot_name}/drive" \
  robot_namespace_format:="{robot_name}" \
  rmf_level:=L1
```

이렇게 실행하면 RMF-facing API는 다음처럼 생성된다.

```text
/pinky1/drive/state
/pinky1/drive/navigate
/pinky1/drive/stop

/pinky2/drive/state
/pinky2/drive/navigate
/pinky2/drive/stop
```

## 설정 파일

기본 설정 파일:

```text
src/pinky_drive_manager/config/pinky_drive_manager.yaml
```

주요 설정:

| 키 | 의미 |
|---|---|
| `rmf_level` | RMF map/level 이름. 기본 `L1` |
| `map_frame` | pose 기준 map frame. 기본 `map` |
| `robot_frame` | 로봇 base frame. 기본 `{robot_name}/base_link` |
| `robot_namespace` | Nav2, battery, emergency가 있는 로봇 namespace |
| `nav2_action` | robot namespace 아래 Nav2 action 이름 |
| `battery_percent_topic` | battery SOC topic. `0.0~1.0` 또는 `0~100` 허용 |
| `emergency_topic` | emergency input topic |
| `follow_event_topic` | 추후 follower 노드가 상태 전이를 요청할 내부 topic |
| `allow_blocked_retry` | `blocked` 상태에서 RMF retry navigation 허용 여부 |
| `state_publish_frequency` | `/drive/state` publish 주기 |

패키지 설치 후 다른 config를 쓰려면:

```bash
ros2 launch pinky_drive_manager multi_drive_manager.launch.py \
  config_file:=/path/to/pinky_drive_manager.yaml \
  robot_names:=pinky1,pinky2
```

## 동작 확인 명령

상태 확인:

```bash
ros2 topic echo /pinky1/drive/state
```

navigation goal 전송:

```bash
ros2 action send_goal /pinky1/drive/navigate pinky_drive_msgs/action/Navigate \
  "{robot_name: 'pinky1', map_name: 'L1', x: 1.0, y: 2.0, yaw: 0.0, speed_limit: 0.0, request_id: 'manual-test-001', destination_name: 'test', command_mode: 'task'}" \
  --feedback
```

returning goal 전송:

```bash
ros2 action send_goal /pinky1/drive/navigate pinky_drive_msgs/action/Navigate \
  "{robot_name: 'pinky1', map_name: 'L1', x: 0.0, y: 0.0, yaw: 0.0, speed_limit: 0.0, request_id: 'manual-return-001', destination_name: 'home', command_mode: 'returning'}" \
  --feedback
```

정지:

```bash
ros2 service call /pinky1/drive/stop pinky_drive_msgs/srv/Stop \
  "{robot_name: 'pinky1', request_id: 'manual-stop-001'}"
```

emergency on/off 테스트:

```bash
ros2 topic pub --once /pinky1/emergency std_msgs/msg/Bool "{data: true}"
ros2 topic pub --once /pinky1/emergency std_msgs/msg/Bool "{data: false}"
```

following 상태 전이 테스트:

```bash
ros2 topic pub --once /pinky1/drive/internal/follow_event std_msgs/msg/String \
  "{data: 'follow_start'}"

ros2 topic pub --once /pinky1/drive/internal/follow_event std_msgs/msg/String \
  "{data: 'target_lost_timeout'}"

ros2 topic pub --once /pinky1/drive/internal/follow_event std_msgs/msg/String \
  "{data: 'follow_stop'}"
```

## RMF-facing 인터페이스

각 로봇은 아래 namespace를 제공한다.

```text
/{robot_name}/drive
```

| 인터페이스 | 타입 |
|---|---|
| `/{robot_name}/drive/state` | `pinky_drive_msgs/msg/DriveState` |
| `/{robot_name}/drive/navigate` | `pinky_drive_msgs/action/Navigate` |
| `/{robot_name}/drive/stop` | `pinky_drive_msgs/srv/Stop` |

자세한 계약은 [docs/rmf_pinky_drive_interface.md](../docs/rmf_pinky_drive_interface.md)를
참고한다.

## 문제 확인 포인트

`state == unknown`이 계속 유지되면 아래를 확인한다.

```bash
ros2 action list | grep /pinky1/navigate_to_pose
ros2 run tf2_ros tf2_echo map pinky1/base_link
ros2 topic echo /pinky1/drive/state
```

`Navigate` goal이 reject되면 보통 아래 중 하나다.

- `robot_name` 또는 `map_name` 불일치
- `request_id` 누락
- Nav2 action server 미준비
- TF 미준비
- 현재 상태가 `navigating`, `following`, `emergency`, `unknown`

MVP 단계에서는 Nav2 실패와 goal reject를 public state `blocked`로 매핑한다. 정밀주차,
YOLO 기반 사람 추종, follower stop service 연동은 이후 노드가 추가될 때
`drive_manager_node.py`의 TODO 지점에 연결한다.
