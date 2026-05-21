# RMF - Pinky 주행 인터페이스 초안

버전: `0.2.0-topic-mvp`

ROS domain bridge를 사용할 때 RMF, `pinky1`, `pinky2`는 서로 다른 `ROS_DOMAIN_ID`를 사용할 수 있다. Domain bridge는 topic 중심으로 연결하고, service/action은 RMF-facing 인터페이스로 사용하지 않는다.

따라서 RMF adapter와 Pinky drive manager 사이의 명령은 범용 `/command` topic으로 전달한다. 명령 수락, 진행, 완료 여부는 `/state` topic의 `active_command_id`, `last_command_id`, `last_command_status` 필드로 확인한다.

## 목표

- RMF -> Pinky: 주행, 정지, 로봇팔 등 명령을 하나의 topic으로 보낸다.
- Pinky -> RMF: 현재 pose, 배터리, 주행 상태, 명령 상태를 topic으로 보고한다.
- Action/service 없이 domain bridge로 전달 가능한 topic-only 계약을 만든다.

## Topic

각 로봇은 아래 namespace를 사용한다.

```text
/{robot_name}
```

예시:

| Topic | 방향 | Message |
|---|---|---|
| `/pinky1/command` | RMF -> Pinky | `pinky_drive_msgs/msg/DriveCommand` |
| `/pinky1/state` | Pinky -> RMF | `pinky_drive_msgs/msg/DriveState` |

Domain bridge는 각 로봇별로 위 topic만 bridge한다.

## DriveCommand

초안 message:

```text
# pinky_drive_msgs/msg/DriveCommand.msg

std_msgs/Header header
string robot_name
string command_id
string command_type
string map_name

float64 x
float64 y
float64 yaw
float64 speed_limit

string target_name
string payload_json
```

### 필드 의미

| 필드 | 의미 |
|---|---|
| `header.stamp` | RMF가 명령을 생성한 시각 |
| `robot_name` | 대상 로봇 이름. 예: `pinky1` |
| `command_id` | 명령 고유 id. RMF가 생성하고 Pinky가 state에서 echo한다. |
| `command_type` | 명령 종류. 예: `navigate`, `stop`, `arm`, `dock`, `returning` |
| `map_name` | RMF level 이름. 예: `L1` |
| `x`, `y`, `yaw` | `navigate`, `returning`에서 사용하는 목표 pose |
| `speed_limit` | 선택적 속도 제한. 없으면 `0.0` |
| `target_name` | 목적지, waypoint, station 등 사람이 읽기 쉬운 이름 |
| `payload_json` | command_type별 추가 인자. MVP에서는 비워둘 수 있다. |

### command_type

MVP에서 우선 아래 값만 사용한다.

| 값 | 의미 |
|---|---|
| `navigate` | 지정 pose로 이동 |
| `returning` | 복귀/대기 위치로 이동 |
| `stop` | 현재 motion 명령 정지 |

추후 로봇팔이나 기타 동작은 같은 topic에서 `command_type = "arm"`처럼 확장한다. 추가 인자는 `payload_json`에 넣는다.

## DriveState

초안 message:

```text
# pinky_drive_msgs/msg/DriveState.msg

std_msgs/Header header
string robot_name
string map_name
float64[3] pose
float32 battery_soc

string state
bool available
bool emergency
bool command_active

string active_command_id
string last_command_id
string last_command_status
string message
```

### 필드 의미

| 필드 | 의미 |
|---|---|
| `pose` | map frame 기준 `[x, y, yaw]` |
| `battery_soc` | 배터리 잔량 `[0.0, 1.0]` |
| `state` | Pinky public state |
| `available` | RMF가 새 일반 주행 명령을 보낼 수 있는지 |
| `emergency` | 비상정지 활성 여부 |
| `command_active` | 현재 명령 수행 중인지 |
| `active_command_id` | 수행 중인 명령 id. 없으면 빈 문자열 |
| `last_command_id` | 마지막으로 종료된 명령 id |
| `last_command_status` | 마지막 명령 결과. 예: `accepted`, `succeeded`, `failed`, `rejected`, `canceled` |
| `message` | 사람이 읽을 수 있는 상태/오류 사유 |

권장 publish rate는 `5~10 Hz`이다. RMF는 일정 시간 state를 받지 못하면 해당 로봇을 unavailable로 처리한다.

## State 값

| 값 | 의미 |
|---|---|
| `unknown` | drive manager 준비 전 |
| `idle` | 대기 중 |
| `navigating` | RMF 주행 명령 수행 중 |
| `returning` | 복귀 명령 수행 중 |
| `following` | Pinky 내부 사람 추종 수행 중 |
| `blocked` | 현재 명령을 계속할 수 없음 |
| `emergency` | 비상정지 중 |

## Command 처리 규칙

- Pinky는 `robot_name`이 자신과 다르면 명령을 무시한다.
- Pinky는 이미 처리한 `command_id`가 다시 오면 중복 명령으로 보고 무시하거나 현재 상태만 다시 publish한다.
- 명령을 수락하면 `state.active_command_id = command_id`, `command_active = true`로 publish한다.
- 명령이 끝나면 `active_command_id`를 비우고, `last_command_id`와 `last_command_status`를 publish한다.
- `stop`은 가능한 한 idempotent하게 처리한다. 같은 `stop` 명령이 여러 번 와도 안전해야 한다.
- `emergency` 상태에서는 `navigate`, `returning` 명령을 수행하지 않고 `rejected`로 보고한다.

## 예시 Flow

Navigate:

```text
RMF publishes /pinky1/command
  command_id=rmf-001
  command_type=navigate
  map_name=L1
  x=1.0, y=2.0, yaw=0.0

Pinky publishes /pinky1/state
  state=navigating
  command_active=true
  active_command_id=rmf-001

Pinky reaches goal

Pinky publishes /pinky1/state
  state=idle
  command_active=false
  active_command_id=""
  last_command_id=rmf-001
  last_command_status=succeeded
```

Stop:

```text
RMF publishes /pinky1/command
  command_id=rmf-stop-001
  command_type=stop

Pinky cancels current motion

Pinky publishes /pinky1/state
  state=idle
  command_active=false
  last_command_id=rmf-stop-001
  last_command_status=succeeded
```

## 구현 메모

현재 코드는 RMF-facing 명령에 `Navigate` action과 `Stop` service를 사용한다. Domain bridge topic-only 구조로 바꾸려면 다음이 필요하다.

- `pinky_drive_msgs/msg/DriveCommand.msg` 추가
- `DriveState.msg`에 command 결과 확인용 필드 추가 또는 기존 `active_request_id`를 `active_command_id` 용도로 재사용
- `drive_manager_node.py`에서 `/command` subscriber 추가
- `RobotClientAPI.py`에서 action/service client 대신 `/command` publisher와 `/state` subscriber 사용
