# Pinky RMF Workspace

이 workspace는 Pinky fleet을 RMF에 붙이기 위한 map, navigation graph, fleet
adapter 설정과 adapter 코드를 담는다.

실제 로봇 drive API는 `../pinky_drive_ws`의 `pinky_drive_manager`가 제공하고,
이 workspace의 adapter는 RMF domain에서 보이는 `/pinkyX/command`, `/pinkyX/state`
topic으로 각 로봇과 통신한다. Pinky local domain의 `/command`, `/state`와 RMF
domain의 로봇별 topic은 `domain_bridge`가 remap한다.

## 디렉토리 구조

```text
rmf_ws/
  src/
    pinky_rmf_maps/
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
        fleet_adapter.py             # Open-RMF fleet adapter template
        RobotClientAPI.py            # Pinky drive API 연결 구현 위치
```

## 패키지 역할

| 패키지 | 역할 |
|---|---|
| `pinky_rmf_maps` | building map 원본과 생성된 nav graph를 보관하고 install한다. |
| `pinky_rmf_adapter` | Pinky fleet adapter 코드와 adapter 설정을 보관한다. |

## YAML 파일 위치

PoC 때 루트에 있던 파일은 아래처럼 옮겼다.

| 기존 파일 | 새 위치 |
|---|---|
| `rmf-test.building.yaml` | `src/pinky_rmf_maps/maps/rmf-test.building.yaml` |
| `0.yaml` | `src/pinky_rmf_maps/nav_graphs/0.yaml` |
| `pinky_adapter.yaml` | `src/pinky_rmf_adapter/config/pinky_adapter.yaml` |

`rmf-test.building.yaml` 안의 drawing image는 `../maps/test_map.png`를 참조한다.
실제 Ubuntu 실행 환경에서는 해당 이미지도 `src/pinky_rmf_maps/maps/test_map.png`에
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
3. RMF core와 schedule 관련 노드가 준비된 상태에서 fleet adapter를 실행한다.

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

`pinky_rmf_adapter`에는 Open-RMF
[`fleet_adapter_template`](https://github.com/open-rmf/fleet_adapter_template/tree/main/fleet_adapter_template/fleet_adapter_template)
의 기본 템플릿 코드가 들어 있다. `RobotClientAPI.py`는 다음 단계에서
`/pinkyX/command` publisher와 `/pinkyX/state` subscriber를 사용하도록 연결한다.

fleet adapter launch를 실행한다.

```bash
ros2 launch pinky_rmf_adapter pinky_fleet_adapter.launch.py \
  config_file:=$(ros2 pkg prefix pinky_rmf_adapter)/share/pinky_rmf_adapter/config/pinky_adapter.yaml \
  nav_graph_file:=$(ros2 pkg prefix pinky_rmf_maps)/share/pinky_rmf_maps/nav_graphs/0.yaml
```

## 구현 메모

### Adapter

adapter 구현 시 우선 연결할 인터페이스:

| RMF adapter 쪽 | Pinky drive manager 쪽 |
|---|---|
| robot state polling/update | RMF domain `/{robot_name}/state` subscribe |
| navigation command | RMF domain `/{robot_name}/command` publish, `command_type=navigate` |
| returning command | RMF domain `/{robot_name}/command` publish, `command_type=returning` |
| stop/cancel command | RMF domain `/{robot_name}/command` publish, `command_type=stop` |

좌표 변환은 `pinky_adapter.yaml`의 `reference_coordinates`를 기준으로 처리한다.
RMF level 이름은 현재 `L1`이다.
