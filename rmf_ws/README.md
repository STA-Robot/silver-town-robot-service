# RMF Workspace

이 workspace는 RMF map, navigation graph, 공통 workflow orchestrator,
Pinky fleet adapter 설정과 adapter 코드를 담는다.

실제 로봇 drive API는 `../pinky_drive_ws`의 `pinky_drive_manager`가 제공하고,
이 workspace의 adapter는 RMF domain에서 보이는 `/pinkyX/command`, `/pinkyX/state`
topic으로 각 로봇과 통신한다. Pinky local domain의 `/command`, `/state`와 RMF
domain의 로봇별 topic은 `domain_bridge`가 remap한다.

## 디렉토리 구조

```text
rmf_ws/
  src/
    rmf_maps/
      maps/
        rmf-test.building.yaml       # traffic-editor/building map 원본
      nav_graphs/
        0.yaml                       # RMF fleet adapter가 사용하는 nav graph

    pinky_rmf_adapter/
      config/
        pinky_adapter.yaml           # fleet, robot, coordinate transform 설정
        pinky1_domain_bridge.yaml      # RMF domain 31 <-> pinky1 domain 32 bridge
        pinky2_domain_bridge.yaml      # RMF domain 31 <-> pinky2 domain 33 bridge
      launch/
        pinky_domain_bridges.launch.py
        pinky_fleet_adapter.launch.py
      pinky_rmf_adapter/
        pinky_fleet_adapter.py        # Open-RMF fleet adapter
        RobotClientAPI.py            # Pinky drive API 연결 구현 위치

    task_msgs/
      srv/
        TableCall.srv                # table call service interface
        FollowCall.srv               # 특정 Pinky follow 시작 service interface
        CancelFollow.srv             # follow task 취소 service interface

    task_orchestrator/
      config/
        task_orchestrator.yaml       # task API, fleet, workflow 기본 설정
      launch/
        task_orchestrator.launch.py
      task_orchestrator/
        task_orchestrator.py   # table/follow call, mission, warehouse orchestration

    rmf_bringup/
      launch/
        rmf_core.launch.py           # RMF schedule, task dispatcher, map server 실행
        rmf.launch.py                # RMF core, adapter, orchestrator 통합 실행
```

## 패키지 역할

| 패키지 | 역할 |
|---|---|
| `rmf_maps` | building map 원본과 생성된 nav graph를 보관하고 install한다. |
| `pinky_rmf_adapter` | Pinky fleet adapter 코드와 adapter 설정을 보관한다. |
| `task_msgs` | task orchestrator 외부 입력용 service interface를 제공한다. |
| `task_orchestrator` | table call과 follow call을 RMF task로 제출하고 mission workflow를 관리한다. |
| `rmf_bringup` | RMF core, adapter, task orchestrator launch를 묶는다. |

## YAML 파일 위치

PoC 때 루트에 있던 파일은 아래처럼 옮겼다.

| 기존 파일 | 새 위치 |
|---|---|
| `rmf-test.building.yaml` | `src/rmf_maps/maps/rmf-test.building.yaml` |
| `0.yaml` | `src/rmf_maps/nav_graphs/0.yaml` |
| `pinky_adapter.yaml` | `src/pinky_rmf_adapter/config/pinky_adapter.yaml` |

`rmf-test.building.yaml` 안의 drawing image는 `../maps/test_map.png`를 참조한다.
실제 Ubuntu 실행 환경에서는 해당 이미지도 `src/rmf_maps/maps/test_map.png`에
두면 된다.

## 빌드

ROS 2 Jazzy 기준:

```bash
source /opt/ros/jazzy/setup.bash

# 저장소 루트 기준
cd pinky_drive_ws
colcon build --symlink-install
source install/setup.bash

cd ../rmf_ws
rosdep install --from-paths src --ignore-src -r -y --skip-keys pinky_drive_msgs
colcon build --symlink-install

source install/setup.bash
```

새 터미널을 열 때마다 `pinky_drive_ws`를 먼저 source한 뒤 `rmf_ws`를 source한다.

```bash
source /opt/ros/jazzy/setup.bash
cd rmf_ws
source ../pinky_drive_ws/install/setup.bash
source install/setup.bash
```

## 실행 흐름

1. 각 Pinky local domain에서 Nav2와 `pinky_drive_manager`를 실행한다.
   - pinky1 예: `ROS_DOMAIN_ID=32`
   - pinky2 예: `ROS_DOMAIN_ID=33`
2. RMF domain에서 domain bridge를 실행한다.
3. RMF domain에서 `rmf_bringup` 통합 launch를 실행한다.
   - 기본으로 RMF schedule node, task dispatcher, building map server를 함께 실행한다.
   - 이어서 fleet adapter와 task orchestrator를 실행한다.

### Domain Bridge

기본 domain 배치는 아래를 가정한다.

| 대상 | ROS_DOMAIN_ID | local topic | RMF domain topic |
|---|---:|---|---|
| RMF | 31 | - | - |
| pinky1 | 32 | `/command`, `/state` | `/pinky1/command`, `/pinky1/state` |
| pinky2 | 33 | `/command`, `/state` | `/pinky2/command`, `/pinky2/state` |

bridge 설정 파일은 `pinky_rmf_adapter/config`에 있다.

| 파일 | 의미 |
|---|---|
| `pinky1_domain_bridge.yaml` | RMF domain 31과 pinky1 domain 32 연결 |
| `pinky2_domain_bridge.yaml` | RMF domain 31과 pinky2 domain 33 연결 |

`reversed: true`는 bridge 방향을 뒤집는다. 예를 들어 pinky1 설정에서:

```yaml
from_domain: 31
to_domain: 32

topics:
  pinky1/command:
    type: pinky_drive_msgs/msg/DriveCommand
    remap: command

  state:
    type: pinky_drive_msgs/msg/DriveState
    remap: pinky1/state
    reversed: true
```

의미는 아래와 같다.

```text
31 /pinky1/command -> 32 /command
32 /state          -> 31 /pinky1/state
```

bridge launch 사용법:

```bash
cd rmf_ws
source ../pinky_drive_ws/install/setup.bash
source install/setup.bash

ros2 launch pinky_rmf_adapter pinky_domain_bridges.launch.py
```

개별 설정 파일로 직접 실행할 수도 있다.

```bash
ros2 run domain_bridge domain_bridge \
  src/pinky_rmf_adapter/config/pinky1_domain_bridge.yaml

ros2 run domain_bridge domain_bridge \
  src/pinky_rmf_adapter/config/pinky2_domain_bridge.yaml
```

bridge 확인:

```bash
ROS_DOMAIN_ID=31 ros2 topic list | grep pinky
ROS_DOMAIN_ID=31 ros2 topic echo /pinky1/state
```

`pinky_rmf_adapter`는 Open-RMF fleet adapter 역할을 맡고, `RobotClientAPI.py`는
RMF domain의 `/pinkyX/command` publisher와 `/pinkyX/state` subscriber를 사용해
Pinky drive manager와 통신한다. `task_orchestrator`는 별도 패키지이며
RMF task API service에 table collection/warehouse task를 제출한다.

RMF core만 실행하려면 아래 launch를 사용한다.

```bash
ros2 launch rmf_bringup rmf_core.launch.py
```

이 launch가 기본으로 실행하는 노드는 아래와 같다.

| 노드 | 패키지 / executable | 역할 |
|---|---|---|
| `rmf_traffic_schedule` | `rmf_traffic_ros2` / `rmf_traffic_schedule` | RMF traffic schedule database |
| `rmf_task_dispatcher` | `rmf_task_ros2` / `rmf_task_dispatcher` | `/submit_task` task 접수/dispatch |
| `building_map_server` | `rmf_building_map_tools` / `building_map_server` | building map service 제공 |

fleet adapter만 실행하려면 아래 launch를 사용한다. 이 경우 RMF schedule node는
이미 실행 중이어야 한다.

```bash
ros2 launch pinky_rmf_adapter pinky_fleet_adapter.launch.py \
  config_file:=$(ros2 pkg prefix pinky_rmf_adapter)/share/pinky_rmf_adapter/config/pinky_adapter.yaml \
  nav_graph_file:=$(ros2 pkg prefix rmf_maps)/share/rmf_maps/nav_graphs/0.yaml
```

통합 bringup launch는 RMF core를 먼저 띄운 뒤 adapter와 task orchestrator를 함께
실행한다.

```bash
ros2 launch rmf_bringup rmf.launch.py
```

이미 다른 launch에서 RMF core를 띄웠다면 core 포함을 끌 수 있다.

```bash
ros2 launch rmf_bringup rmf.launch.py use_rmf_core:=false
```

개별 core 노드를 끄거나 adapter 시작 지연 시간을 조정할 수도 있다.

```bash
ros2 launch rmf_bringup rmf.launch.py \
  use_building_map_server:=false \
  adapter_start_delay:=5.0
```

core만 통합 launch 안에서 확인하고 싶으면 adapter와 orchestrator를 끈다.

```bash
ros2 launch rmf_bringup rmf.launch.py \
  use_fleet_adapter:=false \
  use_task_orchestrator:=false
```

task orchestrator의 dispatch/task 상태 흐름을 자세히 보려면 debug 로그를 켠다.

```bash
ros2 launch rmf_bringup rmf.launch.py \
  task_orchestrator_log_level:=debug
```

### Table Call Service

task orchestrator는 단일 테이블 호출 입력으로 `/table_call` service를 제공한다.
요청을 받으면 table collection RMF task를 `/submit_task`로 제출하고,
응답으로 orchestrator가 만든 `mission_id`를 반환한다. `table_waypoint`를 비우면
`table_id`와 같은 waypoint로 처리한다. `wait_seconds`가 `0`이면 orchestrator 기본
대기 시간을 사용한다.

```bash
ros2 service call /table_call task_msgs/srv/TableCall \
  "{table_id: 'tent_1', table_waypoint: 'tent_1', wait_seconds: 20}"
```

기본 waypoint/default wait 설정을 쓰는 호출:

```bash
ros2 service call /table_call task_msgs/srv/TableCall \
  "{table_id: 'tent_1', table_waypoint: '', wait_seconds: 0}"
```

table collection task를 one-shot으로 직접 제출하려면 task orchestrator executable을 사용할 수 있다.

```bash
ros2 run task_orchestrator task_orchestrator --table-waypoint tent_1
```

one-shot 실행에서 debug 로그를 보려면 ROS log level을 넘긴다.

```bash
ros2 run task_orchestrator task_orchestrator \
  --table-waypoint tent_1 \
  --ros-args --log-level task_orchestrator:=debug
```

### Follow Service

task orchestrator는 특정 Pinky에게 사람 추종을 시작시키는 `/follow_call` service를
제공한다. 요청을 받으면 해당 로봇에 대한 RMF `robot_task_request`를 제출하고,
fleet adapter는 compose task의 `perform_action` category `follow`를
`DriveCommand(command_type=follow)`로 변환해 Pinky drive manager에 전달한다.

```bash
ros2 service call /follow_call task_msgs/srv/FollowCall \
  "{robot_name: 'pinky1'}"
```

follow 상태 확인:

```bash
ros2 topic echo /pinky1/state
```

정상 수락되면 `state=following`, `last_command_status=accepted`가 publish된다.
현재 follow 동작 자체는 Pinky drive manager의 follower/person-tracking 연동 지점에
연결될 예정이다.

follow를 중단하려면 `/cancel_follow_call` service를 호출한다. orchestrator는
`/follow_call`로 제출한 follow task의 RMF `task_id`를 로봇별로 추적하고,
cancel 요청 시 RMF Task API에 `cancel_task_request`를 보낸다.

```bash
ros2 service call /cancel_follow_call task_msgs/srv/CancelFollow \
  "{robot_name: 'pinky1'}"
```

cancel이 받아들여지면 RMF가 실행 중인 follow task를 취소하고 adapter의 stop 경로를
호출한다. 이후 `pinky_adapter.yaml`의 `finishing_request: park` 설정에 따라 RMF가
자동으로 parking/returning 동작을 이어간다.

## 구현 메모

### Adapter

adapter 구현 시 우선 연결할 인터페이스:

| RMF adapter 쪽 | Pinky drive manager 쪽 |
|---|---|
| robot state polling/update | RMF domain `/{robot_name}/state` subscribe |
| navigation command | RMF domain `/{robot_name}/command` publish, `command_type=navigate` |
| returning command | RMF domain `/{robot_name}/command` publish, `command_type=returning` |
| follow command | RMF domain `/{robot_name}/command` publish, `command_type=follow` |
| stop/cancel command | RMF domain `/{robot_name}/command` publish, `command_type=stop` |

좌표 변환은 `pinky_adapter.yaml`의 `reference_coordinates`를 기준으로 처리한다.
RMF level 이름은 현재 `L1`이다.
