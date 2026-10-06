import json

import pytest

from storm2flow.config import load_config, validate_config
from storm2flow.errors import InputValidationError


def valid_config():
    return {
        "schema_version": "1.0",
        "basin": {},
        "rainfall": {"time_step_h": 1.0, "rainfall_mm": [1, 2, 3]},
        "runoff": {"initial_loss_mm": 2, "stable_loss_mm_per_h": 1},
        "unit_hydrograph": {"n": 2.5, "K_h": 1.2},
    }


def test_config_validation_accepts_non_integer_n():
    validate_config(valid_config())


def test_config_validation_rejects_negative_rainfall():
    config = valid_config()
    config["rainfall"]["rainfall_mm"] = [1, -1]
    with pytest.raises(InputValidationError):
        validate_config(config)


def test_load_config_reads_utf8_json(tmp_path):
    path = tmp_path / "parameters.json"
    path.write_text(json.dumps(valid_config(), ensure_ascii=False), encoding="utf-8")
    assert load_config(path)["schema_version"] == "1.0"
