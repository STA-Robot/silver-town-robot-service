# RMF - JetCobot workcell 인터페이스 초안

버전: `0.1.0-workcell-topic-mvp`

이 문서는 창고 pick/place 시나리오에서 `task_orchestrator -> Open-RMF -> workcell_adapter -> jetcobot_arm_manager` 흐름을 기준으로 JetCobot 연동 인터페이스를 정의한다.

Pinky 주행 인터페이스와 마찬가지로, 실제 하드웨어 제어 노드는 RMF를 직접 알지 않는다. RMF-facing 책임은 `workcell_adapter`가 맡고, JetCobot-facing 책임은 `jetcobot_arm_manager`가 맡는다.

```text
task_orchestrator
        |
        | RMF task / workcell request
        v
Open-RMF
        |
        | rmf_ingestor_msgs
        v
workcell_adapter
        |
        | WorkcellCommand / WorkcellState
        v
jetcobot_arm_manager
        |
        v
JetCobot pick & place logic
```

## 목표

- Orchestrator는 JetCobot에 직접 명령하지 않고 Open-RMF에 pick/place task를 제출한다.
- Open-RMF는 workcell/ingestor 인터페이스로 `workcell_adapter`에 요청을 전달하되, JetCobot을 fleet robot처럼 동적으로 선정하지 않는다.
- Orchestrator는 pick/place task를 만들 때 대상 창고 workcell 또는 로봇팔 이름이 드러나는 `target_guid`를 지정한다.
- `workcell_adapter`는 `target_guid`에 매핑된 JetCobot 1~2대의 사용 가능 여부, 요청 큐, 성공/실패 결과를 관리한다.
- `jetcobot_arm_manager`는 실제 JetCobot pick & place sequence를 실행하고 명령 상태를 topic으로 보고한다.
- 내부 JetCobot 명령/상태 계약은 ROS domain bridge로 연결할 수 있도록 topic-only를 기본으로 한다.

## 책임 분리

| 컴포넌트 | 책임 |
|---|---|
| `task_orchestrator` | mission 상태 관리, 창고 도착 후 pick/place task 제출, 완료/실패에 따른 mission 분기 |
| Open-RMF | 지정된 workcell request 전달, workcell result 기반 task 상태 갱신. JetCobot 선정은 하지 않는다. |
| `workcell_adapter` | RMF ingestor request 수신, `target_guid` 기반 JetCobot 라우팅, arm command 발행, arm state 감시, RMF result 보고 |
| `jetcobot_arm_manager` | JetCobot 하드웨어 제어, pick & place 로직 실행, command/state idempotency 처리 |

## RMF-facing Topic

Open-RMF와 `workcell_adapter` 사이에는 `rmf_ingestor_msgs`를 사용한다.

기본 topic 이름은 배포 설정에서 바꿀 수 있지만, MVP에서는 아래 이름을 기준으로 한다.

| Topic | 방향 | Message |
|---|---|---|
| `/ingestor_requests` | RMF -> workcell_adapter | `rmf_ingestor_msgs/msg/IngestorRequest` |
| `/ingestor_states` | workcell_adapter -> RMF | `rmf_ingestor_msgs/msg/IngestorState` |
| `/ingestor_results` | workcell_adapter -> RMF | `rmf_ingestor_msgs/msg/IngestorResult` |

`rmf_ingestor_msgs`의 핵심 필드는 다음과 같다. 필드 이름은 Open-RMF `rmf_internal_msgs`의 public message API를 따른다.

### IngestorRequest

```text
builtin_interfaces/Time time
string request_guid
string target_guid
string transporter_type
IngestorRequestItem[] items
```

| 필드 | 의미 |
|---|---|
| `request_guid` | RMF가 생성한 workcell 요청 id. 내부 `command_id`로 매핑한다. |
| `target_guid` | 요청 대상 창고 workcell 또는 로봇팔 라우팅 id. 예: `warehouse_pick_place_jetcobot1`, `warehouse_pick_place_all` |
| `transporter_type` | 물품을 가져온 운반체 타입. MVP에서는 `pinky` 또는 `pinky_pro` |
| `items` | pick/place할 물품 목록 |

### 로봇팔 대상 지정 정책

Open-RMF가 JetCobot을 직접 선정하지 않는다. `task_orchestrator`는 창고 pick/place task를 제출할 때 대상 창고 workcell 또는 로봇팔 이름이 드러나는 `target_guid`를 지정한다.

`rmf_ingestor_msgs/msg/IngestorRequest`에는 별도의 `arm_names` 필드가 없으므로, MVP에서는 `target_guid`를 로봇팔 라우팅의 source of truth로 사용한다. `workcell_adapter`는 설정 파일에서 `target_guid`를 실제 JetCobot 이름 목록으로 매핑한다.

예시:

| `target_guid` | `workcell_adapter` routing |
|---|---|
| `warehouse_pick_place_jetcobot1` | `jetcobot1` |
| `warehouse_pick_place_jetcobot2` | `jetcobot2` |
| `warehouse_pick_place_all` | `jetcobot1`, `jetcobot2` |

Task API label이나 payload에 `target_arm_names=["jetcobot1"]` 같은 정보를 함께 넣을 수는 있지만, 2.7.2 표준 ingestor request로 반드시 전달된다고 가정하지 않는다. 실제 arm command 라우팅은 `target_guid`와 adapter 설정으로 결정한다.

### IngestorRequestItem

```text
string type_guid
int32 quantity
string compartment_name
```

| 필드 | 의미 |
|---|---|
| `type_guid` | 물품 종류 id. 예: `towel`, `medicine_box`, `unknown` |
| `quantity` | 해당 물품 수량. MVP에서는 사전 수량을 모르면 `0`으로 두고 "감지되는 모든 해당 물품"으로 해석한다. |
| `compartment_name` | Pinky 보관함/칸 이름. MVP에서는 칸을 구분하지 않으므로 빈 문자열로 둔다. |

MVP의 JetCobot 작업은 Pinky가 창고의 지정 위치에 정지해 있다는 전제를 둔다. 따라서 `quantity`는 작업 계획의 상한값이 아니라 분류 가능한 물품 종류를 전달하기 위한 보조 정보로만 사용한다. 실제 종료 조건은 JetCobot이 더 이상 피킹할 물품을 감지하지 못하는 시점이다.

### IngestorState

```text
builtin_interfaces/Time time
string guid
int32 mode
int32 IDLE=0
int32 BUSY=1
int32 OFFLINE=2
string[] request_guid_queue
float32 seconds_remaining
```

| 필드 | 의미 |
|---|---|
| `guid` | workcell id. 예: `warehouse_pick_place` |
| `mode` | `IDLE`, `BUSY`, `OFFLINE` |
| `request_guid_queue` | 처리 중이거나 대기 중인 request id 목록 |
| `seconds_remaining` | 현재 요청의 예상 잔여 시간. 모르면 `0.0` |

권장 publish rate는 `1~5 Hz`이다. RMF가 일정 시간 state를 받지 못하면 workcell을 unavailable로 판단할 수 있어야 한다.

### IngestorResult

```text
builtin_interfaces/Time time
string request_guid
string source_guid
uint8 status
uint8 ACKNOWLEDGED=0
uint8 SUCCESS=1
uint8 FAILED=2
```

| 필드 | 의미 |
|---|---|
| `request_guid` | 결과가 대응되는 RMF request id |
| `source_guid` | 결과를 보낸 workcell id |
| `status` | `ACKNOWLEDGED`, `SUCCESS`, `FAILED` |

`ACKNOWLEDGED`는 요청을 접수했다는 의미이고 최종 완료가 아니다. JetCobot 작업이 끝나면 반드시 `SUCCESS` 또는 `FAILED`를 publish한다.

## JetCobot-facing Topic

`workcell_adapter`와 `jetcobot_arm_manager` 사이에는 프로젝트 전용 메시지를 사용한다.

각 JetCobot이 별도 `ROS_DOMAIN_ID`에서 실행될 수 있으므로, JetCobot domain 내부 topic에는 로봇 namespace를 붙이지 않는다. 로봇 구분은 RMF/workcell domain 쪽 topic 이름과 domain bridge remap으로 처리한다.

JetCobot domain 내부 topic:

| Topic | 방향 | Message |
|---|---|---|
| `/command` | workcell_adapter -> arm_manager | `jetcobot_workcell_msgs/msg/WorkcellCommand` |
| `/state` | arm_manager -> workcell_adapter | `jetcobot_workcell_msgs/msg/WorkcellState` |

workcell/RMF domain에서는 로봇팔별 topic으로 bridge한다.

| workcell domain topic | JetCobot domain topic |
|---|---|
| `/jetcobot1/command` | jetcobot1 domain `/command` |
| `/jetcobot1/state` | jetcobot1 domain `/state` |
| `/jetcobot2/command` | jetcobot2 domain `/command` |
| `/jetcobot2/state` | jetcobot2 domain `/state` |

`workcell_adapter`와 `jetcobot_arm_manager`가 같은 ROS domain에서 실행되는 경우에도 위 topic 이름을 그대로 사용할 수 있다.

## WorkcellCommand

초안 message:

```text
# jetcobot_workcell_msgs/msg/WorkcellCommand.msg

std_msgs/Header header
string arm_name
string command_id
string command_type

string mission_id

string[] item_type_guids

string payload_json
```

### 필드 의미

| 필드 | 의미 |
|---|---|
| `header.stamp` | `workcell_adapter`가 명령을 생성한 시각 |
| `arm_name` | 대상 로봇팔 이름. 예: `jetcobot1` |
| `command_id` | 명령 고유 id. RMF `request_guid`와 같게 두는 것을 권장한다. |
| `command_type` | 명령 종류. 예: `pick_and_place`, `stop`, `reset` |
| `mission_id` | orchestrator mission id. payload나 RMF label에서 전달받는다. |
| `item_type_guids` | pick/place할 수 있는 물품 종류 목록. 예: `towel`, `medicine_box`, `cup` |
| `payload_json` | command_type별 추가 인자. 예: retry 정책, vision 옵션 |

Pinky는 창고의 지정 위치에 정지하고, 분류 목적지 박스/선반은 workcell 설정으로 고정되어 있다고 본다. 따라서 `mobile_robot_name`, `warehouse_station`, `source_container`, `item_quantities`, `compartment_names`는 MVP command에는 넣지 않는다. 로봇별 캘리브레이션이나 station별 sorting map이 필요해지면 `workcell_adapter` 설정 또는 `payload_json`에서 시작하고, 반복적으로 필요해질 때 별도 필드로 승격한다.

### command_type

MVP에서 우선 아래 값만 사용한다.

| 값 | 의미 |
|---|---|
| `pick_and_place` | 지정 위치의 Pinky 보관함에서 피킹 대상과 물품 종류를 먼저 판별한 뒤 `picking`/`placing`을 반복하고, 더 이상 지원 대상 물품이 감지되지 않으면 완료한다. |
| `stop` | 현재 arm motion 또는 sequence를 안전 정지한다. |
| `reset` | 수동개입 후 arm 상태를 초기화하고 idle로 복귀한다. |

## WorkcellState

초안 message:

```text
# jetcobot_workcell_msgs/msg/WorkcellState.msg

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

### 필드 의미

| 필드 | 의미 |
|---|---|
| `arm_name` | 상태를 publish하는 로봇팔 이름 |
| `state` | JetCobot public state |
| `available` | `workcell_adapter`가 새 일반 작업을 라우팅할 수 있는지 |
| `emergency` | 비상정지 또는 안전 정지 활성 여부 |
| `command_active` | 현재 명령 수행 중인지 |
| `active_command_id` | 수행 중인 명령 id. 없으면 빈 문자열 |
| `last_command_id` | 마지막으로 종료된 명령 id |
| `last_command_status` | 마지막 명령 결과. 예: `accepted`, `succeeded`, `failed`, `rejected`, `canceled` |
| `mission_id` | 현재 또는 마지막 명령의 mission id |
| `progress` | 진행률 `[0.0, 1.0]`. 모르면 `0.0` |
| `seconds_remaining` | 예상 잔여 시간. 모르면 `0.0` |
| `message` | 사람이 읽을 수 있는 상태/오류 사유 |

권장 publish rate는 `5~10 Hz`이다. `workcell_adapter`는 일정 시간 state를 받지 못하면 해당 arm을 unavailable로 처리한다.

## State 값

| 값 | 의미 |
|---|---|
| `unknown` | arm manager 준비 전 |
| `idle` | 대기 중 |
| `reserved` | workcell_adapter가 지정된 요청을 arm에 전달했지만 motion 시작 전 |
| `picking` | 보관함 안에서 피킹 대상 후보와 물품 종류를 판별하고, 지원 대상 물품을 집는 중 |
| `placing` | 집은 물품을 물품 종류별 분류 목적지에 내려놓는 중 |
| `homing` | home pose로 복귀 중 |
| `blocked` | 현재 명령을 계속할 수 없음 |
| `emergency` | 비상정지 중 |

## Command 처리 규칙

- JetCobot은 `arm_name`이 자신과 다르면 명령을 무시한다.
- JetCobot은 이미 처리한 `command_id`가 다시 오면 중복 명령으로 보고 무시하거나 현재 상태만 다시 publish한다.
- 명령을 수락하면 `state.active_command_id = command_id`, `command_active = true`, `last_command_status = accepted`로 publish한다.
- 명령이 끝나면 `active_command_id`를 비우고, `last_command_id`와 `last_command_status`를 publish한다.
- `stop`은 가능한 한 idempotent하게 처리한다. 같은 `stop` 명령이 여러 번 와도 안전해야 한다.
- `emergency` 상태에서는 `pick_and_place` 명령을 수행하지 않고 `rejected`로 보고한다.
- `pick_and_place`가 실패하면 `last_command_status = failed`, `state = blocked` 또는 `state = idle` 중 하나를 운영 정책에 따라 선택한다. MVP에서는 사람이 확인해야 하므로 `blocked`를 권장한다.
- `reset`은 수동개입 후 `blocked` 또는 `emergency`에서 `idle`로 복귀할 때 사용한다.

## workcell_adapter 처리 규칙

- `target_guid`가 자신이 관리하는 workcell id와 다르면 RMF request를 무시한다.
- 요청을 받을 수 있으면 `/ingestor_results`에 `ACKNOWLEDGED`를 publish한다.
- `target_guid`에 매핑된 JetCobot 이름을 찾고, 해당 arm topic으로 `WorkcellCommand(command_type=pick_and_place)`를 publish한다.
- 지정된 JetCobot이 아직 사용할 수 없으면 request를 queue에 넣고 `/ingestor_states`의 `request_guid_queue`에 반영한다.
- arm state에서 해당 `command_id`의 `succeeded`를 확인하면 `/ingestor_results`에 `SUCCESS`를 publish한다.
- arm state에서 해당 `command_id`의 `failed`, `rejected`, `canceled`를 확인하면 `/ingestor_results`에 `FAILED`를 publish한다.
- 하나의 논리 workcell이 `jetcobot1`, `jetcobot2`를 모두 관리할 수 있다. MVP에서는 `target_guid`를 `warehouse_pick_place_jetcobot1`, `warehouse_pick_place_jetcobot2`, `warehouse_pick_place_all`처럼 나누고, 각 값이 어떤 arm으로 라우팅되는지는 adapter 설정으로 관리한다.

## 예시 Flow

Pick and place:

```text
task_orchestrator submits pick/place task/request to Open-RMF
  mission_id=mission_abc123
  target_guid=warehouse_pick_place_jetcobot1

RMF publishes `/ingestor_requests`
  request_guid=mission_abc123-pick-place
  target_guid=warehouse_pick_place_jetcobot1
  transporter_type=pinky
  items=[towel x unknown, medicine_box x unknown, cup x unknown]

workcell_adapter publishes `/ingestor_results`
  request_guid=mission_abc123-pick-place
  source_guid=warehouse_pick_place_jetcobot1
  status=ACKNOWLEDGED

workcell_adapter publishes `/jetcobot1/command`
  arm_name=jetcobot1
  command_id=mission_abc123-pick-place
  command_type=pick_and_place
  mission_id=mission_abc123
  item_type_guids=[towel, medicine_box, cup]

jetcobot1 detects a towel target in the Pinky bin before picking

jetcobot1 publishes `/jetcobot1/state`
  state=picking
  command_active=true
  active_command_id=mission_abc123-pick-place
  last_command_status=accepted

jetcobot1 picks the towel

jetcobot1 publishes `/jetcobot1/state`
  state=placing
  command_active=true
  active_command_id=mission_abc123-pick-place

jetcobot1 places the towel in the towel destination box

jetcobot1 repeats picking and placing until no supported items are detected

jetcobot1 publishes `/jetcobot1/state`
  state=idle
  available=true
  command_active=false
  active_command_id=""
  last_command_id=mission_abc123-pick-place
  last_command_status=succeeded

workcell_adapter publishes `/ingestor_results`
  request_guid=mission_abc123-pick-place
  source_guid=warehouse_pick_place_jetcobot1
  status=SUCCESS

Open-RMF marks the workcell task/request completed
task_orchestrator marks mission completed
Pinky returns by RMF finishing_request=park
```

Failure:

```text
jetcobot1 publishes `/jetcobot1/state`
  state=blocked
  command_active=false
  last_command_id=mission_abc123-pick-place
  last_command_status=failed
  message="object detection failed"

workcell_adapter publishes `/ingestor_results`
  request_guid=mission_abc123-pick-place
  source_guid=warehouse_pick_place_jetcobot1
  status=FAILED

Open-RMF marks the workcell task/request failed
task_orchestrator keeps mission in intervention_required
Pinky must not return until the failure policy allows it
```

Stop:

```text
workcell_adapter publishes `/jetcobot1/command`
  command_id=workcell-stop-001
  command_type=stop

jetcobot1 cancels or safely stops current motion

jetcobot1 publishes `/jetcobot1/state`
  state=blocked
  command_active=false
  last_command_id=workcell-stop-001
  last_command_status=succeeded
```

## task_orchestrator 연동 메모

`task_orchestrator`는 창고 이동 task가 완료된 뒤 workcell pick/place task/request를 Open-RMF에 제출한다.

```text
table_task_completed
  -> check_bin_state
  -> submit_warehouse_task_to_same_robot
  -> warehouse_task_completed
  -> submit_pick_place_workcell_task
  -> wait_until_workcell_completed
  -> mission_completed
```

중요 규칙:

- `warehouse_task_completed` 전에는 pick/place task를 제출하지 않는다.
- pick/place task에는 대상 창고 workcell/로봇팔이 드러나는 `target_guid`를 포함한다. Open-RMF가 JetCobot을 선정하지 않는다.
- pick/place 성공 전에는 Pinky 보관함을 empty로 갱신하지 않는다.
- pick/place 실패 시 mission은 `intervention_required`로 남긴다.
- pick/place 진행 중인 Pinky는 신규 table call 후보가 되면 안 된다.
- pick/place 완료 후 Pinky 복귀는 별도 direct return task가 아니라 RMF `finishing_request: park`에 맡긴다.

## 구현 메모

- 새 메시지 패키지는 `jetcobot_workcell_msgs`로 둔다.
- 새 adapter 패키지는 `jetcobot_workcell_adapter` 또는 `pinky_workcell_adapter`로 둔다. 프로젝트 전체 용어를 맞추려면 `jetcobot_workcell_adapter`를 권장한다.
- `workcell_adapter`는 `/ingestor_requests`, `/ingestor_states`, `/ingestor_results`를 제공한다.
- `jetcobot_arm_manager`는 `/command` subscriber와 `/state` publisher를 제공한다.
- `WorkcellState.msg`의 `active_command_id`, `last_command_id`, `last_command_status`로 command 결과를 확인한다.
- 물품 종류별 분류 목적지, vision 옵션, retry 횟수는 `payload_json`에 넣고, 정책이 안정되면 별도 필드로 승격한다.
