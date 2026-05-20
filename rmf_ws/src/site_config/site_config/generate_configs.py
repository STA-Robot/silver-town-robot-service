import argparse
from copy import deepcopy
from pathlib import Path
import sys

import yaml


GENERATED_HEADER = (
    "# Generated from site_config/config/rmf_test.site.yaml.\n"
    "# Edit the site config and rerun `ros2 run site_config generate_configs`.\n"
)

ROBOT_ADAPTER_KEYS = {"rmf_level", "drive_namespace", "drive_api"}


def deep_merge(base: dict, overlay: dict) -> dict:
    merged = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def load_site_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def require_mapping(data: dict, path: str) -> dict:
    current = data
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            raise ValueError(f"Missing required config key: {path}")
        current = current[key]

    if not isinstance(current, dict):
        raise ValueError(f"Expected mapping at config key: {path}")
    return current


def require_value(data: dict, path: str):
    current = data
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            raise ValueError(f"Missing required config key: {path}")
        current = current[key]

    if current in (None, ""):
        raise ValueError(f"Config key must not be empty: {path}")
    return current


def validate_site_config(site_config: dict):
    require_value(site_config, "site.name")
    require_value(site_config, "site.default_map")
    require_mapping(site_config, "maps")
    require_mapping(site_config, "fleet.rmf_fleet")
    require_value(site_config, "fleet.rmf_fleet.name")
    robots = require_mapping(site_config, "fleet.robots")
    require_mapping(site_config, "reference_coordinates")

    for robot_name, robot in robots.items():
        if not isinstance(robot, dict):
            raise ValueError(f"Expected mapping for fleet.robots.{robot_name}")
        require_value(site_config, f"fleet.robots.{robot_name}.rmf_level")
        require_value(site_config, f"fleet.robots.{robot_name}.charger")
        require_value(site_config, f"fleet.robots.{robot_name}.drive_namespace")


def build_adapter_config(site_config: dict) -> dict:
    fleet = require_mapping(site_config, "fleet")

    rmf_fleet = deepcopy(require_mapping(fleet, "rmf_fleet"))
    robots = require_mapping(fleet, "robots")
    rmf_fleet["robots"] = {
        name: {
            key: deepcopy(value)
            for key, value in robot.items()
            if key not in ROBOT_ADAPTER_KEYS
        }
        for name, robot in robots.items()
    }

    fleet_manager = deepcopy(require_mapping(fleet, "fleet_manager"))
    robot_defaults = fleet_manager.pop("robot_defaults", {})
    fleet_manager["robots"] = {}
    for name, robot in robots.items():
        robot_config = {
            "rmf_level": robot["rmf_level"],
            "drive_namespace": robot["drive_namespace"],
        }
        robot_config = deep_merge(robot_config, robot_defaults)
        robot_config = deep_merge(robot_config, robot.get("drive_api", {}))
        fleet_manager["robots"][name] = robot_config

    return {
        "rmf_fleet": rmf_fleet,
        "fleet_manager": fleet_manager,
        "reference_coordinates": deepcopy(
            site_config.get("reference_coordinates", {})
        ),
    }


def build_orchestrator_config(site_config: dict) -> dict:
    site = require_mapping(site_config, "site")
    fleet = require_mapping(site_config, "fleet")
    rmf_fleet = require_mapping(fleet, "rmf_fleet")
    robots = require_mapping(fleet, "robots")

    return {
        "orchestrator": {
            "name": "pinky_task_orchestrator",
            "fleet_name": rmf_fleet["name"],
            "default_map": site["default_map"],
        },
        "robots": list(robots.keys()),
        "locations": deepcopy(site_config.get("locations", {})),
        "workflows": deepcopy(site_config.get("workflows", {})),
        "rmf_task_dispatch": deepcopy(site_config.get("rmf_task_dispatch", {})),
    }


def write_yaml(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    path.write_text(GENERATED_HEADER + body, encoding="utf-8")


def default_rmf_ws_root() -> Path:
    cwd = Path.cwd()
    if cwd.name == "rmf_ws":
        return cwd
    if (cwd / "rmf_ws" / "src").exists():
        return cwd / "rmf_ws"
    return cwd


def main(argv=None):
    rmf_ws_root = default_rmf_ws_root()
    default_site_config = (
        rmf_ws_root / "src" / "site_config" / "config" / "rmf_test.site.yaml"
    )

    parser = argparse.ArgumentParser(
        prog="generate_configs",
        description="Generate RMF adapter/orchestrator configs from site SoT.",
    )
    parser.add_argument("--site-config", default=str(default_site_config))
    parser.add_argument("--rmf-ws-root", default=str(rmf_ws_root))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    root = Path(args.rmf_ws_root).resolve()
    site_config_path = Path(args.site_config).resolve()
    site_config = load_site_config(site_config_path)
    validate_site_config(site_config)

    adapter_output = (
        root / "src" / "pinky_rmf_adapter" / "config" / "pinky_adapter.yaml"
    )
    orchestrator_output = (
        root / "src" / "pinky_task_orchestrator" / "config" / "task_orchestrator.yaml"
    )
    outputs = {
        adapter_output: build_adapter_config(site_config),
        orchestrator_output: build_orchestrator_config(site_config),
    }

    if args.check:
        for output in outputs:
            print(output)
        return 0

    for path, data in outputs.items():
        write_yaml(path, data)
        print(f"generated: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
