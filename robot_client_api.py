from .robot_command_client import RobotCommandClient


class RobotUpdateData:
    def __init__(
        self,
        robot_name: str,
        map: str,
        position: list[float],
        battery_soc: float,
        state: str = "unknown",
        available: bool = False,
        emergency: bool = False,
        requires_replan: bool | None = None,
    ):
        self.robot_name = robot_name
        self.position = position
        self.map = map
        self.battery_soc = battery_soc
        self.state = state
        self.available = available
        self.emergency = emergency
        self.requires_replan = requires_replan


class RobotAPI:
    """Template-facing robot API that delegates ROS/Nav2 work per robot."""

    def __init__(self, config_yaml: dict, node):
        self.node = node
        self.config_yaml = config_yaml
        self.clients: dict[str, RobotCommandClient] = {}

        robot_configs = config_yaml.get("robots", {})
        if not robot_configs:
            node.get_logger().warn("fleet_manager.robots is empty")

        for robot_name, robot_config in robot_configs.items():
            self.clients[robot_name] = RobotCommandClient(
                node, robot_name, robot_config or {}
            )

    def _client(self, robot_name: str) -> RobotCommandClient | None:
        client = self.clients.get(robot_name)
        if client is None:
            self.node.get_logger().warn(f"No RobotCommandClient for [{robot_name}]")
        return client

    def check_connection(self) -> bool:
        if not self.clients:
            return False
        return all(client.check_connection() for client in self.clients.values())

    def localize(self, robot_name: str, pose, map_name: str) -> bool:
        del pose
        client = self._client(robot_name)
        if client is None:
            return False
        return map_name == client.map_name()

    def navigate(
        self,
        robot_name: str,
        pose,
        map_name: str,
        speed_limit=0.0,
        destination_name: str = "",
        command_mode: str = "task",
    ) -> bool:
        client = self._client(robot_name)
        if client is None:
            return False
        if not client.is_available():
            drive_state = client.drive_state()
            state = "unknown" if drive_state is None else drive_state.state
            self.node.get_logger().warn(
                f"[{robot_name}] refusing navigation because drive state is [{state}]"
            )
            return False
        return client.send_goal(
            list(pose),
            map_name,
            speed_limit,
            destination_name=destination_name,
            command_mode=command_mode,
        )

    def start_activity(self, robot_name: str, activity: str, label: str) -> bool:
        del robot_name, activity, label
        return False

    def stop(self, robot_name: str) -> bool:
        client = self._client(robot_name)
        if client is None:
            return False
        return client.cancel_goal()

    def position(self, robot_name: str) -> list[float] | None:
        client = self._client(robot_name)
        if client is None:
            return None
        return client.position()

    def battery_soc(self, robot_name: str) -> float | None:
        client = self._client(robot_name)
        if client is None:
            return None
        return client.battery_soc()

    def map(self, robot_name: str) -> str | None:
        client = self._client(robot_name)
        if client is None:
            return None
        return client.map_name()

    def is_command_completed(self, robot_name: str | None = None) -> bool:
        if robot_name is not None:
            client = self._client(robot_name)
            return False if client is None else client.is_command_completed()
        return any(client.is_command_completed() for client in self.clients.values())

    def requires_replan(self, robot_name: str) -> bool:
        client = self._client(robot_name)
        return False if client is None else client.requires_replan()

    def drive_state(self, robot_name: str):
        client = self._client(robot_name)
        return None if client is None else client.drive_state()

    def get_data(self, robot_name: str):
        client = self._client(robot_name)
        if client is None:
            return None
        drive_state = client.drive_state()
        if drive_state is None or drive_state.state == "unknown":
            return None

        map_name = drive_state.map_name or client.map_name()
        position = [float(v) for v in drive_state.pose]
        battery_soc = client.battery_soc()
        if map_name is None or position is None or battery_soc is None:
            return None
        return RobotUpdateData(
            robot_name,
            map_name,
            position,
            battery_soc,
            drive_state.state,
            bool(drive_state.available),
            bool(drive_state.emergency),
            client.requires_replan(),
        )
