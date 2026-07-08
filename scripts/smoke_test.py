from __future__ import annotations

import json
import urllib.request


BASE_URL = "http://127.0.0.1:8000"


def request_json(path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    health = request_json("/api/health")
    snapshot = request_json("/api/snapshot")
    manual = request_json("/api/control/manual", {"direction": "stop", "speed": 0})
    nav = request_json("/api/navigation/goal", {"point_id": "kitchen"})
    vision = request_json("/api/vision/detect", {})

    checks = {
        "health": health.get("ok") is True,
        "points": len(snapshot.get("points", [])) >= 2,
        "sensors": len(snapshot.get("sensors", [])) >= 2,
        "manual_control": manual.get("ok") is True,
        "navigation": nav.get("state") == "running",
        "vision": bool(vision.get("label")),
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise SystemExit("Smoke test failed: " + ", ".join(failed))

    print("Smoke test passed.")
    print(f"Adapter: {health.get('adapter')}")
    print(f"Navigation target: {nav.get('target', {}).get('name')}")
    print(f"Vision event: {vision.get('label_zh') or vision.get('label')}")


if __name__ == "__main__":
    main()

