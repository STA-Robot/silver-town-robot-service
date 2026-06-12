import pytest

from jetcobot_manager.arm_manager_node import (
    ConfigError,
    validate_arm_manager_config,
)


def _valid_config():
    return {
        "pick_place": {
            "action_name": "/pick_place",
            "server_timeout": 5.0,
            "seconds_estimate": 30.0,
            "feedback_iteration_budget": 150,
            "task_id_source": "command_id",
            "state_map": {
                "GO_READY": "homing",
                "SEARCHING": "aligning",
                "SERVO": "aligning",
                "OFFSET_MOVE": "picking",
                "DESCENDING": "picking",
                "GRIPPING": "picking",
                "LIFTING": "picking",
                "SERVO_FAILED": "blocked",
            },
        },
    }


def test_validate_arm_manager_config_accepts_pick_place_config():
    config = validate_arm_manager_config(_valid_config())

    assert config["pick_place"]["action_name"] == "/pick_place"
    assert config["pick_place"]["server_timeout"] == pytest.approx(5.0)
    assert config["pick_place"]["state_map"]["GO_READY"] == "homing"


def test_validate_arm_manager_config_supplies_pick_place_defaults():
    config = validate_arm_manager_config({})

    assert config["pick_place"]["action_name"] == "/pick_place"
    assert config["pick_place"]["feedback_iteration_budget"] == 150
    assert config["pick_place"]["state_map"]["SERVO_FAILED"] == "blocked"


def test_validate_arm_manager_config_rejects_bad_pick_place_section():
    config = _valid_config()
    config["pick_place"] = []

    with pytest.raises(ConfigError, match="pick_place must be a mapping"):
        validate_arm_manager_config(config)


def test_validate_arm_manager_config_rejects_bad_state_map():
    config = _valid_config()
    config["pick_place"]["state_map"] = []

    with pytest.raises(ConfigError, match="pick_place.state_map must be a mapping"):
        validate_arm_manager_config(config)
