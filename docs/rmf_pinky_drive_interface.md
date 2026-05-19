# RMF - Pinky 주행 인터페이스

버전: `0.1.0-mvp`

이 문서는 RMF adapter와 Pinky drive manager 사이의 ROS 2 인터페이스 계약을 정의한다. RMF 개발자는 이 문서만 보고 fleet adapter를 개발할 수 있어야 하고, Pinky 개발자는 RMF 내부 구현에 의존하지 않고 주행 노드를 구현할 수 있어야 한다.

상태 모델은 [pinky_drive_state_diagram.md](pinky_drive_state_diagram.md)에 정의되어 있다.

## 범위

MVP 인터페이스는 다음 기능을 포함한다.

- RMF가 Pinky에게 특정 pose로 이동하라고 명령한다.
- RMF가 Pinky에게 현재 움직임을 정지하라고 명령한다.
- Pinky가 pose, 배터리, 명령 수행 상태, 주행 상태를 보고한다.
- Pinky가 사람 추종 로직으로 제어 중일 때 `following` 상태를 보고한다.
- Pinky가 현재 이동 명령을 더 이상 계속할 수 없을 때 `blocked` 상태를 보고한다.
- Pinky가 비상정지 중일 때 `emergency` 상태를 보고한다.

MVP 인터페이스에서는 RMF가 YOLO/person tracking을 직접 제어하지 않는다. 사람 추종은 Pinky 쪽 local UI, service, task node 등이 시작하거나 재시도한다. RMF는 `state == "following"`을 관측하고 해당 로봇을 busy 상태로 취급한다.

## 역할

| 역할 | 책임 |
|---|---|
| RMF adapter | `Navigate` goal 전송, `Stop` 호출, `DriveState` 구독, RMF에 로봇 위치와 사용 가능 상태 반영 |
| Pinky drive manager | public drive state 소유, 명령 검증, navigation 요청을 Nav2 또는 follow control로 연결, `DriveState` publish |
| Pinky follower | 사람을 인식하고 따라가는 Pinky 내부 구성요소. MVP에서는 RMF-facing API가 아니지만 drive manager 상태를 `following` 또는 `blocked`로 갱신해야 함 |
| Emergency source | Pinky에 emergency input publish. RMF는 `DriveState.emergency`와 `DriveState.state`로 결과를 관측 |

## 네임스페이스

각 로봇은 하나의 drive API namespace를 제공한다.

```text
/{robot_name}/drive
```

`pinky1` 예시:

| 인터페이스 | 전체 이름 | 방향 |
|---|---|---|
| State topic | `/pinky1/drive/state` | Pinky -> RMF |
| Navigate action | `/pinky1/drive/navigate` | RMF -> Pinky |
| Stop service | `/pinky1/drive/stop` | RMF -> Pinky |

Pinky 구현은 Nav2, battery, emergency, camera, YOLO, follower controller 등 추가 내부 topic을 사용할 수 있다. 이 내부 topic들은 RMF-facing 계약에 포함되지 않는다.

## 좌표 계약

| 필드 | 단위 | 계약 |
|---|---|---|
| `map_name` | string | RMF level 이름. Pinky에 설정된 level과 일치해야 한다. 예: `L1` |
| `x` | meter | `map_name` / Pinky `map_frame` 기준 x 위치 |
| `y` | meter | `map_name` / Pinky `map_frame` 기준 y 위치 |
| `yaw` | radian | map frame 기준 heading. Pinky는 pose를 보고할 때 `[-pi, pi]` 범위로 normalize하는 것을 권장한다. |
| `speed_limit` | m/s | 선택적 최대 속도. `0.0` 이하이면 RMF가 지정한 속도 제한이 없다는 뜻이다. MVP에서 Pinky는 이 값을 무시할 수 있지만 필드는 수락해야 한다. |

RMF는 Pinky가 `DriveState.header.frame_id`로 보고하는 map frame과 같은 좌표계로 goal을 보내야 한다.

## State Topic

Topic:

```text
/{robot_name}/drive/state
```

Message type:

```text
pinky_drive_msgs/msg/DriveState
```

Definition:

```text
std_msgs/Header header
string robot_name
string map_name
float64[3] pose
float32 battery_soc
string state
string nav2_state
bool available
bool emergency
bool command_active
string active_request_id
string message
```

Publish rate:

- Pinky는 `10 Hz`로 publish하는 것을 권장한다.
- RMF는 `2 s` 이상 메시지를 받지 못하면 state를 stale로 간주하고 unavailable로 처리해야 한다.

### DriveState 필드

| 필드 | 의미 |
|---|---|
| `header.stamp` | Pinky 상태 timestamp |
| `header.frame_id` | `pose`에 사용된 map frame. 일반적으로 `map` |
| `robot_name` | 로봇 이름. 예: `pinky1` |
| `map_name` | RMF level 이름. 예: `L1` |
| `pose` | map frame 기준 `[x, y, yaw]` |
| `battery_soc` | 배터리 state of charge. 범위는 `[0.0, 1.0]`. 알 수 없으면 `NaN` 사용 |
| `state` | public drive state. 아래 state enum 참고 |
| `nav2_state` | Nav2 action 상태. Nav2 주행 중이 아니면 `none` 사용 |
| `available` | RMF가 일반적인 새 navigation 명령을 보낼 수 있는지 여부. RMF는 반드시 `state`도 함께 확인해야 한다. |
| `emergency` | 비상정지가 활성화되어 있으면 `true` |
| `command_active` | Pinky가 navigation, return, following 명령을 수행 중이면 `true` |
| `active_request_id` | 현재 수행 중인 RMF request id. 활성 RMF 명령이 없으면 빈 문자열 |
| `message` | 로그와 UI를 위한 사람이 읽을 수 있는 상태/사유 문자열 |

### Public State Enum

Pinky는 MVP에서 다음 상태만 publish해야 한다.

| 상태 | 의미 | `available` |
|---|---|---|
| `unknown` | drive manager가 시작됐지만 아직 준비되지 않은 상태. 보통 Nav2와 TF를 기다리는 중 | `false` |
| `idle` | 로봇이 준비되어 있고 활성 motion command가 없는 상태 | `true` |
| `navigating` | RMF task navigation 명령을 수행 중인 상태 | `false` |
| `returning` | RMF return 명령을 수행 중인 상태. RMF는 task 명령으로 이를 preempt할 수 있다. | `true` |
| `following` | Pinky 쪽 perception/control로 사람을 따라가는 상태 | `false` |
| `blocked` | 현재 또는 직전 motion command를 계속할 수 없는 상태. 작업자 개입 또는 retry가 필요하다. | `false` |
| `emergency` | 비상정지가 활성화된 상태. Pinky는 움직이면 안 된다. | `false` |

`error`는 MVP public state enum에서 의도적으로 제외한다. 움직임을 막는 시스템 수준 실패도 MVP에서는 설명적인 `message`와 함께 `blocked`로 보고한다. 이후 버전에서 `blocked`와 `error`를 분리할 수 있다.

### Nav2 State Enum

`nav2_state`는 진단용이다. RMF는 이를 task 완료 판단의 주 근거로 사용하면 안 된다.

허용 값:

```text
none
pending
accepted
executing
canceling
succeeded
canceled
aborted
unknown
```

RMF는 `Navigate` action result와 `DriveState.state`를 주요 계약으로 사용해야 한다.

## Navigate Action

Action name:

```text
/{robot_name}/drive/navigate
```

Action type:

```text
pinky_drive_msgs/action/Navigate
```

Definition:

```text
string robot_name
string map_name
float64 x
float64 y
float64 yaw
float64 speed_limit
string request_id
string destination_name
string command_mode
---
bool success
bool retryable
string final_state
string message
---
string state
float64 distance_remaining
string message
```

### Goal 필드

| 필드 | 필수 | 계약 |
|---|---|---|
| `robot_name` | yes | 대상 Pinky 로봇 이름과 일치해야 한다. |
| `map_name` | yes | Pinky에 설정된 RMF level과 일치해야 한다. |
| `x` | yes | map frame 기준 goal x |
| `y` | yes | map frame 기준 goal y |
| `yaw` | yes | radian 단위 goal yaw |
| `speed_limit` | no | 선택적 속도 제한. 사용하지 않으면 `0.0` |
| `request_id` | yes | 고유한 RMF command id. Pinky는 이를 `DriveState.active_request_id`에 echo한다. |
| `destination_name` | no | 사람이 읽을 수 있는 목적지/waypoint 이름 |
| `command_mode` | yes | `task` 또는 `returning` 중 하나 |

`command_mode == "following"`은 허용하지 않는다. MVP에서 사람 추종은 RMF `Navigate` action으로 구동하지 않는다.

### Goal 수락 규칙

Pinky는 아래 조건이 모두 참일 때만 `Navigate` goal을 수락해야 한다.

- `robot_name`이 현재 로봇과 일치한다.
- `map_name`이 현재 로봇에 설정된 level과 일치한다.
- `command_mode`가 `task` 또는 `returning`이다.
- `x`, `y`, `yaw`가 모두 finite number이다.
- 비상정지가 활성화되어 있지 않다.
- TF/pose가 준비되어 있다.
- 하위 navigation stack이 준비되어 있다.
- 현재 상태가 다음 중 하나이다.
  - `idle`
  - `returning`
  - `blocked`, 단 retry 또는 replacement command인 경우

Pinky는 현재 상태가 아래 중 하나이면 `Navigate` goal을 거절해야 한다.

- `unknown`
- `navigating`
- `following`
- `emergency`

Pinky가 `returning` 상태에서 `task` 명령을 수락하면, 기존 return motion을 cancel하고 `navigating`으로 전환해야 한다.

### 상태 전이

| 현재 상태 | 이벤트 | 다음 상태 |
|---|---|---|
| `idle` | accepted `Navigate(command_mode=task)` | `navigating` |
| `idle` | accepted `Navigate(command_mode=returning)` | `returning` |
| `returning` | accepted `Navigate(command_mode=task)` | `navigating` |
| `blocked` | accepted retry `Navigate(command_mode=task)` | `navigating` |
| `blocked` | accepted retry `Navigate(command_mode=returning)` | `returning` |
| `navigating` | navigation success | `idle` |
| `returning` | navigation success | `idle` |
| `navigating` | navigation abort 또는 goal rejected | `blocked` |
| `returning` | navigation abort 또는 goal rejected | `blocked` |
| emergency가 아닌 모든 상태 | emergency input active | `emergency` |

### Feedback

Pinky는 navigation이 활성화되어 있는 동안 action feedback을 publish해야 한다.

| 필드 | 의미 |
|---|---|
| `state` | 현재 public drive state. 일반적으로 `navigating` 또는 `returning` |
| `distance_remaining` | 남은 거리, meter 단위. 알 수 없으면 `NaN` |
| `message` | 사람이 읽을 수 있는 진행 상태 메시지 |

권장 feedback rate는 최소 `1 Hz`이다.

### Result

| 상황 | `success` | `retryable` | `final_state` |
|---|---:|---:|---|
| goal 도착 | `true` | `false` | `idle` |
| Nav2가 goal을 abort | `false` | `true` | `blocked` |
| Pinky가 RMF goal을 수락한 뒤 Nav2가 goal을 reject | `false` | `true` | `blocked` |
| `Stop`으로 goal cancel | `false` | `true` | `idle` |
| emergency 활성화 | `false` | `true` | `emergency` |
| 실행 전 invalid request reject | action goal 자체를 reject해야 함 | n/a | n/a |

RMF는 `success == false`가 항상 로봇 고장을 의미한다고 가정하면 안 된다. `final_state`와 `message`를 통해 blocked, stopped, emergency interruption 중 무엇인지 판단해야 한다.

## Stop Service

Service name:

```text
/{robot_name}/drive/stop
```

Service type:

```text
pinky_drive_msgs/srv/Stop
```

Definition:

```text
string robot_name
string request_id
---
bool success
string state
string message
```

### Stop 의미

RMF는 활성 robot motion을 cancel하기 위해 `Stop`을 호출할 수 있다.

| 현재 상태 | Stop 동작 |
|---|---|
| `navigating` | Nav2 goal을 cancel하고 `idle`로 전환 |
| `returning` | Nav2 goal을 cancel하고 `idle`로 전환 |
| `following` | follower controller를 정지하고 `idle`로 전환 |
| `blocked` | 현재 command context를 정리하고 retry 가능한 상태로 남김. blocked 원인이 해소되었는지에 따라 response state는 `blocked` 또는 `idle`일 수 있다. |
| `idle` | idempotent success. 상태는 `idle` 유지 |
| `emergency` | 움직이지 않음. 상태는 `emergency` 유지 |
| `unknown` | 가능한 경우 pending command를 정지. 준비될 때까지 상태는 `unknown` 유지 |

이 service는 idempotent해야 한다. 같은 stop request를 반복해도 안전해야 한다.

## Following Mode 계약

MVP에서 following은 Pinky 쪽에서 제어한다. RMF는 person-tracking goal을 보내지 않는다.

### Pinky 필수 동작

Pinky는 다음 상태 갱신을 publish해야 한다.

| 이벤트 | 필요한 상태 갱신 |
|---|---|
| person following starts | `state = "following"`, `available = false`, `command_active = true` |
| person following ends normally | `state = "idle"`, `available = true`, `command_active = false` |
| delivery flow completes | `state = "idle"`, `available = true`, `command_active = false` |
| target is lost longer than timeout | `state = "blocked"`, `available = false`, `message`에 target loss 사유 기록 |
| emergency input becomes active | `state = "emergency"`, follower 즉시 정지 |

`state == "following"`이면 RMF는 로봇을 busy 상태로 취급하고 새 `Navigate` goal을 보내지 않아야 한다. 단, operator 또는 safety policy상 정지가 필요하면 RMF는 `Stop`을 호출할 수 있다.

## Emergency 계약

Emergency input은 Pinky 쪽 책임이다. RMF는 아래 값으로 emergency를 관측한다.

```text
DriveState.state == "emergency"
DriveState.emergency == true
```

Emergency가 활성화되면 다음을 만족해야 한다.

- Pinky는 Nav2 또는 follower motion을 즉시 cancel해야 한다.
- Pinky는 `state = "emergency"`를 publish해야 한다.
- Pinky는 새 `Navigate` goal을 reject해야 한다.
- `Stop`은 안전하고 idempotent해야 하지만, emergency가 유지되는 동안 `idle`로 전이하면 안 된다.

MVP 다이어그램은 `emergency -> idle` 전이를 정의하지 않는다. Pinky는 emergency input이 해제되고 활성 command가 없을 때만 `idle`로 돌아갈 수 있다.

## RMF Adapter 책임

RMF adapter는 다음을 수행해야 한다.

- `/{robot_name}/drive/state`를 subscribe한다.
- stale state를 unavailable로 처리한다.
- 일반 RMF task 목적지에는 `Navigate(command_mode=task)`를 보낸다.
- return/home 동작에는 `Navigate(command_mode=returning)`을 보낸다.
- 전역적으로 고유한 `request_id`를 생성한다.
- `DriveState.pose`를 사용해 RMF에 현재 로봇 위치를 반영한다.
- `state == "following"`이면 busy/unavailable로 처리한다.
- `state == "blocked"`이면 retry 또는 operator intervention이 필요한 상태로 처리한다.
- `state == "emergency"`이면 unavailable 및 non-moving 상태로 처리한다.
- `Navigate` action result를 사용해 명령 완료, 실패, interruption 여부를 판단한다.
- Pinky가 `navigating`, `following`, `unknown`, `emergency` 상태일 때 일반 task goal을 보내지 않는다.

Adapter policy가 retry를 허용한다면 `DriveState.available`이 `false`여도 `blocked` 상태에서 retry command를 보낼 수 있다.

## Pinky Drive Manager 책임

Pinky drive manager는 다음을 수행해야 한다.

- `state` topic, `navigate` action server, `stop` service를 제공한다.
- public drive state enum을 소유하고 publish한다.
- 모든 RMF goal을 수락하기 전에 검증한다.
- 잘못된 robot 또는 map으로 온 명령을 reject한다.
- `DriveState`를 안정적인 주기로 publish한다.
- RMF command를 수행하는 동안 `active_request_id`를 유지한다.
- RMF command가 완료, 정지, blocked, emergency interruption 상태가 되면 `active_request_id`를 clear한다.
- navigation abort/rejection을 `blocked`로 매핑한다.
- person target loss timeout을 `blocked`로 매핑한다.
- emergency input을 `emergency`로 매핑한다.
- MVP public state enum에서는 `error`를 publish하지 않는다.

## 예시 Command Flow

일반 task navigation:

```text
RMF subscribes: /pinky1/drive/state
Pinky publishes: state=idle, available=true
RMF sends action goal: /pinky1/drive/navigate, command_mode=task
Pinky accepts goal
Pinky publishes: state=navigating, command_active=true, active_request_id=<id>
Pinky sends feedback: state=navigating, distance_remaining=...
Pinky reaches goal
Pinky action result: success=true, final_state=idle
Pinky publishes: state=idle, available=true, command_active=false
```

사람 추종:

```text
Pinky local follow command starts
Pinky publishes: state=following, available=false
RMF marks robot busy and does not dispatch normal task goals
Pinky target is lost for too long
Pinky publishes: state=blocked, message=target_lost_timeout
RMF marks robot blocked and waits for retry/operator policy
```

Emergency:

```text
Pinky receives emergency input
Pinky cancels active Nav2/follower motion
Pinky publishes: state=emergency, emergency=true, available=false
RMF marks robot unavailable
RMF must not send new Navigate goals until state returns to idle
```

## 현재 코드 기준 구현 메모

현재 `pinky_drive_manager` 코드는 주요 RMF-facing API를 이미 제공한다.

- `navigate`에 `Navigate` action 제공
- `stop`에 `Stop` service 제공
- `state`에 `DriveState` topic 제공

이 MVP 계약과 맞추려면 Pinky 쪽 구현에서 다음을 추가로 반영해야 한다.

- `following`을 유효한 public drive state로 추가한다.
- RMF navigation을 block하는 상태 목록에 `following`을 포함한다.
- retry policy가 활성화된 경우 `blocked`에서 retry navigation을 허용한다.
- MVP에서는 Nav2/server/follower failure를 public `error`가 아니라 `blocked`로 보고한다.
- `Stop`이 Nav2 navigation과 person-following control을 모두 정지할 수 있게 한다.
