"""World model shared by planner, gate and simulator.

Pure Python (no Genesis import) so that CI can import it without a GPU.
Units: metres, robot base at the origin, Z up.
"""

OBJECTS = {
    "red_cube": {"label": "赤い箱", "pos": (0.50, -0.15, 0.02), "color": (0.85, 0.15, 0.15)},
    "blue_cube": {"label": "青い箱", "pos": (0.50, 0.15, 0.02), "color": (0.15, 0.35, 0.85)},
}

ZONES = {
    "zone_A": {"label": "置き場A", "center": (0.30, -0.45), "half": 0.07,
               "forbidden": False, "color": (0.20, 0.70, 0.30)},
    "zone_B": {"label": "置き場B", "center": (0.30, 0.45), "half": 0.07,
               "forbidden": False, "color": (0.20, 0.70, 0.30)},
    "operator_area": {"label": "作業者エリア（立入禁止）", "center": (0.70, 0.00), "half": 0.08,
                      "forbidden": True, "color": (0.95, 0.75, 0.10)},
    "far_shelf": {"label": "奥の棚", "center": (1.05, 0.00), "half": 0.07,
                  "forbidden": False, "color": (0.60, 0.60, 0.60)},
}

# Horizontal reach envelope from the robot base. Franka's nominal reach is ~0.855 m;
# 0.80 m keeps a safety margin for a top-down grasp.
REACH_MIN = 0.25
REACH_MAX = 0.80

CUBE_SIZE = 0.04
PLATE_THICKNESS = 0.004
