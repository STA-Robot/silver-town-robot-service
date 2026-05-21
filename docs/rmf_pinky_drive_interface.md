# RMF - Pinky 주행 인터페이스 초안

버전: `0.2.0-topic-mvp`

ROS domain bridge를 사용할 때 RMF, `pinky1`, `pinky2`는 서로 다른 `ROS_DOMAIN_ID`를 사용할 수 있다. Domain bridge는 topic 중심으로 연결하고, service/action은 RMF-facing 인터페이스로 사용하지 않는다.

따라서 RMF adapter와 Pinky drive manager 사이의 명령은 범용 `/command` topic으로 전달한다. 명령 수락, 진행, 완료 여부는 `/state` topic의 `active_command_id`, `last_command_id`, `last_command_status` 필드로 확인한다.

## 목표

- RMF -> Pinky: 주행, 정지, 사람 추종 등 명령을 하나의 topic으로 보낸다.
- Pinky -> RMF: 현재 pose, 배터리, 주행 상태, 명령 상태를 topic으로 보고한다.
- Action/service 없이 domain bridge로 전달 가능한 topic-only 계약을 만든다.

## Topic

각 Pinky는 별도 `ROS_DOMAIN_ID`에서 실행되므로 drive manager 내부 topic에는 로봇 namespace를 붙이지 않는다. 로봇 구분은 RMF domain 쪽 topic 이름과 domain bridge remap으로 처리한다.

Pinky domain 내부 topic:

| Topic | 방향 | Message |
|---|---|---|
| `/command` | RMF -> Pinky | `pinky_drive_msgs/msg/DriveCommand` |
| `/state` | Pinky -> RMF | `pinky_drive_msgs/msg/DriveState` |

RMF domain에서는 로봇별 topic으로 bridge한다.

| RMF domain topic | Pinky domain topic |
|---|---|
| `/pinky1/command` | pinky1 domain `/command` |
| `/pinky1/state` | pinky1 domain `/state` |
| `/pinky2/command` | pinky2 domain `/command` |
| `/pinky2/state` | pinky2 domain `/state` |

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
| `command_type` | 명령 종류. 예: `navigate`, `returning`, `follow`, `stop` |
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
RMF publishes `/pinky1/command`, bridged to Pinky domain `/command`
  command_id=rmf-001
  command_type=navigate
  map_name=L1
  x=1.0, y=2.0, yaw=0.0

Pinky publishes `/state`, bridged to RMF domain `/pinky1/state`
  state=navigating
  command_active=true
  active_command_id=rmf-001

Pinky reaches goal

Pinky publishes `/state`, bridged to RMF domain `/pinky1/state`
  state=idle
  command_active=false
  active_command_id=""
  last_command_id=rmf-001
  last_command_status=succeeded
```

Stop:

```text
RMF publishes `/pinky1/command`, bridged to Pinky domain `/command`
  command_id=rmf-stop-001
  command_type=stop

Pinky cancels current motion

Pinky publishes `/state`, bridged to RMF domain `/pinky1/state`
  state=idle
  command_active=false
  last_command_id=rmf-stop-001
  last_command_status=succeeded
```

## 구현 메모

Drive manager는 Pinky domain 내부에서 `/command`, `/state`를 사용한다. RMF domain의 `/pinky1/command`, `/pinky1/state` 같은 로봇별 topic은 domain bridge remap으로 연결한다.

- `pinky_drive_msgs/msg/DriveCommand.msg` 사용
- `DriveState.msg`의 `active_command_id`, `last_command_id`, `last_command_status`로 command 결과 확인
- `drive_manager_node.py`는 `/command` subscriber와 `/state` publisher 제공
- `RobotClientAPI.py`는 action/service client 대신 RMF domain의 로봇별 `/command` publisher와 `/state` subscriber 사용
