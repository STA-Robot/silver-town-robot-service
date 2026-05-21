# Pinky Drive Workspace

이 저장소는 Pinky 로봇을 RMF에서 제어하기 위한 ROS 2 drive interface와
`pinky_drive_manager` MVP 구현을 포함한다.

현재 로컬 개발 환경에서는 코드 작성만 수행하고, 실제 빌드/실행은 Ubuntu ROS 2
환경에서 진행하는 것을 전제로 한다.

## Workspace 구조

```text
src/
  pinky_drive_msgs/          # RMF <-> Pinky drive interface msg
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

drive manager는 각 Pinky의 `ROS_DOMAIN_ID` 안에서 실행된다. 로봇 구분은 ROS
namespace가 아니라 domain bridge remap으로 처리한다. 따라서 Pinky domain 내부에서
기본 리소스 이름은 아래처럼 단순하다.

| 항목 | 기본 이름 |
|---|---|
| Command topic | `/command` |
| State topic | `/state` |
| Nav2 action | `/navigate_to_pose` |
| TF | `map -> base_link` |
| Battery topic | `/battery/percent` |
| Emergency topic | `/emergency` |
| Follow event topic | `/internal/follow_event` |

RMF domain에서는 domain bridge가 로봇별 topic으로 remap한다.

```text
RMF domain 31:     /pinky1/command  ->  pinky1 domain 32: /command
RMF domain 31:     /pinky1/state    <-  pinky1 domain 32: /state
RMF domain 31:     /pinky2/command  ->  pinky2 domain 33: /command
RMF domain 31:     /pinky2/state    <-  pinky2 domain 33: /state
```

Nav2와 TF가 준비되어 있는지 Pinky domain에서 확인한다.

```bash
ROS_DOMAIN_ID=32 ros2 action list | grep /navigate_to_pose
ROS_DOMAIN_ID=32 ros2 run tf2_ros tf2_echo map base_link
```

## 단일 로봇 실행

각 Pinky domain에서 drive manager를 하나씩 실행한다.

pinky1:

```bash
cd pinky_drive_ws
source /opt/ros/jazzy/setup.bash
source install/setup.bash

ROS_DOMAIN_ID=32 ros2 launch pinky_drive_manager drive_manager.launch.py \
  robot_name:=pinky1 \
  rmf_level:=L1
```

pinky2:

```bash
cd pinky_drive_ws
source /opt/ros/jazzy/setup.bash
source install/setup.bash

ROS_DOMAIN_ID=33 ros2 launch pinky_drive_manager drive_manager.launch.py \
  robot_name:=pinky2 \
  rmf_level:=L1
```

시뮬레이션 시간을 쓰는 경우:

```bash
ROS_DOMAIN_ID=32 ros2 launch pinky_drive_manager drive_manager.launch.py \
  robot_name:=pinky1 \
  rmf_level:=L1 \
  use_sim_time:=true
```

## 멀티로봇 실행

기본 domain bridge 구조에서는 `multi_drive_manager.launch.py`를 사용하지 않는 것을
권장한다. drive manager가 `/command`, `/state` 같은 절대 topic을 쓰기 때문에 같은
`ROS_DOMAIN_ID` 안에서 여러 drive manager를 띄우면 topic이 충돌할 수 있다.

디버그 목적으로 같은 domain에 여러 노드를 띄워야 할 때만 사용한다.

```bash
ROS_DOMAIN_ID=32 ros2 launch pinky_drive_manager multi_drive_manager.launch.py \
  robot_names:=pinky1,pinky2 \
  rmf_level:=L1
```

실제 멀티로봇 운용은 각 로봇을 별도 domain에서 단일 launch로 실행한다.

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
| `robot_frame` | 로봇 base frame. 기본 `base_link` |
| `command_topic` | RMF command를 받는 Pinky domain 내부 topic. 기본 `/command` |
| `state_topic` | drive state를 publish하는 Pinky domain 내부 topic. 기본 `/state` |
| `nav2_action` | Pinky domain 내부 Nav2 action 이름. 기본 `/navigate_to_pose` |
| `battery_percent_topic` | battery SOC topic. `0.0~1.0` 또는 `0~100` 허용 |
| `emergency_topic` | emergency input topic |
| `follow_event_topic` | follower 노드가 상태 전이를 알려주는 내부 topic |
| `state_publish_frequency` | `/state` publish 주기 |

패키지 설치 후 다른 config를 쓰려면:

```bash
ROS_DOMAIN_ID=32 ros2 launch pinky_drive_manager drive_manager.launch.py \
  config_file:=/path/to/pinky_drive_manager.yaml \
  robot_name:=pinky1
```

## 동작 확인 명령

아래 명령은 Pinky domain 내부에서 직접 테스트하는 예시다. RMF domain에서 테스트할
때는 domain bridge remap 이후의 `/pinky1/command`, `/pinky1/state`를 사용한다.

상태 확인:

```bash
ROS_DOMAIN_ID=32 ros2 topic echo /state
```

navigation command 전송:

```bash
ROS_DOMAIN_ID=32 ros2 topic pub --once /command pinky_drive_msgs/msg/DriveCommand \
  "{robot_name: 'pinky1', command_id: 'manual-nav-001', command_type: 'navigate', map_name: 'L1', x: 1.0, y: 2.0, yaw: 0.0, speed_limit: 0.0, target_name: 'test', payload_json: ''}"
```

returning command 전송:

```bash
ROS_DOMAIN_ID=32 ros2 topic pub --once /command pinky_drive_msgs/msg/DriveCommand \
  "{robot_name: 'pinky1', command_id: 'manual-return-001', command_type: 'returning', map_name: 'L1', x: 0.0, y: 0.0, yaw: 0.0, speed_limit: 0.0, target_name: 'home', payload_json: ''}"
```

follow command 전송:

```bash
ROS_DOMAIN_ID=32 ros2 topic pub --once /command pinky_drive_msgs/msg/DriveCommand \
  "{robot_name: 'pinky1', command_id: 'manual-follow-001', command_type: 'follow', map_name: 'L1', target_name: 'person', payload_json: ''}"
```

정지:

```bash
ROS_DOMAIN_ID=32 ros2 topic pub --once /command pinky_drive_msgs/msg/DriveCommand \
  "{robot_name: 'pinky1', command_id: 'manual-stop-001', command_type: 'stop', map_name: 'L1'}"
```

emergency on/off 테스트:

```bash
ROS_DOMAIN_ID=32 ros2 topic pub --once /emergency std_msgs/msg/Bool "{data: true}"
ROS_DOMAIN_ID=32 ros2 topic pub --once /emergency std_msgs/msg/Bool "{data: false}"
```

following 상태 이벤트 테스트:

```bash
ROS_DOMAIN_ID=32 ros2 topic pub --once /internal/follow_event std_msgs/msg/String \
  "{data: 'start'}"

ROS_DOMAIN_ID=32 ros2 topic pub --once /internal/follow_event std_msgs/msg/String \
  "{data: 'blocked'}"

ROS_DOMAIN_ID=32 ros2 topic pub --once /internal/follow_event std_msgs/msg/String \
  "{data: 'done'}"
```

## RMF-facing 인터페이스

Pinky domain 내부 drive manager는 `/command`, `/state`만 제공한다. RMF domain에서는
domain bridge remap을 통해 로봇별 topic으로 보이게 한다.

| RMF domain topic | Pinky domain topic | 타입 |
|---|---|---|
| `/pinky1/command` | `/command` | `pinky_drive_msgs/msg/DriveCommand` |
| `/pinky1/state` | `/state` | `pinky_drive_msgs/msg/DriveState` |
| `/pinky2/command` | `/command` | `pinky_drive_msgs/msg/DriveCommand` |
| `/pinky2/state` | `/state` | `pinky_drive_msgs/msg/DriveState` |

자세한 계약은 [docs/rmf_pinky_drive_interface.md](../docs/rmf_pinky_drive_interface.md)를
참고한다.

## 문제 확인 포인트

`state == unknown`이 계속 유지되면 Pinky domain에서 아래를 확인한다.

```bash
ROS_DOMAIN_ID=32 ros2 action list | grep /navigate_to_pose
ROS_DOMAIN_ID=32 ros2 run tf2_ros tf2_echo map base_link
ROS_DOMAIN_ID=32 ros2 topic echo /state
```

command가 `rejected`가 되면 보통 아래 중 하나다.

- `robot_name` 또는 `map_name` 불일치
- `command_id` 누락
- emergency 상태에서 `navigate`, `returning`, `follow` 요청
- 다른 command가 이미 active 상태
- 현재 `returning`이 아닌 motion 중 새 일반 command 요청

Nav2 action server가 준비되지 않았거나 Nav2가 goal을 실패시키면 public state는
`blocked`가 되고, `last_command_status`는 `failed` 또는 `rejected`로 publish된다.
정밀주차, YOLO 기반 사람 추종, follower stop 연동은 이후 노드가 추가될 때
`drive_manager_node.py`의 TODO 지점에 연결한다.
