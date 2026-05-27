import argparse
from dataclasses import dataclass
import json
import sys
import time
import uuid

import rclpy
from rclpy.node import Node
from rclpy.task import Future
from rmf_fleet_msgs.msg import FleetState
from rmf_task_msgs.msg import ApiRequest, ApiResponse, DispatchStates, TaskSummary
from pinky_task_msgs.srv import TableCall
import yaml


REQUESTER = "pinky_task_orchestrator"
DEFAULT_FLEET_NAME = "pinky"
DEFAULT_TASK_API_REQUEST_TOPIC = "task_api_requests"
DEFAULT_TASK_API_RESPONSE_TOPIC = "task_api_responses"
TASK_STATE_NAMES = {
    TaskSummary.STATE_QUEUED: "queued",
    TaskSummary.STATE_ACTIVE: "active",
    TaskSummary.STATE_COMPLETED: "completed",
    TaskSummary.STATE_FAILED: "failed",
    TaskSummary.STATE_CANCELED: "canceled",
    TaskSummary.STATE_PENDING: "pending",
}
DISPATCH_STATUS_NAMES = {
    0: "uninitialized",
    1: "queued",
    2: "selected",
    3: "dispatched",
    4: "failed_to_assign",
    5: "canceled_in_flight",
}


@dataclass
class Mission:
    mission_id: str
    table_id: str
    table_waypoint: str
    state: str
    assigned_robot: str | None = None
    current_rmf_task_id: str | None = None
    storage_full: bool | None = None
    wait_seconds: int | None = None


def build_table_collection_task(
    mission_id: str,
    table_waypoint: str,
    wait_seconds: int,
    fleet_name: str = DEFAULT_FLEET_NAME,
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
        "requester": REQUESTER,
        "fleet_name": fleet_name,
    }


def build_warehouse_move_task(
    mission_id: str,
    warehouse_waypoint: str,
    fleet_name: str = DEFAULT_FLEET_NAME,
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
        "requester": REQUESTER,
        "fleet_name": fleet_name,
    }


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


class PinkyTaskOrchestrator(Node):
    def __init__(
        self,
        fleet_name: str = DEFAULT_FLEET_NAME,
        task_api_request_topic: str = DEFAULT_TASK_API_REQUEST_TOPIC,
        task_api_response_topic: str = DEFAULT_TASK_API_RESPONSE_TOPIC,
        default_wait_seconds: int = 20,
        warehouse_waypoint: str = "warehouse",
    ):
        super().__init__("pinky_task_orchestrator")
        self.fleet_name = fleet_name
        self.task_api_request_topic = task_api_request_topic
        self.task_api_response_topic = task_api_response_topic
        self.default_wait_seconds = default_wait_seconds
        self.warehouse_waypoint = warehouse_waypoint
        self.missions_by_id = {}
        self.missions_by_task_id = {}
        self.completed_rmf_task_ids = set()
        self.pending_api_requests = {}
        self.fleet_robot_states = {}
        self.api_request_pub = self.create_publisher(
            ApiRequest,
            task_api_request_topic,
            10,
        )
        self.api_response_sub = self.create_subscription(
            ApiResponse,
            task_api_response_topic,
            self._on_api_response,
            10,
        )
        self.table_call_srv = self.create_service(
            TableCall,
            "/table_call",
            self._on_table_call_request,
        )
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
        self.fleet_state_sub = self.create_subscription(
            FleetState,
            "/fleet_states",
            self._on_fleet_state,
            10,
        )
        self.get_logger().info(
            f"PinkyTaskOrchestrator ready fleet={self.fleet_name} "
            f"task_api_topics={task_api_request_topic},{task_api_response_topic} "
            f"wait_seconds={self.default_wait_seconds} "
            f"warehouse={self.warehouse_waypoint} table_call_service=/table_call"
        )

    def _create_table_mission(
        self,
        table_id: str,
        table_waypoint: str | None = None,
        wait_seconds: int | None = None,
    ) -> Mission:
        mission_id = f"mission_{uuid.uuid4().hex[:8]}"
        waypoint = table_waypoint or table_id
        mission = Mission(
            mission_id=mission_id,
            table_id=table_id,
            table_waypoint=waypoint,
            state="created",
            wait_seconds=wait_seconds,
        )
        self.missions_by_id[mission_id] = mission
        self._log_mission_transition(
            mission,
            "table_call_received",
            f"table={table_id} waypoint={waypoint}",
        )
        return mission

    def on_table_call(
        self,
        table_id: str,
        table_waypoint: str | None = None,
        wait_seconds: int | None = None,
    ) -> str:
        mission = self._create_table_mission(
            table_id=table_id,
            table_waypoint=table_waypoint,
            wait_seconds=wait_seconds,
        )
        self.submit_table_collection_task(mission)
        return mission.mission_id

    def submit_table_collection_task(self, mission: Mission) -> None:
        wait_seconds = mission.wait_seconds or self.default_wait_seconds
        task_request = build_table_collection_task(
            mission_id=mission.mission_id,
            table_waypoint=mission.table_waypoint,
            wait_seconds=wait_seconds,
            fleet_name=self.fleet_name,
        )
        self._stamp_task_request(task_request)
        self.get_logger().debug(
            f"dispatch table_collection request mission={mission.mission_id} "
            f"table={mission.table_waypoint} wait={wait_seconds}s"
        )
        response = self._call_task_api(
            {
                "type": "dispatch_task_request",
                "request": task_request,
            }
        )
        self._handle_table_collection_response(mission, response)
        if response.get("success", False):
            self.get_logger().info(
                f"submitted table collection mission={mission.mission_id} "
                f"response={response}"
            )

    def submit_table_collection_task_async(self, mission: Mission) -> None:
        wait_seconds = mission.wait_seconds or self.default_wait_seconds
        task_request = build_table_collection_task(
            mission_id=mission.mission_id,
            table_waypoint=mission.table_waypoint,
            wait_seconds=wait_seconds,
            fleet_name=self.fleet_name,
        )
        self._stamp_task_request(task_request)
        self.get_logger().info(
            f"dispatch table_collection request mission={mission.mission_id} "
            f"table={mission.table_waypoint} wait={wait_seconds}s"
        )
        future = self._call_task_api_async(
            {
                "type": "dispatch_task_request",
                "request": task_request,
            }
        )

        future.add_done_callback(
            lambda completed: self._on_table_collection_response(
                mission,
                completed,
            )
        )

    def _handle_table_collection_response(
        self,
        mission: Mission,
        response: dict,
    ) -> None:
        if not response.get("success", False):
            self._log_mission_transition(mission, "table_task_submit_failed")
            self.get_logger().warning(
                f"failed to submit table collection mission={mission.mission_id} "
                f"response={response}"
            )
            return

        task_id = self._extract_task_id(response)
        if task_id:
            mission.current_rmf_task_id = task_id
            self.missions_by_task_id[task_id] = mission
            self.get_logger().debug(
                f"track rmf task task_id={task_id} mission={mission.mission_id}"
            )
        self._log_mission_transition(mission, "table_task_submitted")

    def _on_table_collection_response(self, mission: Mission, future) -> None:
        response = self._future_json_result(future)
        self._handle_table_collection_response(mission, response)
        if response.get("success", False):
            self.get_logger().info(
                f"submitted table collection mission={mission.mission_id} "
                f"response={response}"
            )

    def _on_table_call_request(
        self,
        request: TableCall.Request,
        response: TableCall.Response,
    ) -> TableCall.Response:
        table_id = request.table_id.strip()
        table_waypoint = request.table_waypoint.strip() or table_id
        wait_seconds = int(request.wait_seconds) or self.default_wait_seconds

        if not table_id:
            response.accepted = False
            response.mission_id = ""
            response.message = "table_id is required"
            return response

        mission = self._create_table_mission(
            table_id=table_id,
            table_waypoint=table_waypoint,
            wait_seconds=wait_seconds,
        )
        self.submit_table_collection_task_async(mission)

        response.accepted = True
        response.mission_id = mission.mission_id
        response.message = "table call accepted; RMF submission pending"
        self.get_logger().info(
            f"accepted table_call mission={mission.mission_id} "
            f"table={table_id} waypoint={table_waypoint}"
        )
        return response

    def on_table_task_completed(self, mission: Mission) -> None:
        self._log_mission_transition(mission, "table_task_completed")
        self.check_storage(mission)
        if mission.storage_full:
            self.submit_warehouse_task(mission)
            return

        self._log_mission_transition(mission, "mission_completed")
        # TODO: Publish mission completion to the UI/API layer.

    def check_storage(self, mission: Mission) -> None:
        # TODO: Connect real Pinky storage state and set mission.storage_full.
        mission.storage_full = False
        self.get_logger().debug(
            f"storage check mission={mission.mission_id} "
            f"storage_full={mission.storage_full}"
        )

    def submit_warehouse_task(self, mission: Mission) -> None:
        if not mission.assigned_robot:
            self.get_logger().warning(
                f"mission [{mission.mission_id}] has no assigned robot yet"
            )
            # TODO: Decide whether to wait, fail, or retry when assignment is missing.
            return

        task_request = build_warehouse_move_task(
            mission_id=mission.mission_id,
            warehouse_waypoint=self.warehouse_waypoint,
            fleet_name=self.fleet_name,
        )
        self._stamp_task_request(task_request)
        future = self._call_task_api_async(
            wrap_robot_task_request(
                fleet_name=self.fleet_name,
                robot_name=mission.assigned_robot,
                task_request=task_request,
            )
        )
        future.add_done_callback(
            lambda completed: self._on_warehouse_response(
                mission,
                completed,
            )
        )
        self.get_logger().debug(
            f"published warehouse robot_task_request mission={mission.mission_id} "
            f"robot={mission.assigned_robot} waypoint={self.warehouse_waypoint}"
        )

    def _handle_warehouse_response(self, mission: Mission, response: dict) -> None:
        if not response.get("success", False):
            self._log_mission_transition(mission, "warehouse_task_submit_failed")
            self.get_logger().warning(
                f"failed to submit warehouse move mission={mission.mission_id} "
                f"robot={mission.assigned_robot} response={response}"
            )
            return

        self.get_logger().debug(
            f"submit warehouse robot_task_request mission={mission.mission_id} "
            f"robot={mission.assigned_robot} waypoint={self.warehouse_waypoint}"
        )
        self._log_mission_transition(mission, "warehouse_task_submitted")
        task_id = self._extract_task_id(response)
        if task_id:
            mission.current_rmf_task_id = task_id
            self.missions_by_task_id[task_id] = mission
            self.get_logger().debug(
                f"track rmf task task_id={task_id} mission={mission.mission_id}"
            )
        self.get_logger().info(
            f"submitted warehouse move mission={mission.mission_id} "
            f"robot={mission.assigned_robot} response={response}"
        )

    def _on_warehouse_response(self, mission: Mission, future) -> None:
        response = self._future_json_result(future)
        self._handle_warehouse_response(mission, response)

    def on_warehouse_task_completed(self, mission: Mission) -> None:
        self._log_mission_transition(mission, "warehouse_task_completed")
        # TODO: Submit or observe the robot-arm ingestor/workcell task.

    def on_workcell_done(
        self,
        mission: Mission,
        success: bool,
        message: str,
    ) -> None:
        if success:
            self._log_mission_transition(mission, "mission_completed")
            return

        self._log_mission_transition(mission, "intervention_required")
        self.get_logger().warning(
            f"workcell failed mission={mission.mission_id}: {message}"
        )
        # TODO: Add intervention workflow for workcell failures.

    def _log_mission_transition(
        self,
        mission: Mission,
        new_state: str,
        detail: str = "",
    ) -> None:
        old_state = mission.state
        mission.state = new_state
        suffix = f" {detail}" if detail else ""
        self.get_logger().info(
            f"mission={mission.mission_id} {old_state}->{new_state}"
            f" task_id={mission.current_rmf_task_id} "
            f"robot={mission.assigned_robot}{suffix}"
        )

    def _task_state_name(self, state: int) -> str:
        return TASK_STATE_NAMES.get(state, f"unknown({state})")

    def _dispatch_status_name(self, status: int) -> str:
        return DISPATCH_STATUS_NAMES.get(status, f"unknown({status})")

    def _stamp_task_request(self, task_request: dict) -> None:
        now = self._unix_millis_now()
        task_request["unix_millis_request_time"] = now
        task_request["unix_millis_earliest_start_time"] = now

    def _unix_millis_now(self) -> int:
        return int(time.time() * 1000)

    def _call_task_api(self, envelope: dict) -> dict:
        future = self._publish_task_api_request(envelope)
        rclpy.spin_until_future_complete(self, future, timeout_sec=10.0)
        if not future.done():
            self._forget_pending_api_request(future)
            self.get_logger().warning("RMF task API response timeout")
            # TODO: Decide how mission state should represent submit timeout.
            return {"success": False, "message": "task API response timeout"}

        return self._future_json_result(future)

    def _call_task_api_async(self, envelope: dict):
        return self._publish_task_api_request(envelope)

    def _publish_task_api_request(self, envelope: dict):
        request_id = f"orchestrator_{uuid.uuid4().hex}"
        future = Future()
        setattr(future, "request_id", request_id)
        self.pending_api_requests[request_id] = future

        msg = ApiRequest()
        msg.request_id = request_id
        msg.json_msg = json.dumps(envelope)
        self.api_request_pub.publish(msg)
        self.get_logger().info(
            f"published task API request request_id={request_id} "
            f"type={envelope.get('type')}"
        )
        return future

    def _on_api_response(self, msg: ApiResponse) -> None:
        future = self.pending_api_requests.get(msg.request_id)
        if future is None:
            self.get_logger().warn(
                f"ignoring task API response for unknown request_id={msg.request_id}"
            )
            return

        if msg.type == ApiResponse.TYPE_ACKNOWLEDGE:
            self.get_logger().info(
                f"task API acknowledged request_id={msg.request_id}"
            )
            return

        self.pending_api_requests.pop(msg.request_id, None)
        if msg.type != ApiResponse.TYPE_RESPONDING:
            self.get_logger().warning(
                f"task API response failed request_id={msg.request_id} "
                f"unexpected_type={msg.type}"
            )
            future.set_result(
                {
                    "success": False,
                    "message": f"unexpected ApiResponse.type={msg.type}",
                }
            )
            return

        response = self._parse_task_api_json(msg.json_msg)
        if response.get("success", False):
            self.get_logger().info(
                f"task API response succeeded request_id={msg.request_id} "
                f"task_id={self._extract_task_id(response)}"
            )

        future.set_result(response)

    def _forget_pending_api_request(self, future) -> None:
        request_id = getattr(future, "request_id", None)
        if request_id:
            self.pending_api_requests.pop(request_id, None)

    def _future_json_result(self, future) -> dict:
        try:
            response = future.result()
        except Exception as exc:
            self.get_logger().warning(f"RMF task API failed: {exc}")
            return {"success": False, "message": str(exc)}

        if isinstance(response, dict):
            return self._normalize_task_api_response(response)

        return {
            "success": False,
            "message": f"unexpected task API response type {type(response).__name__}",
        }

    def _parse_task_api_json(self, json_msg: str) -> dict:
        try:
            response = json.loads(json_msg)
        except Exception as exc:
            self.get_logger().warning(f"malformed RMF task API response: {exc}")
            return {"success": False, "message": str(exc)}

        if not isinstance(response, dict):
            return {
                "success": False,
                "message": f"unexpected task API JSON response: {response}",
            }

        return self._normalize_task_api_response(response)

    def _normalize_task_api_response(self, response: dict) -> dict:
        normalized = dict(response)
        task_id = self._extract_task_id(normalized)
        if task_id and "task_id" not in normalized:
            normalized["task_id"] = task_id

        if "success" not in normalized and "state" in normalized:
            normalized["success"] = True

        if not normalized.get("success", False) and "message" not in normalized:
            normalized["message"] = self._format_task_api_errors(normalized)

        return normalized

    def _format_task_api_errors(self, response: dict) -> str:
        errors = response.get("errors")
        if isinstance(errors, list) and errors:
            return "; ".join(
                str(error.get("detail") or error.get("category") or error)
                if isinstance(error, dict)
                else str(error)
                for error in errors
            )
        if isinstance(response.get("error"), str):
            return response["error"]
        return "task API request failed"

    def _extract_task_id(self, response: dict) -> str | None:
        for key in ("task_id", "request_id", "booking"):
            value = response.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, dict) and isinstance(value.get("id"), str):
                return value["id"]

        state = response.get("state")
        if isinstance(state, dict):
            return self._extract_task_id(state)

        return None

    def _on_task_summary(self, msg: TaskSummary) -> None:
        task_id = msg.task_id or msg.task_profile.task_id
        mission = self.missions_by_task_id.get(task_id)
        state_name = self._task_state_name(msg.state)
        if mission is None:
            self.get_logger().debug(
                f"task_summary untracked task_id={task_id} "
                f"state={state_name} robot={msg.robot_name} status={msg.status}"
            )
            return

        self.get_logger().debug(
            f"task_summary mission={mission.mission_id} task_id={task_id} "
            f"state={state_name} robot={msg.robot_name} status={msg.status}"
        )

        if msg.robot_name and mission.assigned_robot != msg.robot_name:
            mission.assigned_robot = msg.robot_name
            self.get_logger().info(
                f"mission={mission.mission_id} assigned_robot={msg.robot_name} "
                f"task_id={task_id}"
            )

        if msg.state == TaskSummary.STATE_COMPLETED:
            if task_id in self.completed_rmf_task_ids:
                self.get_logger().debug(
                    f"task_summary duplicate completed task_id={task_id} "
                    f"mission={mission.mission_id}"
                )
                return

            self.completed_rmf_task_ids.add(task_id)
            self.get_logger().info(
                f"task completed mission={mission.mission_id} "
                f"task_id={task_id} robot={mission.assigned_robot}"
            )
            if mission.state == "warehouse_task_submitted":
                self.on_warehouse_task_completed(mission)
            else:
                self.on_table_task_completed(mission)
        elif msg.state in (
            TaskSummary.STATE_FAILED,
            TaskSummary.STATE_CANCELED,
        ):
            self._log_mission_transition(mission, "rmf_task_failed")
            self.get_logger().warning(
                f"mission={mission.mission_id} task={task_id} failed: {msg.status}"
            )
            # TODO: Add mission failure/intervention policy.

    def _on_dispatch_states(self, msg: DispatchStates) -> None:
        for state in msg.active:
            self.get_logger().debug(
                f"dispatch active task_id={state.task_id} "
                f"status={self._dispatch_status_name(state.status)} "
                f"assigned={state.assignment.is_assigned} "
                f"fleet={state.assignment.fleet_name} "
                f"robot={state.assignment.expected_robot_name} "
                f"errors={list(state.errors)}"
            )

        for state in msg.finished:
            self.get_logger().debug(
                f"dispatch finished task_id={state.task_id} "
                f"status={self._dispatch_status_name(state.status)} "
                f"assigned={state.assignment.is_assigned} "
                f"fleet={state.assignment.fleet_name} "
                f"robot={state.assignment.expected_robot_name} "
                f"errors={list(state.errors)}"
            )
            if state.errors:
                self.get_logger().warning(
                    f"dispatch finished with errors: {state.task_id}, "
                    f"errors={state.errors}"
                )
                # TODO: Attach dispatch errors to the matching mission.



    def _on_fleet_state(self, msg: FleetState) -> None:
        if msg.name != self.fleet_name:
            return

        for robot in msg.robots:
            self.fleet_robot_states[robot.name] = robot
            self.get_logger().debug(
                f"fleet_state robot={robot.name} task_id={robot.task_id} "
                f"mode={robot.mode.mode} battery={robot.battery_percent:.1f}"
            )

def _load_config(config_file: str) -> dict:
    if not config_file:
        return {}

    with open(config_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main(argv=sys.argv):
    rclpy.init(args=argv)
    args_without_ros = rclpy.utilities.remove_ros_args(argv)

    parser = argparse.ArgumentParser(
        prog="pinky_task_orchestrator",
        description="Submit Pinky workflow tasks to the RMF task API.",
    )
    parser.add_argument("--config-file", default="")
    parser.add_argument("--fleet-name", default=DEFAULT_FLEET_NAME)
    parser.add_argument(
        "--task-api-request-topic",
        default=DEFAULT_TASK_API_REQUEST_TOPIC,
    )
    parser.add_argument(
        "--task-api-response-topic",
        default=DEFAULT_TASK_API_RESPONSE_TOPIC,
    )
    parser.add_argument("--table-waypoint", default="")
    parser.add_argument("--wait-seconds", type=int, default=20)
    parser.add_argument("--warehouse-waypoint", default="warehouse")
    args = parser.parse_args(args_without_ros[1:])

    config = _load_config(args.config_file)

    node = PinkyTaskOrchestrator(
        fleet_name=config.get("fleet_name", args.fleet_name),
        task_api_request_topic=config.get(
            "task_api_request_topic",
            args.task_api_request_topic,
        ),
        task_api_response_topic=config.get(
            "task_api_response_topic",
            args.task_api_response_topic,
        ),
        default_wait_seconds=int(
            config.get("default_wait_seconds", args.wait_seconds)
        ),
        warehouse_waypoint=config.get(
            "warehouse_waypoint",
            args.warehouse_waypoint,
        ),
    )

    if args.table_waypoint:
        mission_id = node.on_table_call(
            table_id=args.table_waypoint,
            wait_seconds=args.wait_seconds,
        )
        node.get_logger().info(f"created one-shot mission [{mission_id}]")
        node.destroy_node()
        rclpy.shutdown()
        return

    # TODO: Add UI/topic input and multi-destination request handling.
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main(sys.argv)
