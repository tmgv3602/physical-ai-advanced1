import pytest

import gate
import planner
from world import OBJECTS, ZONES


@pytest.mark.req("REQ-SAF-003")
@pytest.mark.parametrize("text", ["", "了解しました", "{broken json", '["pick_place"]'])
def test_unparseable_llm_output_is_blocked_by_gate(text):
    plan = planner.parse_plan(text)
    assert not gate.check(plan).allowed


@pytest.mark.req("REQ-FUN-001")
def test_parse_plan_extracts_json_surrounded_by_prose():
    plan = planner.parse_plan('はい。{"action":"pick_place","object":"red_cube","target":"zone_A"} です')
    assert plan["object"] == "red_cube" and plan["target"] == "zone_A"


@pytest.mark.req("REQ-FUN-001")
def test_system_prompt_lists_every_object_and_zone():
    prompt = planner.build_system_prompt(safe=True)
    for name in list(OBJECTS) + list(ZONES):
        assert name in prompt


@pytest.mark.req("REQ-ROB-001", "REQ-SAF-001")
def test_safe_prompt_contains_safety_rules_and_unsafe_does_not():
    assert "clarify" in planner.build_system_prompt(True).split("ルール")[-1]
    assert "ルール" not in planner.build_system_prompt(False)


@pytest.mark.req("REQ-ROB-001")
@pytest.mark.parametrize("text", ["箱を片付けて", "赤い箱をどこかに置いて", "置き場Aに置いて"])
def test_rule_planner_asks_for_clarification(text):
    plan, _ = planner.RulePlanner().plan(text)
    assert plan["action"] == "clarify"


@pytest.mark.req("REQ-SAF-001")
def test_rule_planner_refuses_forbidden_zone():
    plan, _ = planner.RulePlanner().plan("青い箱を作業者エリアに置いて")
    assert plan["action"] == "refuse"
