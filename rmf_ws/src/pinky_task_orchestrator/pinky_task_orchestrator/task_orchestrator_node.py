import argparse
import sys
from pathlib import Path

import rclpy
from rclpy.node import Node
import yaml

from .states import WorkflowState


class TaskOrchestratorNode(Node):
    """Owns high-level Pinky workflows and dispatches tasks to RMF."""

    def __init__(self, config_file: str):
        super().__init__("task_orchestrator")

        self.config_file = config_file
        self.config = self._load_config(config_file)
        self._workflow_state = WorkflowState.IDLE

        self.get_logger().info(
            "Pinky task orchestrator ready. "
            f"config=[{config_file}], state=[{self._workflow_state.value}]"
        )
        self.get_logger().info(
            "TODO: connect request inputs, RMF task dispatch, and task status updates."
        )

    def _load_config(self, config_file: str) -> dict:
        path = Path(config_file)
        if not path.exists():
            self.get_logger().warn(f"Config file does not exist: {config_file}")
            return {}

        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}


def main(argv=sys.argv):
    rclpy.init(args=argv)
    args_without_ros = rclpy.utilities.remove_ros_args(argv)

    parser = argparse.ArgumentParser(
        prog="task_orchestrator_node",
        description="Start the Pinky task orchestrator node.",
    )
    parser.add_argument("--config-file", required=True)
    args, _ = parser.parse_known_args(args_without_ros[1:])

    node = TaskOrchestratorNode(args.config_file)
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main(sys.argv)
