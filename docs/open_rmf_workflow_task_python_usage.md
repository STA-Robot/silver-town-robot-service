# Open-RMF Workflow, Task 단위 설계와 Python 호출 예시

## 목적

이 문서는 Pinky 주행로봇과 고정식 적재 로봇팔을 Open-RMF로 운용할 때
workflow와 task 단위를 어떻게 나눌지, 그리고 Python 노드에서 Open-RMF API를
어떻게 호출할지를 정리한다.

여기서 말하는 Python import는 `open_rmf`라는 단일 패키지를 import한다는 뜻이
아니다. ROS 2 Jazzy 기준으로는 Open-RMF가 제공하는 Python 바인딩과 메시지를
아래처럼 import해서 사용한다.

```python
import rclpy
from rclpy.node import Node

import rmf_adapter
from rmf_task_msgs.msg import ApiRequest, ApiResponse, TaskSummary, DispatchStates
from rmf_task_msgs.srv import ApiService, SubmitTask
```

Pinky adapter와 주행로봇 사이의 실제 주행 명령/상태 인터페이스는
[`rmf_pinky_drive_interface.md`](./rmf_pinky_drive_interface.md)를 따른다.
즉 orchestrator는 Pinky에게 직접 Nav2 goal을 보내지 않고, RMF task를 제출한다.
RMF fleet adapter가 그 task를 `DriveCommand`로 변환하고, Pinky는 `DriveState`로
결과를 보고한다.

## 전체 구조

권장 구조는 다음과 같다.

```text
table call / UI / API
        |
        v
task_orchestrator
        |
        |  RMF task API
        v
Open-RMF dispatcher / task manager / traffic schedule
        |
        |  robot assignment + navigation/activity commands
        v
pinky_rmf_adapter
        |
        |  DriveCommand / DriveState
        v
Pinky drive manager / Nav2
```

```
task_orchestrator
        |
        |  workcell/ingestor status + result coordination
        v
robot_arm_ingestor_adapter
        |
        |  ROS action/service
        v
fixed loading robot arm
```

역할 분리는 명확히 둔다.

- Open-RMF: 로봇 선택, traffic schedule, task 실행, parking 복귀
- `task_orchestrator`: 업무 workflow, 분기, 같은 로봇 유지, 로봇팔 workcell 결과 조정
- Pinky adapter: RMF task 실행 요청을 Pinky의 `DriveCommand`로 변환
- Pinky drive manager: `navigate`, `returning`, `stop` 등 실제 주행 명령 수행

## Workflow 단위

workflow는 사용자가 기대하는 업무 시나리오 단위다.

### Workflow A: 단순 회수

```text
table_call_received
  -> submit_table_collection_task
  -> observe_assigned_robot
  -> wait_until_table_task_completed
  -> check_storage
  -> complete_mission
  -> RMF finishing_request: park
```

의미:

- 테이블 호출 하나가 mission 하나가 된다.
- table task는 "테이블로 이동 + 일정 시간 대기"까지 포함한다.
- 보관함에 여유가 있으면 orchestrator는 추가 task를 보내지 않는다.
- task가 끝난 뒤 RMF의 `finishing_request: park`가 복귀를 수행한다.
- 복귀 중인 로봇도 RMF idle/finishing behavior 수행 중인 commissioned robot이므로 새 table call의 dispatch 후보가 될 수 있다.

### Workflow B: 회수 후 창고 이동/정리

```text
table_call_received
  -> submit_table_collection_task
  -> observe_assigned_robot
  -> wait_until_table_task_completed
  -> check_storage
  -> submit_warehouse_task_to_same_robot
  -> wait_until_warehouse_task_completed
  -> wait_until_robot_arm_workcell_completed
  -> complete_mission
  -> RMF finishing_request: park
```

의미:

- table task를 수행한 로봇 이름을 `assigned_robot`으로 저장한다.
- 보관함이 가득 찼으면 warehouse task는 반드시 같은 로봇에게 direct task로 보낸다.
- table task 완료 직후 RMF가 잠깐 `finishing_request: park`를 시작할 수 있지만, warehouse direct task가 같은 로봇에게 들어오면 복귀보다 새 업무가 우선되어야 한다.
- 창고 도착 후 로봇팔 작업은 `robot_arm_ingestor_adapter` 같은 workcell adapter를 통해 수행한다.
- workcell 성공 후 mission이 완료되면 RMF의 `finishing_request: park`가 복귀를 수행한다.

## Task 단위

Open-RMF에 제출하는 task는 workflow보다 작고 실행 가능한 단위로 나눈다.

### Task 1: Table Collection Task

목적:

- `table_1` 같은 호출 위치로 이동한다.
- 도착 후 사용자가 물건을 넣을 수 있도록 일정 시간 대기한다.

권장 RMF task 형태:

```text
category: compose
description:
  phases:
    - sequence:
        - go_to_place(table waypoint)
        - perform_action(wait_at_table)
```

이 task는 fleet-level dispatch로 제출한다. 즉 RMF가 `pinky1`, `pinky2` 중 적절한
로봇을 선택한다.

### Task 2: Warehouse Move Task

목적:

- 보관함이 가득 찬 경우, table task를 수행한 같은 로봇을 창고로 보낸다.

권장 RMF task 형태:

```text
category: compose
description:
  phases:
    - go_to_place(warehouse waypoint)
```

이 task는 robot direct request로 제출한다. `assigned_robot`을 명시해서 table
task를 수행한 로봇과 warehouse task를 수행하는 로봇이 달라지지 않도록 한다.

### Task 3: Parking Return / Idle Behavior

목적:

- mission이 끝난 로봇이 `start` 같은 대기장소로 돌아간다.

이 복귀는 orchestrator가 direct task로 제출하지 않는다. RMF의
`finishing_request: park`를 idle/finishing behavior로 사용한다.

`pinky_adapter.yaml`은 아래처럼 유지한다.

```yaml
rmf_fleet:
  finishing_request: park
```

이 방식을 쓰는 이유는 중요하다. 복귀를 일반 direct task로 만들면 RMF 입장에서
로봇이 active task를 수행 중인 상태가 되어, 새 table call의 일반 dispatch 후보에서
빠지거나 불리하게 평가될 수 있다. 반대로 `finishing_request: park`로 수행되는
복귀는 RMF의 idle/finishing behavior이므로 새 task가 들어오면 취소 가능한 대기
동작으로 다루는 것이 Open-RMF의 의도에 맞다.

storage full인 경우에는 table task가 끝난 직후 아주 잠깐 parking 복귀가 시작될 수
있다. 이때 orchestrator는 `assigned_robot`에게 warehouse task를 `robot_task_request`로
즉시 제출한다. adapter/Pinky 계층은 `returning` 중 새 `navigate` 명령이 오면 기존
returning 주행을 취소하고 warehouse 이동을 받아야 한다.

### Task 4: Robot Arm Workcell / Ingestor Task

목적:

- 창고에 도착한 Pinky 보관함의 물건을 고정식 로봇팔이 창고에 정리한다.

로봇팔은 RMF fleet이 아니라 workcell adapter로 통합한다. 특히 창고에서 물건을
받아 정리하는 의미이므로 RMF의 ingestor 패턴이 잘 맞는다.

권장 RMF-facing 인터페이스:

```text
/rmf_ingestor_states   또는 /ingestor_states   : rmf_ingestor_msgs/msg/IngestorState
/rmf_ingestor_requests 또는 /ingestor_requests : rmf_ingestor_msgs/msg/IngestorRequest
/rmf_ingestor_results  또는 /ingestor_results  : rmf_ingestor_msgs/msg/IngestorResult
```

권장 내부 인터페이스:

```text
Action/Service: UnloadAndStore
Goal:
  mobile_robot_name: pinky1
  warehouse_station: warehouse
  mission_id: mission_...
Result:
  success: true/false
  error_code: string
  message: string
```

orchestrator는 warehouse 도착 후 workcell result를 기다린다. 성공하면 mission을
완료하고, 이후 복귀는 RMF `finishing_request: park`에 맡긴다.

## RMF Task JSON 설계

아래 JSON은 Python에서 만들 task request의 기본 모양이다.

### Fleet-level dispatch: Table Collection

```python
def build_table_collection_task(
    mission_id: str,
    table_waypoint: str,
    wait_seconds: int,
) -> dict:
    return {
        "category": "compose",
        "description": {
            "category": "table_collection",
            "detail": f"{table_waypoint} collection for {mission_id}",
            "phases": [
                {
                    "activity": {
                        "category": "sequence",
                        "description": {
                            "activities": [
                                {
                                    "category": "go_to_place",
                                    "description": table_waypoint,
                                },
                                {
                                    "category": "perform_action",
                                    "description": {
                                        "category": "wait_at_table",
                                        "description": {
                                            "mission_id": mission_id,
                                            "table": table_waypoint,
                                            "seconds": wait_seconds,
                                        },
                                        "unix_millis_action_duration_estimate": (
                                            wait_seconds * 1000
                                        ),
                                    },
                                },
                            ]
                        },
                    }
                }
            ],
        },
        "labels": [mission_id, "table_collection", table_waypoint],
        "requester": "task_orchestrator",
        "fleet_name": "pinky",
    }
```

주의할 점:

- `perform_action`의 `category` 값인 `wait_at_table`은 fleet adapter가 수행 가능한
  action으로 등록해야 한다.
- 현재 adapter의 `execute_action()`은 비어 있으므로, 실제 구현 단계에서는
  `wait_at_table`을 처리하고 시간이 지나면 `execution.finished()`를 호출하도록
  adapter를 확장해야 한다.

### Robot direct request: Warehouse Move

```python
def build_warehouse_move_task(
    mission_id: str,
    warehouse_waypoint: str,
) -> dict:
    return {
        "category": "compose",
        "description": {
            "category": "warehouse_move",
            "detail": f"Move assigned robot to {warehouse_waypoint}",
            "phases": [
                {
                    "activity": {
                        "category": "go_to_place",
                        "description": warehouse_waypoint,
                    }
                }
            ],
        },
        "labels": [mission_id, "warehouse_move", warehouse_waypoint],
        "requester": "task_orchestrator",
        "fleet_name": "pinky",
    }
```

이 task request 자체에는 robot 이름을 넣지 않는다. robot direct request envelope에
`fleet`, `robot`, `request`를 함께 넣는다.

```python
def wrap_robot_task_request(
    fleet_name: str,
    robot_name: str,
    task_request: dict,
) -> dict:
    return {
        "type": "robot_task_request",
        "fleet": fleet_name,
        "robot": robot_name,
        "request": task_request,
    }
```

## Python 호출 방식 1: RMF JSON API Service 사용

검증 결과, 이 프로젝트에는 RMF JSON API service 방식이 가장 적합하다. 설치된
Jazzy 스키마에는 `dispatch_task_request`와 `robot_task_request`가 모두 있으며,
`ApiService.srv`는 JSON request/response를 그대로 전달한다. 따라서 아래 요구사항을
표현할 수 있다.

- 첫 table task는 `dispatch_task_request`로 제출해서 RMF가 최적 로봇을 선택한다.
- storage full 이후 warehouse task는 `robot_task_request`로 같은 robot에 직접 제출한다.
- mission 완료 후 복귀는 `finishing_request: park`에 맡기므로 별도 return task를 제출하지 않는다.
- `compose`, `go_to_place`, `perform_action` 스키마를 사용해 이동과 대기/작업을 묶는다.

별도 `task_orchestrator` 노드에서 가장 깔끔한 방식은 RMF task API service에
JSON request를 보내는 것이다.

```python
import json
import time
import uuid

import rclpy
from rclpy.node import Node
from rmf_task_msgs.srv import ApiService


class RmfTaskApiClient(Node):
    def __init__(self):
        super().__init__("task_orchestrator")
        # 실제 service 이름은 배포 launch에서 확인한다.
        # 일반적으로 rmf_task_msgs/srv/ApiService 타입의 task API service를 사용한다.
        self.api = self.create_client(ApiService, "/task_api_service")

    def _unix_millis_now(self) -> int:
        return int(time.time() * 1000)

    def _call_task_api(self, envelope: dict):
        request = ApiService.Request()
        request.json_msg = json.dumps(envelope)

        self.api.wait_for_service(timeout_sec=5.0)
        future = self.api.call_async(request)
        rclpy.spin_until_future_complete(self, future, timeout_sec=10.0)

        if not future.done():
            raise TimeoutError("RMF task API response timeout")

        response = future.result()
        return json.loads(response.json_msg)

    def dispatch_table_collection(
        self,
        mission_id: str,
        table_waypoint: str,
        wait_seconds: int,
    ) -> dict:
        task_request = build_table_collection_task(
            mission_id=mission_id,
            table_waypoint=table_waypoint,
            wait_seconds=wait_seconds,
        )
        task_request["unix_millis_request_time"] = self._unix_millis_now()
        task_request["unix_millis_earliest_start_time"] = self._unix_millis_now()

        envelope = {
            "type": "dispatch_task_request",
            "request": task_request,
        }
        return self._call_task_api(envelope)

    def submit_warehouse_to_same_robot(
        self,
        mission_id: str,
        assigned_robot: str,
        warehouse_waypoint: str,
    ) -> dict:
        task_request = build_warehouse_move_task(
            mission_id=mission_id,
            warehouse_waypoint=warehouse_waypoint,
        )
        task_request["unix_millis_request_time"] = self._unix_millis_now()
        task_request["unix_millis_earliest_start_time"] = self._unix_millis_now()

        envelope = wrap_robot_task_request(
            fleet_name="pinky",
            robot_name=assigned_robot,
            task_request=task_request,
        )
        return self._call_task_api(envelope)

```

사용 예:

```python
def main():
    rclpy.init()
    node = RmfTaskApiClient()

    mission_id = f"mission_{uuid.uuid4().hex[:8]}"

    table_response = node.dispatch_table_collection(
        mission_id=mission_id,
        table_waypoint="tent_1",
        wait_seconds=20,
    )
    node.get_logger().info(f"table task response: {table_response}")

    rclpy.shutdown()
```

## Python 호출 방식 2: `ApiRequest` topic 사용

배포 환경에 `/task_api_service` 대신 topic API만 열려 있다면
`ApiRequest`/`ApiResponse`를 사용한다.

```python
import json
import uuid

from rmf_task_msgs.msg import ApiRequest, ApiResponse


class RmfTaskTopicClient(Node):
    def __init__(self):
        super().__init__("task_orchestrator")
        self.pending = {}
        self.request_pub = self.create_publisher(
            ApiRequest,
            "/task_api_requests",
            10,
        )
        self.response_sub = self.create_subscription(
            ApiResponse,
            "/task_api_responses",
            self._on_api_response,
            10,
        )

    def _on_api_response(self, msg: ApiResponse):
        if msg.request_id not in self.pending:
            return

        self.pending[msg.request_id] = json.loads(msg.json_msg)

    def publish_api_request(self, envelope: dict) -> str:
        request_id = f"orchestrator_{uuid.uuid4().hex}"

        msg = ApiRequest()
        msg.request_id = request_id
        msg.json_msg = json.dumps(envelope)

        self.pending[request_id] = None
        self.request_pub.publish(msg)
        return request_id
```

fleet-level dispatch 요청:

```python
mission_id = "mission_table_1_001"
task_request = build_table_collection_task(
    mission_id=mission_id,
    table_waypoint="tent_1",
    wait_seconds=20,
)

request_id = node.publish_api_request({
    "type": "dispatch_task_request",
    "request": task_request,
})
```

같은 로봇에게 warehouse direct task 요청:

```python
warehouse_task = build_warehouse_move_task(
    mission_id=mission_id,
    warehouse_waypoint="warehouse",
)

request_id = node.publish_api_request({
    "type": "robot_task_request",
    "fleet": "pinky",
    "robot": assigned_robot,
    "request": warehouse_task,
})
```

## Python 호출 방식 3: Fleet adapter 내부에서 `adapter.dispatch_task()` 사용

orchestrator를 fleet adapter와 같은 프로세스에 넣는 구조라면 `rmf_adapter.Adapter`
객체의 `dispatch_task()`를 직접 사용할 수 있다.

이 방식은 테스트나 단순 PoC에서는 편하지만, 장기적으로는 orchestrator와 fleet
adapter를 분리하고 JSON API를 쓰는 편이 책임 분리가 좋다.

```python
import rmf_adapter


def dispatch_from_adapter_process(adapter, mission_id: str):
    task_request = build_table_collection_task(
        mission_id=mission_id,
        table_waypoint="tent_1",
        wait_seconds=20,
    )

    task_id = f"{mission_id}_table"
    adapter.dispatch_task(task_id, task_request)
```

## Python 호출 방식 4: Legacy `SubmitTask` service

`rmf_task_msgs/srv/SubmitTask`로도 task를 제출할 수 있다. 다만 이 방식은 메시지형
`TaskDescription` 중심이라 compose task, robot direct request, custom action을
표현하기에는 JSON API보다 덜 유연하다.

단순 station task 예시는 아래와 같다.

```python
from rmf_task_msgs.srv import SubmitTask
from rmf_task_msgs.msg import TaskDescription, TaskType


class LegacySubmitTaskClient(Node):
    def __init__(self):
        super().__init__("legacy_submit_task_client")
        self.client = self.create_client(SubmitTask, "/submit_task")

    def submit_station_task(self, place_name: str):
        req = SubmitTask.Request()
        req.requester = "task_orchestrator"

        req.description = TaskDescription()
        req.description.start_time = self.get_clock().now().to_msg()
        req.description.task_type.type = TaskType.TYPE_STATION
        req.description.station.task_id = f"station_{place_name}"
        req.description.station.robot_type = "pinky"
        req.description.station.place_name = place_name

        self.client.wait_for_service(timeout_sec=5.0)
        return self.client.call_async(req)
```

이 프로젝트의 table workflow에는 `SubmitTask`보다 JSON API를 우선한다. 이유는
다음과 같다.

- table 이동과 wait action을 한 task로 묶어야 한다.
- warehouse step은 특정 robot에게 direct task로 보내야 한다.
- mission label, requester, workflow별 metadata를 JSON으로 담기 쉽다.

## Task 상태 관찰

orchestrator는 task를 제출한 뒤 반드시 RMF task 상태를 관찰해야 한다.

가장 중요한 값은 다음이다.

- task id 또는 request response에서 받은 token/id
- `TaskSummary.robot_name`: 실제 할당된 로봇
- `TaskSummary.state`: queued, active, completed, failed, canceled 등
- `DispatchStates`: dispatch 중 assignment 상태와 실패 원인

예시:

```python
from rmf_task_msgs.msg import TaskSummary, DispatchStates


class MissionTracker(Node):
    def __init__(self):
        super().__init__("mission_tracker")
        self.missions_by_task_id = {}
        self.task_summary_sub = self.create_subscription(
            TaskSummary,
            "/task_summaries",
            self._on_task_summary,
            10,
        )
        self.dispatch_state_sub = self.create_subscription(
            DispatchStates,
            "/dispatch_states",
            self._on_dispatch_states,
            10,
        )

    def _on_task_summary(self, msg: TaskSummary):
        task_id = msg.task_id or msg.task_profile.task_id
        mission = self.missions_by_task_id.get(task_id)
        if mission is None:
            return

        if msg.robot_name:
            mission.assigned_robot = msg.robot_name

        if msg.state == TaskSummary.STATE_COMPLETED:
            mission.on_rmf_task_completed(task_id)
        elif msg.state in (
            TaskSummary.STATE_FAILED,
            TaskSummary.STATE_CANCELED,
        ):
            mission.on_rmf_task_failed(task_id, msg.status)

    def _on_dispatch_states(self, msg: DispatchStates):
        for state in msg.active:
            self.get_logger().debug(
                f"dispatch active: {state.task_id}, status={state.status}"
            )

        for state in msg.finished:
            if state.errors:
                self.get_logger().warning(
                    f"dispatch finished with errors: {state.task_id}, "
                    f"errors={state.errors}"
                )
```

## Orchestrator 메서드 설계

실제 `task_orchestrator`는 아래 정도의 public method를 가지면 충분하다.

```python
class TaskOrchestrator(Node):
    def on_table_call(self, table_id: str) -> str:
        """table call을 mission으로 만들고 table collection task를 제출한다."""

    def submit_table_collection_task(self, mission) -> None:
        """fleet-level dispatch task를 RMF에 제출한다."""

    def on_table_task_completed(self, mission) -> None:
        """storage 상태를 확인하고 다음 분기를 결정한다."""

    def submit_warehouse_task(self, mission) -> None:
        """assigned_robot에게 warehouse direct task를 제출한다."""

    def on_warehouse_task_completed(self, mission) -> None:
        """robot-arm workcell/ingestor 완료를 기다린다."""

    def on_workcell_done(self, mission, success: bool, message: str) -> None:
        """mission 완료 또는 intervention_required를 결정한다."""
```

mission 데이터는 최소한 아래 필드를 가진다.

```python
from dataclasses import dataclass


@dataclass
class Mission:
    mission_id: str
    table_id: str
    table_waypoint: str
    state: str
    assigned_robot: str | None = None
    current_rmf_task_id: str | None = None
    storage_full: bool | None = None
```

## Adapter 쪽 추가 요구사항

compose task 안에서 `perform_action(wait_at_table)`을 쓰려면 fleet adapter가 해당
action을 받아야 한다.

현재 `pinky_fleet_adapter.py`에는 아래 callback이 이미 연결되어 있다.

```python
lambda category, description, execution: self.execute_action(
    category, description, execution
)
```

따라서 실제 구현 단계에서는 `RobotAdapter.execute_action()`에서 다음을 처리한다.

```python
def execute_action(self, category: str, description: dict, execution):
    if category == "wait_at_table":
        seconds = float(description.get("seconds", 0.0))
        # timer 또는 thread로 seconds만큼 기다린 뒤 execution.finished() 호출
        return

    # 모르는 action이면 실패 처리 또는 경고 후 replan 정책 적용
```

그리고 fleet handle에는 `wait_at_table`이 performable action임을 등록해야 한다.
Python binding의 정확한 이름은 설치된 RMF 버전에 맞춰 확인해야 하지만, C++ API
기준 개념은 다음과 같다.

```python
fleet_handle.add_performable_action("wait_at_table", consider_callback)
fleet_handle.consider_composed_requests(consider_callback)
```

## 최종 권장안

이 프로젝트에서는 다음 순서로 구현하는 것을 권장한다.

1. `task_orchestrator`를 별도 Python ROS 2 노드로 만든다.
2. RMF task 제출은 JSON API service 또는 topic을 사용한다.
3. table task는 `compose`: `go_to_place + perform_action(wait_at_table)`로 만든다.
4. storage full이면 warehouse task를 `robot_task_request`로 같은 로봇에게 보낸다.
5. warehouse 도착 후 로봇팔은 workcell/ingestor adapter를 통해 정리 작업을 수행한다.
6. workcell 성공 후 orchestrator는 mission을 완료한다.
7. 복귀는 `finishing_request: park`에 맡겨 returning robot도 새 table call dispatch 후보가 되도록 한다.
8. storage full 직후 잠깐 시작된 returning은 warehouse direct task로 대체될 수 있어야 한다.

## 참고

- [`rmf_pinky_drive_interface.md`](./rmf_pinky_drive_interface.md)
- [`open_rmf_task_orchestrator_design.md`](./open_rmf_task_orchestrator_design.md)
- Open-RMF fleet adapter template: <https://github.com/open-rmf/fleet_adapter_template>
- Open-RMF API schemas: <https://github.com/open-rmf/rmf_api_msgs>
- 설치된 Jazzy schema 참고:
  - `/opt/ros/jazzy/share/schemas/dispatch_task_request.json`
  - `/opt/ros/jazzy/share/schemas/robot_task_request.json`
  - `/opt/ros/jazzy/share/schemas/task_request.json`
  - `/opt/ros/jazzy/include/rmf_fleet_adapter/schemas/task_description__compose.hpp`
  - `/opt/ros/jazzy/include/rmf_fleet_adapter/schemas/event_description__go_to_place.hpp`
  - `/opt/ros/jazzy/include/rmf_fleet_adapter/schemas/event_description__perform_action.hpp`
