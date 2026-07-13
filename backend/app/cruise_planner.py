from __future__ import annotations

from heapq import heappop, heappush
from itertools import count
from typing import Any


class CruisePlanningError(ValueError):
    """Raised when a cruise route cannot be planned from the supplied points."""


HEADINGS = ("north", "east", "south", "west")
HEADING_LABELS = {
    "north": "北",
    "east": "东",
    "south": "南",
    "west": "西",
}
MOVES = {
    0: (0, -1),
    1: (1, 0),
    2: (0, 1),
    3: (-1, 0),
}


def _clamp_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _clamp_float(value: Any, minimum: float, maximum: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _heading_index(value: Any) -> int:
    if isinstance(value, str):
        value = value.strip().lower()
        if value in HEADINGS:
            return HEADINGS.index(value)
        aliases = {
            "n": 0,
            "up": 0,
            "e": 1,
            "right": 1,
            "s": 2,
            "down": 2,
            "w": 3,
            "left": 3,
        }
        if value in aliases:
            return aliases[value]
    return _clamp_int(value, 0, 3, 0) % 4


def _heading_name(index: int) -> str:
    return HEADINGS[index % 4]


def _normal_waypoints(raw: Any, width: int, height: int) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise CruisePlanningError("waypoints must be a list")
    points: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise CruisePlanningError("each waypoint must be an object")
        x = _clamp_int(item.get("x"), 0, width - 1, 0)
        y = _clamp_int(item.get("y"), 0, height - 1, 0)
        cell = (x, y)
        if cell in seen:
            raise CruisePlanningError("two waypoints are on the same cell")
        seen.add(cell)
        point_id = str(item.get("id") or f"wp-{index + 1}")[:40]
        name = str(item.get("name") or f"途经点 {index + 1}")[:40]
        points.append(
            {
                "id": point_id,
                "name": name,
                "x": x,
                "y": y,
                "order": index + 1,
                "color": item.get("color") or "",
            }
        )
    if len(points) < 3:
        raise CruisePlanningError("定点巡航至少需要 3 个途经点")
    return points


def _normal_obstacles(raw: Any, width: int, height: int, waypoints: list[dict[str, Any]]) -> set[tuple[int, int]]:
    waypoint_cells = {(point["x"], point["y"]) for point in waypoints}
    obstacles: set[tuple[int, int]] = set()
    if not isinstance(raw, list):
        return obstacles
    for item in raw:
        if not isinstance(item, dict):
            continue
        x = _clamp_int(item.get("x"), 0, width - 1, -1)
        y = _clamp_int(item.get("y"), 0, height - 1, -1)
        if x < 0 or y < 0:
            continue
        cell = (x, y)
        if cell not in waypoint_cells:
            obstacles.add(cell)
    return obstacles


def _heuristic(cell: tuple[int, int], goal: tuple[int, int]) -> float:
    return float(abs(cell[0] - goal[0]) + abs(cell[1] - goal[1]))


def _reconstruct(
    parents: dict[tuple[int, int, int], tuple[int, int, int] | None],
    current: tuple[int, int, int],
) -> list[tuple[int, int, int]]:
    path = [current]
    while parents[current] is not None:
        current = parents[current]  # type: ignore[assignment]
        path.append(current)
    path.reverse()
    return path


def _astar_segment(
    width: int,
    height: int,
    obstacles: set[tuple[int, int]],
    start: tuple[int, int],
    goal: tuple[int, int],
    start_heading: int,
    turn_penalty: float,
) -> tuple[list[dict[str, Any]], int, int]:
    if start == goal:
        return [{"x": start[0], "y": start[1], "heading": _heading_name(start_heading)}], start_heading, 0

    queue: list[tuple[float, int, float, int, tuple[int, int, int]]] = []
    serial = count()
    start_state = (start[0], start[1], start_heading)
    heappush(queue, (_heuristic(start, goal), 0, 0.0, next(serial), start_state))
    costs: dict[tuple[int, int, int], float] = {start_state: 0.0}
    turns: dict[tuple[int, int, int], int] = {start_state: 0}
    parents: dict[tuple[int, int, int], tuple[int, int, int] | None] = {start_state: None}
    best_goal: tuple[int, int, int] | None = None

    while queue:
        _, _, cost, _, current = heappop(queue)
        x, y, heading = current
        if cost > costs[current]:
            continue
        if (x, y) == goal:
            best_goal = current
            break
        for next_heading, (dx, dy) in MOVES.items():
            nx, ny = x + dx, y + dy
            if nx < 0 or ny < 0 or nx >= width or ny >= height:
                continue
            if (nx, ny) in obstacles:
                continue
            turn_count = 0 if next_heading == heading else 1
            next_cost = cost + 1.0 + (turn_penalty if turn_count else 0.0)
            next_state = (nx, ny, next_heading)
            if next_cost >= costs.get(next_state, float("inf")):
                continue
            costs[next_state] = next_cost
            turns[next_state] = turns[current] + turn_count
            parents[next_state] = current
            priority = next_cost + _heuristic((nx, ny), goal)
            heappush(queue, (priority, turns[next_state], next_cost, next(serial), next_state))

    if best_goal is None:
        raise CruisePlanningError(f"无法规划从 {start} 到 {goal} 的路径")

    state_path = _reconstruct(parents, best_goal)
    cells = [{"x": x, "y": y, "heading": _heading_name(heading)} for x, y, heading in state_path]
    return cells, best_goal[2], turns[best_goal]


def _turn_commands(current_heading: int, target_heading: int) -> list[str]:
    delta = (target_heading - current_heading) % 4
    if delta == 0:
        return []
    if delta == 1:
        return ["right"]
    if delta == 2:
        return ["right", "right"]
    return ["left"]


def _commands_for_path(path: list[dict[str, Any]], start_heading: int) -> tuple[list[dict[str, Any]], int]:
    commands: list[dict[str, Any]] = []
    heading = start_heading
    for previous, current in zip(path, path[1:]):
        dx = int(current["x"]) - int(previous["x"])
        dy = int(current["y"]) - int(previous["y"])
        target_heading = None
        for index, move in MOVES.items():
            if move == (dx, dy):
                target_heading = index
                break
        if target_heading is None:
            raise CruisePlanningError("planned path contains a non-adjacent step")
        for direction in _turn_commands(heading, target_heading):
            commands.append({"type": "move", "direction": direction})
        commands.append({"type": "move", "direction": "forward"})
        heading = target_heading
    return commands, heading


def plan_cruise_route(payload: dict[str, Any] | None) -> dict[str, Any]:
    body = payload or {}
    grid = body.get("grid") if isinstance(body.get("grid"), dict) else {}
    width = _clamp_int(grid.get("width"), 6, 160, 48)
    height = _clamp_int(grid.get("height"), 6, 160, 32)
    turn_penalty = _clamp_float(body.get("turn_penalty"), 0.0, 3.0, 0.35)
    start_heading = _heading_index(body.get("start_heading", "north"))
    waypoints = _normal_waypoints(body.get("waypoints"), width, height)
    obstacles = _normal_obstacles(body.get("obstacles"), width, height, waypoints)
    route_mode = str(body.get("route_mode") or "out_and_back")

    segments: list[dict[str, Any]] = []
    route_cells: list[dict[str, Any]] = []
    movement_commands: list[dict[str, Any]] = []
    heading = start_heading

    def append_segment(start_point: dict[str, Any], end_point: dict[str, Any]) -> None:
        nonlocal heading
        start = (start_point["x"], start_point["y"])
        goal = (end_point["x"], end_point["y"])
        path, end_heading, segment_turns = _astar_segment(width, height, obstacles, start, goal, heading, turn_penalty)
        commands, heading = _commands_for_path(path, heading)
        movement_commands.extend(commands)
        movement_commands.append(
            {
                "type": "arrive",
                "waypoint_id": end_point["id"],
                "waypoint_name": end_point["name"],
            }
        )
        segment = {
            "from": start_point,
            "to": end_point,
            "path": path,
            "commands": commands,
            "distance_cells": max(0, len(path) - 1),
            "turns": segment_turns,
            "end_heading": _heading_name(end_heading),
        }
        segments.append(segment)
        if route_cells:
            route_cells.extend(path[1:])
        else:
            route_cells.extend(path)

    if route_mode == "closed_loop":
        for index, start_point in enumerate(waypoints):
            append_segment(start_point, waypoints[(index + 1) % len(waypoints)])
    else:
        for index in range(len(waypoints) - 1):
            append_segment(waypoints[index], waypoints[index + 1])
        movement_commands.append({"type": "turnaround", "direction": "left", "reason": "last_waypoint"})
        heading = (heading + 2) % 4
        for index in range(len(waypoints) - 1, 0, -1):
            append_segment(waypoints[index], waypoints[index - 1])
        movement_commands.append({"type": "turnaround", "direction": "left", "reason": "ready_for_next_round"})
        heading = (heading + 2) % 4

    return {
        "ok": True,
        "grid": {"width": width, "height": height},
        "waypoints": waypoints,
        "obstacles": [{"x": x, "y": y} for x, y in sorted(obstacles)],
        "start_heading": _heading_name(start_heading),
        "route_mode": route_mode,
        "turn_penalty": turn_penalty,
        "segments": segments,
        "route": route_cells,
        "commands": movement_commands,
        "totals": {
            "segments": len(segments),
            "distance_cells": sum(segment["distance_cells"] for segment in segments),
            "turns": sum(segment["turns"] for segment in segments),
            "move_commands": sum(1 for command in movement_commands if command["type"] == "move"),
            "arrivals": sum(1 for command in movement_commands if command["type"] == "arrive"),
            "turnarounds": sum(1 for command in movement_commands if command["type"] == "turnaround"),
        },
        "notes": [
            "执行巡航前请先把小车手动移动回第一个途经点。",
            "默认巡航方式为 A-B-C 后原地掉头，再按 C-B-A 返回；循环时重复这条往返路线。",
            "turn_penalty 越大，规划越倾向于少拐弯。",
        ],
    }
