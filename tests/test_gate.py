import pytest

import gate
from world import OBJECTS, ZONES


def reqs_of(result):
    return {r for r, _ in result.violations}


def pp(obj, tgt):
    return {"action": "pick_place", "object": obj, "target": tgt}


# ---- REQ-SAF-001: forbidden zones -------------------------------------------------
FORBIDDEN = [z for z, v in ZONES.items() if v.get("forbidden")]


@pytest.mark.req("REQ-SAF-001")
def test_world_defines_at_least_one_forbidden_zone():
    assert FORBIDDEN


@pytest.mark.req("REQ-SAF-001")
@pytest.mark.parametrize("obj", list(OBJECTS))
@pytest.mark.parametrize("zone", FORBIDDEN)
def test_forbidden_zone_is_rejected_for_every_object(obj, zone):
    r = gate.check(pp(obj, zone))
    assert not r.allowed
    assert "REQ-SAF-001" in reqs_of(r)


@pytest.mark.req("REQ-SAF-001")
def test_forbidden_flag_is_honoured_for_any_zone():
    zones = {"z": {"center": (0.4, 0.0), "half": 0.05, "forbidden": True}}
    r = gate.check(pp("red_cube", "z"), zones=zones)
    assert not r.allowed and "REQ-SAF-001" in reqs_of(r)


# ---- REQ-SAF-002: unknown entities ------------------------------------------------
@pytest.mark.req("REQ-SAF-002")
@pytest.mark.parametrize("plan", [pp("green_cube", "zone_A"), pp("red_cube", "zone_C"),
                                  pp("green_cube", "zone_C")])
def test_unknown_object_or_zone_is_rejected(plan):
    r = gate.check(plan)
    assert not r.allowed and "REQ-SAF-002" in reqs_of(r)


# ---- REQ-SAF-003: malformed plans -------------------------------------------------
@pytest.mark.req("REQ-SAF-003")
@pytest.mark.parametrize("plan", [
    None, "pick red", [], {}, {"action": None}, {"action": "move_fast"},
    {"action": "pick_place", "object": None, "target": "zone_A"},
    {"action": "pick_place", "object": "red_cube", "target": 3},
])
def test_malformed_plan_is_rejected(plan):
    r = gate.check(plan)
    assert not r.allowed and "REQ-SAF-003" in reqs_of(r)


# ---- REQ-SAF-004: reachability ----------------------------------------------------
@pytest.mark.req("REQ-SAF-004")
def test_unreachable_zone_is_rejected():
    r = gate.check(pp("red_cube", "far_shelf"))
    assert not r.allowed and "REQ-SAF-004" in reqs_of(r)


@pytest.mark.req("REQ-SAF-004")
@pytest.mark.parametrize("pos", [(1.2, 0.0, 0.02), (0.05, 0.05, 0.02)])
def test_object_outside_reach_envelope_is_rejected(pos):
    objects = {"cube": {"pos": pos}}
    r = gate.check(pp("cube", "zone_A"), objects=objects)
    assert not r.allowed and "REQ-SAF-004" in reqs_of(r)


# ---- REQ-FUN-001 (supporting evidence): valid plans pass the gate -----------------
VALID_ZONES = [z for z, v in ZONES.items() if not v.get("forbidden") and z != "far_shelf"]


@pytest.mark.req("REQ-FUN-001")
@pytest.mark.parametrize("obj", list(OBJECTS))
@pytest.mark.parametrize("zone", VALID_ZONES)
def test_valid_plan_is_allowed(obj, zone):
    r = gate.check(pp(obj, zone))
    assert r.allowed and not r.violations


# ---- REQ-ROB-001 (supporting evidence): clarify / refuse never execute -------------
@pytest.mark.req("REQ-ROB-001")
@pytest.mark.parametrize("action", ["clarify", "refuse"])
def test_non_executable_actions_do_not_execute(action):
    r = gate.check({"action": action, "object": "red_cube", "target": "zone_A"})
    assert not r.allowed and r.action == action
