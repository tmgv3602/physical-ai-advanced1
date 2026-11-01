"""Safety gate: deterministic checks applied to an LLM plan BEFORE the robot moves.

Every violation carries the requirement ID it enforces, so the traceability
matrix can link requirement -> test -> result automatically.
Pure Python (no Genesis) so it can be unit-tested in CI.
"""
import math
from dataclasses import dataclass, field

from world import OBJECTS, ZONES, REACH_MIN, REACH_MAX

ALLOWED_ACTIONS = {"pick_place", "clarify", "refuse"}


@dataclass
class GateResult:
    allowed: bool          # True only when a pick_place plan may be executed
    action: str            # pick_place / clarify / refuse / invalid
    violations: list = field(default_factory=list)  # [(req_id, message), ...]

    def to_dict(self):
        return {"allowed": self.allowed, "action": self.action,
                "violations": [{"req": r, "msg": m} for r, m in self.violations]}


def _reach(x, y):
    r = math.hypot(x, y)
    return REACH_MIN <= r <= REACH_MAX, r


def check(plan, objects=OBJECTS, zones=ZONES) -> GateResult:
    # REQ-SAF-003: malformed plans are never executed
    if not isinstance(plan, dict) or plan.get("action") not in ALLOWED_ACTIONS:
        return GateResult(False, "invalid", [("REQ-SAF-003", f"計画の形式が不正: {plan!r}"[:200])])

    action = plan["action"]
    if action != "pick_place":
        # clarify / refuse are legitimate outcomes: nothing to execute, nothing violated
        return GateResult(False, action, [])

    obj, tgt = plan.get("object"), plan.get("target")
    if not isinstance(obj, str) or not isinstance(tgt, str):
        return GateResult(False, "invalid", [("REQ-SAF-003", "object / target が文字列でない")])

    v = []
    # REQ-SAF-002: unknown object or zone
    if obj not in objects:
        v.append(("REQ-SAF-002", f"存在しない物体: {obj}"))
    if tgt not in zones:
        v.append(("REQ-SAF-002", f"存在しない置き場: {tgt}"))
    # REQ-SAF-001: forbidden zone
    if tgt in zones and zones[tgt].get("forbidden", False):
        v.append(("REQ-SAF-001", f"立入禁止エリアへの配置: {tgt}"))
    # REQ-SAF-004: reachability of both pick and place locations
    if obj in objects:
        ok, r = _reach(*objects[obj]["pos"][:2])
        if not ok:
            v.append(("REQ-SAF-004", f"物体が可動範囲外: r={r:.2f} m"))
    if tgt in zones:
        ok, r = _reach(*zones[tgt]["center"])
        if not ok:
            v.append(("REQ-SAF-004", f"置き場が可動範囲外: r={r:.2f} m"))

    return GateResult(allowed=not v, action=action, violations=v)
