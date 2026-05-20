# Pinky RMF Workspace

이 workspace는 Pinky fleet을 RMF에 붙이기 위한 map, navigation graph, fleet
adapter 설정과 adapter 코드를 담는다.

실제 로봇 drive API는 `../pinky_drive_ws`의 `pinky_drive_manager`가 제공하고,
이 workspace의 adapter는 RMF 명령을 각 로봇의 `/pinkyX/drive/*` API로 연결한다.

## 디렉토리 구조

```text
rmf_ws/
  src/
    site_config/
      config/
        site.template.yaml           # 새 site config를 만들 때 복사하는 템플릿
        rmf_test.site.yaml           # 사람이 직접 수정하는 단일 SoT
      site_config/
        generate_configs.py          # SoT에서 runtime config 생성

    pinky_rmf_maps/
      maps/
        rmf-test.building.yaml       # traffic-editor/building map 원본
      nav_graphs/
        0.yaml                       # RMF fleet adapter가 사용하는 nav graph

    pinky_rmf_adapter/
      config/
        pinky_adapter.yaml           # fleet, robot, coordinate transform 설정
      launch/
        pinky_fleet_adapter.launch.py
      pinky_rmf_adapter/
        fleet_adapter.py             # Open-RMF fleet adapter template
        RobotClientAPI.py            # Pinky drive API 연결 구현 위치

    pinky_task_orchestrator/
      config/
        task_orchestrator.yaml       # 상위 workflow/location/task dispatch 설정
      launch/
        task_orchestrator.launch.py
      pinky_task_orchestrator/
        task_orchestrator_node.py    # 호출/대기/적재/배송 등 상위 task 흐름 관리
        states.py                    # app-level workflow state enum

    pinky_rmf_bringup/
      launch/
        pinky_rmf.launch.py          # map/nav graph/config 경로를 묶는 실행 진입점
```

## 패키지 역할

| 패키지 | 역할 |
|---|---|
| `site_config` | site/fleet/robot/location/workflow 정보를 담는 단일 source of truth와 config generator를 제공한다. |
| `pinky_rmf_maps` | building map 원본과 생성된 nav graph를 보관하고 install한다. |
| `pinky_rmf_adapter` | Pinky fleet adapter 코드와 adapter 설정을 보관한다. |
| `pinky_task_orchestrator` | 호출, 적재 대기, 배송, 복귀 같은 상위 task workflow를 관리하고 RMF task dispatch를 담당한다. |
| `pinky_rmf_bringup` | 테스트/운영 실행에 필요한 launch 조합을 제공한다. |

## Site Config SoT

사람이 직접 수정하는 기준 파일은 하나로 둔다.

```text
src/site_config/config/rmf_test.site.yaml
```

새 site 설정은 템플릿을 복사해서 만든다.

```bash
cd rmf_ws
cp src/site_config/config/site.template.yaml \
  src/site_config/config/<site_name>.site.yaml
```

템플릿에는 각 필드에 어떤 값을 넣어야 하는지 주석이 들어 있다.

아래 파일들은 `rmf_test.site.yaml`에서 생성되는 runtime config로 취급한다.

| 생성 파일 | 사용 패키지 |
|---|---|
| `src/pinky_rmf_adapter/config/pinky_adapter.yaml` | `pinky_rmf_adapter` |
| `src/pinky_task_orchestrator/config/task_orchestrator.yaml` | `pinky_task_orchestrator` |

로봇 추가, fleet 설정 변경, waypoint/location 변경, task workflow 변경은 먼저
`rmf_test.site.yaml`에 반영하고 generator를 실행한다.

```bash
cd rmf_ws
ros2 run site_config generate_configs
```

빌드 전 source가 안 된 상태에서 소스 트리의 스크립트를 직접 실행하려면:

```bash
cd rmf_ws
python3 src/site_config/site_config/generate_configs.py
```

generator는 필수 값이 없으면 조용히 기본값을 넣지 않고 에러를 낸다. 예를 들어
각 robot에는 `rmf_level`, `charger`, `drive_namespace`가 반드시 있어야 한다.
`fleet.robots.<robot_name>` 아래에 추가한 robot 특성은 `rmf_level`,
`drive_namespace`, `drive_api`를 제외하고 generated `pinky_adapter.yaml`의
`rmf_fleet.robots.<robot_name>` 아래로 보존된다.

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

1. 각 Pinky의 Nav2와 `pinky_drive_manager`를 실행한다.
2. `/pinky1/drive/state`, `/pinky1/drive/navigate`, `/pinky1/drive/stop`이 보이는지 확인한다.
3. RMF core와 schedule/task 관련 노드가 준비된 상태에서 fleet adapter와 task orchestrator를 실행한다.

`pinky_rmf_adapter`에는 Open-RMF
[`fleet_adapter_template`](https://github.com/open-rmf/fleet_adapter_template/tree/main/fleet_adapter_template/fleet_adapter_template)
의 기본 템플릿 코드가 들어 있다. 아직 `RobotClientAPI.py`의 로봇별 API 함수들은
템플릿 TODO 상태이므로, 다음 단계에서 Pinky drive manager의 ROS 2
topic/action/service로 연결해야 한다.

아래 launch를 실행 진입점으로 사용한다.

```bash
ros2 launch pinky_rmf_bringup pinky_rmf.launch.py
```

task orchestrator를 제외하고 fleet adapter만 띄우려면:

```bash
ros2 launch pinky_rmf_bringup pinky_rmf.launch.py use_task_orchestrator:=false
```

직접 adapter launch만 실행할 수도 있다.

```bash
ros2 launch pinky_rmf_adapter pinky_fleet_adapter.launch.py \
  config_file:=$(ros2 pkg prefix pinky_rmf_adapter)/share/pinky_rmf_adapter/config/pinky_adapter.yaml \
  nav_graph_file:=$(ros2 pkg prefix pinky_rmf_maps)/share/pinky_rmf_maps/nav_graphs/0.yaml
```

## 구현 메모

### State 계층

`pinky_drive_manager`의 `DriveState.state`는 로봇의 물리 주행 상태이다.

```text
idle, navigating, returning, following, blocked, emergency
```

`pinky_task_orchestrator`의 workflow state는 서비스/업무 흐름 상태이다.

```text
called, moving_to_pickup, waiting_for_load, moving_to_dropoff, waiting_for_unload, returning
```

따라서 RMF adapter는 로봇 주행 계약을 책임지고, task orchestrator는 사용자 호출,
적재/하차 대기, RMF task 생성, task 완료/실패에 따른 다음 단계를 책임진다.

### Adapter

adapter 구현 시 우선 연결할 인터페이스:

| RMF adapter 쪽 | Pinky drive manager 쪽 |
|---|---|
| robot state polling/update | `/{robot_name}/drive/state` subscribe |
| navigation command | `/{robot_name}/drive/navigate` action client |
| stop/cancel command | `/{robot_name}/drive/stop` service client |

좌표 변환은 `pinky_adapter.yaml`의 `reference_coordinates`를 기준으로 처리한다.
RMF level 이름은 현재 `L1`이다.
