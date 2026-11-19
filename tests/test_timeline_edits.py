"""Tests for time parsing and edit plan validation."""

from core.edit_plan import validate_edit_instruction
from utils.prompt_parser import EditInstruction, parse_edit_command
from utils.time_parse import parse_time_to_seconds


def test_parse_time_formats():
    assert parse_time_to_seconds("90") == 90.0
    assert parse_time_to_seconds("1:30") == 90.0
    assert parse_time_to_seconds("0:01:30") == 90.0
    assert parse_time_to_seconds("45s") == 45.0


def test_timeline_trim_validation():
    inst = EditInstruction(
        operation="timeline_trim",
        summary="trim",
        parameters={"start_sec": 5, "end_sec": 30},
    )
    result = validate_edit_instruction(inst)
    assert result.ok


def test_speed_change_validation():
    inst = EditInstruction(
        operation="speed_change",
        summary="slow",
        parameters={"speed_factor": 0.5},
    )
    assert validate_edit_instruction(inst).ok


def test_rule_parse_trim():
    inst = parse_edit_command("Trim from 0:05 to 0:30")
    assert inst.operation == "timeline_trim"
    assert inst.parameters.get("start_sec") == 5.0
    assert inst.parameters.get("end_sec") == 30.0


def test_rule_parse_crop():
    inst = parse_edit_command("Crop to 9:16 for TikTok")
    assert inst.operation == "crop_resize"
    assert inst.parameters.get("aspect_ratio") == "9:16"


def test_rule_parse_slow_mo():
    inst = parse_edit_command("Slow motion 0.5x from 3s to 6s")
    assert inst.operation in {"speed_change", "timeline_edit"}
