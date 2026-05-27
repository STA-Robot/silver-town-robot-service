# Open-RMF Task API Guide (Jazzy / RMF 2.7.2 기준)

## 핵심 결론

현재 apt로 설치된 Jazzy RMF 2.7.2 기준에서는 다음 구성이 가장 안전하다.

- Task 제출: `task_api_requests` + `task_api_responses` 또는 `rmf_task_msgs/srv/ApiService`
- Task 중간 상태: `/task_summaries`
- Dispatch/할당 상태: `/dispatch_states`
- Fleet/Robot 상태: `/fleet_states`
- `task_state_update`, `task_log_update`, `fleet_state_update`, `fleet_log_update`: RMF 2.9.0+ 또는 Kilted/Rolling 계열에서 기대할 수 있는 ROS 2 fallback topic이며, 현재 2.7.2에서는 기본 사용 대상으로 보지 않는다.

PR #383의 "Publish fleet and task updates over ROS 2 if websocket is not provided" 기능은 ROS Index changelog 기준 `rmf_task_ros2` 2.9.0에 들어갔다. 따라서 2.7.2 환경에서 이 fallback topic들이 반드시 나온다고 가정하면 안 된다.

---

## 1. 확인된 토픽과 인터페이스

### Task API 요청/응답

| 이름 | 타입 | 역할 | 2.7.2 확인 |
|---|---|---|---|
| `task_api_requests` | `rmf_task_msgs/msg/ApiRequest` | JSON Task API 요청 publish | O |
| `task_api_responses` | `rmf_task_msgs/msg/ApiResponse` | 요청에 대한 ACK/최종 응답 | O |
| `/task_api_service` | `rmf_task_msgs/srv/ApiService` | JSON Task API service 호출 | 환경별 확인 필요 |

`/opt/ros/jazzy/include/rmf_fleet_adapter/StandardNames.hpp`에서 2.7.2의 `TaskApiRequests`, `TaskApiResponses` 상수는 확인된다.

`task_api_responses`는 지속 상태 스트림이 아니다. `ApiResponse.type`으로 `TYPE_ACKNOWLEDGE`와 `TYPE_RESPONDING`을 구분하고, `request_id`로 원 요청과 매칭한다.

### Legacy 상태/할당 토픽

| 이름 | 타입 | 역할 | 2.7.2에서의 용도 |
|---|---|---|---|
| `/task_summaries` | `rmf_task_msgs/msg/TaskSummary` | Task 요약 상태 | 실행 중 상태 추적 |
| `/dispatch_states` | `rmf_task_msgs/msg/DispatchStates` | Dispatch/할당 상태 | 로봇 선택, dispatch 성공/실패 추적 |
| `/fleet_states` | `rmf_fleet_msgs/msg/FleetState` | Fleet/Robot 상태 | 위치, 배터리, robot state 추적 |

2.7.2에서는 위 세 토픽을 task 진행 상태 추적의 기본 경로로 본다.

### 2.7.2에서 기본으로 기대하지 않는 topic

| 이름 | 역할 | 비고 |
|---|---|---|
| `task_state_update` | Task 상세 JSON 상태 update | PR #383 이후 기능, 2.9.0+ 기준 |
| `task_log_update` | Task JSON log update | PR #383 이후 기능, 2.9.0+ 기준 |
| `fleet_state_update` | Fleet JSON 상태 update | PR #383 이후 기능, 2.9.0+ 기준 |
| `fleet_log_update` | Fleet JSON log update | PR #383 이후 기능, 2.9.0+ 기준 |

Kilted/Rolling 문서의 `StandardNames.hpp`에는 이 topic 이름들이 보이지만, 현재 Jazzy 2.7.2 설치본의 `StandardNames.hpp`에는 없다. `rmf_api_msgs` schema 파일은 존재할 수 있지만, schema 존재와 실제 publisher 존재는 별개다.

---

## 2. Task 제출 방식

신규 workflow에서는 JSON Task API를 우선 사용한다. `/submit_task`와 `rmf_task_msgs/srv/SubmitTask`는 호환성용 legacy API로 보고, compose task, robot direct request, custom action이 필요한 경우에는 JSON API가 더 적합하다.

### Topic 방식

```text
topic: task_api_requests
type:  rmf_task_msgs/msg/ApiRequest
```

`ApiRequest` 필드:

```text
string json_msg
string request_id
```

`json_msg`에는 `rmf_api_msgs` 스키마를 따르는 JSON envelope를 문자열로 넣는다.

Fleet-level dispatch 예시:

```json
{
  "type": "dispatch_task_request",
  "request": {
    "category": "compose",
    "description": {
      "category": "table_collection",
      "detail": "tent_1 collection",
      "phases": [
        {
          "activity": {
            "category": "sequence",
            "description": {
              "activities": [
                {
                  "category": "go_to_place",
                  "description": "tent_1"
                },
                {
                  "category": "perform_action",
                  "description": {
                    "category": "wait_at_table",
                    "description": {
                      "seconds": 20
                    },
                    "unix_millis_action_duration_estimate": 20000
                  }
                }
              ]
            }
          }
        }
      ]
    },
    "requester": "task_orchestrator",
    "fleet_name": "pinky",
    "labels": ["mission_001", "table_collection", "tent_1"]
  }
}
```

특정 로봇에게 직접 보내는 예시:

```json
{
  "type": "robot_task_request",
  "fleet": "pinky",
  "robot": "pinky1",
  "request": {
    "category": "compose",
    "description": {
      "category": "warehouse_move",
      "detail": "Move assigned robot to warehouse",
      "phases": [
        {
          "activity": {
            "category": "go_to_place",
            "description": "warehouse"
          }
        }
      ]
    },
    "requester": "task_orchestrator",
    "fleet_name": "pinky",
    "labels": ["mission_001", "warehouse_move", "warehouse"]
  }
}
```

### Service 방식

```text
service: /task_api_service
type:    rmf_task_msgs/srv/ApiService
```

`ApiService`도 request/response에 `json_msg` 문자열만 싣는다. 배포 환경에서 service가 떠 있다면 topic 방식보다 동기 request/response 처리가 단순할 수 있다.

---

## 3. 제출 응답 처리

Topic 방식의 응답:

```text
topic: task_api_responses
type:  rmf_task_msgs/msg/ApiResponse
```

`ApiResponse` 필드:

```text
uint8 type
string json_msg
string request_id
```

`type` 값:

```text
TYPE_ACKNOWLEDGE = 1
TYPE_RESPONDING  = 2
```

처리 원칙:

- `TYPE_ACKNOWLEDGE`: 요청을 받았고 처리 시간을 연장한다는 의미로 본다.
- `TYPE_RESPONDING`: 최종 응답으로 보고 `json_msg`를 파싱한다.
- `request_id`: 요청 시 보낸 ID와 매칭한다.
- 이 응답은 task 진행 상태 스트림이 아니라 제출 요청에 대한 응답이다.

---

## 4. 중간 상태 추적

2.7.2 기준으로 task 진행 상태는 아래 ROS 2 message topic들을 구독해서 추적한다.

### `/dispatch_states`

Dispatch 단계 추적에 사용한다.

주요 의미:

```text
queued
selected
dispatched
failed_to_assign
canceled_in_flight
```

여기서 RMF가 어떤 task를 dispatch 중인지, 로봇 선택이 되었는지, 할당 실패가 났는지 확인한다.

### `/task_summaries`

Task 실행 상태 추적에 사용한다.

주요 의미:

```text
queued
active
completed
failed
canceled
pending
```

`TaskSummary.robot_name`, `fleet_name`, `task_id`, `state`를 이용해 mission과 실제 할당 로봇을 연결한다.

### `/fleet_states`

Robot/Fleet 상태 확인에 사용한다.

주요 용도:

- robot 위치
- battery state
- mode/state
- task_id 또는 현재 작업과의 보조 매칭

---

## 5. 서비스 Workflow 기준 권장 구조

Table call이 들어오면:

```text
task_orchestrator
  -> task_api_requests 또는 /task_api_service
  -> dispatch_task_request
```

RMF dispatch 상태 확인:

```text
/dispatch_states
  -> selected / dispatched / failed_to_assign 확인
```

할당된 로봇 확인:

```text
/task_summaries
  -> robot_name, fleet_name, task_id 확인
```

Task 완료/실패 확인:

```text
/task_summaries
  -> completed / failed / canceled 확인
```

Robot 위치/상태 보조 확인:

```text
/fleet_states
```

Storage full 이후 같은 로봇에게 warehouse task를 보낼 때:

```text
robot_task_request
  fleet: pinky
  robot: 이전 task의 assigned_robot
```

---

## 6. WebSocket과 fallback topic 조건

`server_uri`가 설정된 fleet adapter는 task/fleet 상태와 log를 WebSocket 서버로 보낼 수 있다.

```text
server_uri 설정 O
  fleet adapter -> WebSocket server -> rmf-web api-server / Socket.IO
```

PR #383 이후 버전, 즉 `rmf_task_ros2` 2.9.0+ 계열에서는 WebSocket이 없을 때 ROS 2 fallback update topic이 사용될 수 있다.

```text
server_uri 설정 X + PR #383 포함 버전
  task_state_update / task_log_update / fleet_state_update / fleet_log_update
```

하지만 현재 2.7.2 기준에서는 이 fallback topic을 기본 설계에 넣지 않는다. 상태 추적은 `/task_summaries`, `/dispatch_states`, `/fleet_states`를 기준으로 한다.

---

## 7. 설치 환경 검증 명령

설치된 RMF 버전 확인:

```bash
apt-cache policy ros-jazzy-rmf-task-ros2 ros-jazzy-rmf-fleet-adapter
```

2.7.2 StandardNames 확인:

```bash
sed -n '1,140p' /opt/ros/jazzy/include/rmf_fleet_adapter/StandardNames.hpp
```

실행 중 topic 확인:

```bash
ros2 topic list | grep -E 'task_api|task_summaries|dispatch_states|fleet_states'
```

fallback topic이 정말 있는지 확인:

```bash
ros2 topic list | grep -E 'task_state_update|task_log_update|fleet_state_update|fleet_log_update'
```

응답 message 구조 확인:

```bash
ros2 interface show rmf_task_msgs/msg/ApiResponse
```

---

## 8. 레퍼런스

| 내용 | URL |
|---|---|
| Jazzy `rmf_fleet_adapter` 2.7.2 changelog | https://index.ros.org/p/rmf_fleet_adapter/ |
| `rmf_task_ros2` PR #383 changelog, 2.9.0 | https://index.ros.org/p/rmf_task_ros2/ |
| Kilted `StandardNames.hpp` topic 이름 정의 | https://docs.ros.org/en/ros2_packages/kilted/api/rmf_fleet_adapter/_sources/generated/program_listing_file_include_rmf_fleet_adapter_StandardNames.hpp.rst.txt |
| `dispatch_delivery.py` `ApiRequest`/`ApiResponse` 사용 예시 | https://github.com/open-rmf/rmf_demos/blob/main/rmf_demos_tasks/rmf_demos_tasks/dispatch_delivery.py |
| JSON schemas | https://github.com/open-rmf/rmf_api_msgs |
