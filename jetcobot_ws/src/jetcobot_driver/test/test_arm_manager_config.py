import pytest

from jetcobot_driver.arm_manager_node import ConfigError, validate_arm_manager_config


def _valid_config():
    return {
        "joint_names": {
            "arm": [
                "joint2_to_joint1",
                "joint3_to_joint2",
                "joint4_to_joint3",
                "joint5_to_joint4",
                "joint6_to_joint5",
                "joint6output_to_joint6",
            ],
            "gripper": ["gripper_controller"],
        },
        "joint_targets": {
            "ready": {
                "group": "arm",
                "positions": [0.0, -0.4, -0.5, -0.6, 1.2, 0.0],
            },
            "gripper_open": {
                "group": "gripper",
                "positions": [0.1],
            },
        },
        "pick_and_place_sequence": [
            {"target": "ready", "state": "homing"},
            {"target": "gripper_open", "state": "picking"},
        ],
    }


def test_validate_arm_manager_config_accepts_valid_sequence():
    config = validate_arm_manager_config(_valid_config())

    assert len(config["pick_and_place_sequence"]) == 2
    assert config["joint_targets"]["ready"]["positions"][1] == pytest.approx(-0.4)
    assert config["motion"]["velocity_scaling"] == pytest.approx(0.1)


def test_validate_arm_manager_config_rejects_bad_position_count():
    config = _valid_config()
    config["joint_targets"]["ready"]["positions"] = [0.0]

    with pytest.raises(ConfigError, match="expected 6"):
        validate_arm_manager_config(config)


def test_validate_arm_manager_config_rejects_unknown_sequence_target():
    config = _valid_config()
    config["pick_and_place_sequence"].append({"target": "missing"})

    with pytest.raises(ConfigError, match="unknown target"):
        validate_arm_manager_config(config)
