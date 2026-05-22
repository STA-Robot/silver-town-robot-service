import argparse
from dataclasses import dataclass
import json
import sys
import time
import uuid

import rclpy
from rclpy.node import Node
from rmf_task_msgs.msg import DispatchStates, TaskSummary
from rmf_task_msgs.srv import ApiService


REQUESTER = "pinky_task_orchestrator"
DEFAULT_FLEET_NAME = "pinky"
DEFAULT_TASK_API_SERVICE = "/task_api_service"


@dataclass
class Mission:
    mission_id: str
    table_id: str
    table_waypoint: str
    state: str
    assigned_robot: str | None = None
    current_rmf_task_id: str | None = None
    storage_full: bool | None = None


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
        task_api_service: str = DEFAULT_TASK_API_SERVICE,
        default_wait_seconds: int = 20,
        warehouse_waypoint: str = "warehouse",
    ):
        super().__init__("pinky_task_orchestrator")
        self.fleet_name = fleet_name
        self.default_wait_seconds = default_wait_seconds
        self.warehouse_waypoint = warehouse_waypoint
        self.missions_by_id = {}
        self.missions_by_task_id = {}
        self.api = self.create_client(ApiService, task_api_service)
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

    def on_table_call(self, table_id: str) -> str:
        mission_id = f"mission_{uuid.uuid4().hex[:8]}"
        mission = Mission(
            mission_id=mission_id,
            table_id=table_id,
            table_waypoint=table_id,
            state="table_call_received",
        )
        self.missions_by_id[mission_id] = mission
        self.submit_table_collection_task(mission)
        return mission_id

    def submit_table_collection_task(self, mission: Mission) -> None:
        task_request = build_table_collection_task(
            mission_id=mission.mission_id,
            table_waypoint=mission.table_waypoint,
            wait_seconds=self.default_wait_seconds,
            fleet_name=self.fleet_name,
        )
        self._stamp_task_request(task_request)
        response = self._call_task_api(
            {
                "type": "dispatch_task_request",
                "request": task_request,
            }
        )
        mission.state = "table_task_submitted"
        task_id = self._extract_task_id(response)
        if task_id:
            mission.current_rmf_task_id = task_id
            self.missions_by_task_id[task_id] = mission
        self.get_logger().info(
            f"submitted table collection mission={mission.mission_id} "
            f"response={response}"
        )

    def on_table_task_completed(self, mission: Mission) -> None:
        mission.state = "table_task_completed"
        self.check_storage(mission)
        if mission.storage_full:
            self.submit_warehouse_task(mission)
            return

        mission.state = "mission_completed"
        # TODO: Publish mission completion to the UI/API layer.

    def check_storage(self, mission: Mission) -> None:
        # TODO: Connect real Pinky storage state and set mission.storage_full.
        mission.storage_full = False

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
        response = self._call_task_api(
            wrap_robot_task_request(
                fleet_name=self.fleet_name,
                robot_name=mission.assigned_robot,
                task_request=task_request,
            )
        )
        mission.state = "warehouse_task_submitted"
        task_id = self._extract_task_id(response)
        if task_id:
            mission.current_rmf_task_id = task_id
            self.missions_by_task_id[task_id] = mission
        self.get_logger().info(
            f"submitted warehouse move mission={mission.mission_id} "
            f"robot={mission.assigned_robot} response={response}"
        )

    def on_warehouse_task_completed(self, mission: Mission) -> None:
        mission.state = "warehouse_task_completed"
        # TODO: Submit or observe the robot-arm ingestor/workcell task.

    def on_workcell_done(
        self,
        mission: Mission,
        success: bool,
        message: str,
    ) -> None:
        if success:
            mission.state = "mission_completed"
            return

        mission.state = "intervention_required"
        self.get_logger().warning(
            f"workcell failed mission={mission.mission_id}: {message}"
        )
        # TODO: Add intervention workflow for workcell failures.

    def _stamp_task_request(self, task_request: dict) -> None:
        now = self._unix_millis_now()
        task_request["unix_millis_request_time"] = now
        task_request["unix_millis_earliest_start_time"] = now

    def _unix_millis_now(self) -> int:
        return int(time.time() * 1000)

    def _call_task_api(self, envelope: dict) -> dict:
        request = ApiService.Request()
        request.json_msg = json.dumps(envelope)

        if not self.api.wait_for_service(timeout_sec=5.0):
            self.get_logger().warning("RMF task API service is not available")
            # TODO: Add retry/backoff policy for task API availability.
            return {}

        future = self.api.call_async(request)
        rclpy.spin_until_future_complete(self, future, timeout_sec=10.0)
        if not future.done():
            self.get_logger().warning("RMF task API response timeout")
            # TODO: Decide how mission state should represent submit timeout.
            return {}

        response = future.result()
        return json.loads(response.json_msg)

    def _extract_task_id(self, response: dict) -> str | None:
        for key in ("task_id", "request_id", "booking"):
            value = response.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, dict) and isinstance(value.get("id"), str):
                return value["id"]
        # TODO: Confirm deployed RMF API response field for task id/token.
        return None

    def _on_task_summary(self, msg: TaskSummary) -> None:
        task_id = msg.task_id or msg.task_profile.task_id
        mission = self.missions_by_task_id.get(task_id)
        if mission is None:
            return

        if msg.robot_name:
            mission.assigned_robot = msg.robot_name

        if msg.state == TaskSummary.STATE_COMPLETED:
            if mission.state == "warehouse_task_submitted":
                self.on_warehouse_task_completed(mission)
            else:
                self.on_table_task_completed(mission)
        elif msg.state in (
            TaskSummary.STATE_FAILED,
            TaskSummary.STATE_CANCELED,
        ):
            mission.state = "rmf_task_failed"
            self.get_logger().warning(
                f"mission={mission.mission_id} task={task_id} failed: {msg.status}"
            )
            # TODO: Add mission failure/intervention policy.

    def _on_dispatch_states(self, msg: DispatchStates) -> None:
        for state in msg.finished:
            if state.errors:
                self.get_logger().warning(
                    f"dispatch finished with errors: {state.task_id}, "
                    f"errors={state.errors}"
                )
                # TODO: Attach dispatch errors to the matching mission.


def main(argv=sys.argv):
    rclpy.init(args=argv)
    args_without_ros = rclpy.utilities.remove_ros_args(argv)

    parser = argparse.ArgumentParser(
        prog="pinky_task_orchestrator",
        description="Submit Pinky workflow tasks to the RMF task API.",
    )
    parser.add_argument("--fleet-name", default=DEFAULT_FLEET_NAME)
    parser.add_argument("--task-api-service", default=DEFAULT_TASK_API_SERVICE)
    parser.add_argument("--table-waypoint", default="")
    parser.add_argument("--wait-seconds", type=int, default=20)
    parser.add_argument("--warehouse-waypoint", default="warehouse")
    args = parser.parse_args(args_without_ros[1:])

    node = PinkyTaskOrchestrator(
        fleet_name=args.fleet_name,
        task_api_service=args.task_api_service,
        default_wait_seconds=args.wait_seconds,
        warehouse_waypoint=args.warehouse_waypoint,
    )

    if args.table_waypoint:
        mission_id = node.on_table_call(args.table_waypoint)
        node.get_logger().info(f"created one-shot mission [{mission_id}]")
        node.destroy_node()
        rclpy.shutdown()
        return

    # TODO: Add table-call UI/API/topic input; v1 exposes methods and one-shot CLI.
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main(sys.argv)
