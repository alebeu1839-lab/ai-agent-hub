"""File-backed sequential task runner. Configure trusted command arrays locally."""
import argparse, json, os, subprocess, tempfile
from pathlib import Path

STATES = {"pending", "implementing", "reviewing", "completed", "waiting_approval", "failed"}

def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
        tmp = f.name
    os.replace(tmp, path)

def run_queue(queue_path, commands, runner=subprocess.run):
    data = json.loads(Path(queue_path).read_text(encoding="utf-8"))
    tasks = data["tasks"]
    ids = {t["id"] for t in tasks}
    if len(ids) != len(tasks):
        raise ValueError("duplicate task id")
    for task in tasks:
        if task.get("state") in ("implementing", "reviewing"):
            # A previous process may have applied side effects before crashing.
            task["state"] = "waiting_approval"
            task["last_error"] = "Interrupted: verify effects before resuming"
    save(queue_path, data)
    for task in tasks:
        if task.get("state", "pending") != "pending":
            continue
        if task.get("requires_approval") and not task.get("approved"):
            task["state"] = "waiting_approval"
            save(queue_path, data)
            continue
        deps = task.get("depends_on", [])
        if any(dep not in ids for dep in deps):
            task["state"] = "failed"
            task["last_error"] = "Unknown dependency"
            save(queue_path, data)
            continue
        if any(next(t for t in tasks if t["id"] == dep).get("state") != "completed" for dep in deps):
            continue
        task["attempts"] = task.get("attempts", 0) + 1
        for phase in ("implement", "review"):
            cmd = commands.get(phase)
            if not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) for x in cmd):
                task["state"] = "waiting_approval"
                task["last_error"] = "Trusted " + phase + " command is not configured"
                save(queue_path, data)
                break
            task["state"] = "implementing" if phase == "implement" else "reviewing"
            save(queue_path, data)
            try:
                result = runner([*cmd, task["id"]], shell=False, text=True, capture_output=True, timeout=1800)
                error = ((result.stderr or "") + "\n" + (result.stdout or ""))[-2000:]
                failed = result.returncode != 0
            except (OSError, subprocess.TimeoutExpired) as exc:
                failed, error = True, str(exc)
            if failed:
                task["last_error"] = error
                task["state"] = ("failed" if task["attempts"] >= task.get("max_attempts", 2) else "pending")
                save(queue_path, data)
                break
        else:
            task["state"] = "completed"
            task["last_error"] = None
            save(queue_path, data)
    return data

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", required=True)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    run_queue(args.queue, json.loads(Path(args.config).read_text(encoding="utf-8")))
