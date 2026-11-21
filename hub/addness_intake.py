"""Addness -> queue intake and queue -> Addness write-back.

One ``cycle`` does, in order (each step is safe to repeat):

1. **intake**   find ``【Claude Code PC】`` tasks in Addness that pass the selection rules,
                claim each one with a marker comment, and submit it to the existing git queue.
2. **run**      ``Runner.run_once()`` — the existing Claude Code -> Codex pipeline.
3. **writeback** for every claimed task whose queue entry reached done/failed, append the
                result (status, review verdict, tests, commit SHA, open issues) to the goal
                detail and post a ``[ai-agent-hub:done ...]`` comment.

Duplicate protection is layered: a local ledger, the claim/done markers on the Addness task
(visible to every PC), the earliest-claim-wins re-read after claiming, and the queue's own
"id already exists" check. A single-instance lock file prevents two cycles on one PC.

    python -m hub.addness_intake --config config/hub.config.json cycle     # one full cycle
    python -m hub.addness_intake --config config/hub.config.json loop      # forever
    python -m hub.addness_intake --config config/hub.config.json status
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import secrets
import sys
import time
from pathlib import Path

from .addness import AddnessAuthError, AddnessError, make_client
from .config import TaskRejected, load_config, validate_task
from .queue import STATES, GitQueue, now_iso
from .redact import redact

log = logging.getLogger("hub.addness")

CLAIM_RE = re.compile(r"\[ai-agent-hub:claim task=(?P<task>\S+) runner=(?P<runner>\S+) nonce=(?P<nonce>\w+)")
DONE_RE = re.compile(r"\[ai-agent-hub:done ")
# owner keeps the runner off a task by posting a comment whose line is exactly this marker
STOP_RE = re.compile(r"^\s*\[ai-agent-hub:stop\]\s*$", re.M)
TERMINAL = ("done", "failed")


def _review_verdict(report: str) -> str:
    m = re.search(r"##\s*Review verdict\s*\n+\s*\**(PASS|FAIL)", report, re.I)
    return m.group(1).upper() if m else "未判定"


def _no_owner_action(owner: str) -> bool:
    """True when the report's "Needs owner action" says there is nothing to do (e.g. "None.", "なし。...")."""
    return re.match(r"\s*(none|なし|-)(?![a-z])", owner or "", re.I) is not None


def task_id_for(goal_id: str) -> str:
    return f"addness-{goal_id}"


class Ledger:
    """Local record of every Addness goal this PC has seen/claimed/written back."""

    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def get(self, gid: str) -> dict | None:
        return self.data.get(gid)

    def set(self, gid: str, **kw) -> None:
        self.data[gid] = {**self.data.get(gid, {}), **kw, "updated_at": now_iso()}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)  # atomic: a crash never leaves a half-written ledger


class InstanceLock:
    """Exclusive lock file (works on Windows and POSIX). Stale locks expire after ``ttl``."""

    def __init__(self, path: Path, ttl: int):
        self.path, self.ttl, self.held = path, ttl, False

    def __enter__(self):
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()} {now_iso()}".encode())
                os.close(fd)
                self.held = True
                return self
            except FileExistsError:
                age = time.time() - self.path.stat().st_mtime
                if age < self.ttl:
                    return self
                self.path.unlink(missing_ok=True)  # previous process died mid-cycle
        return self

    def __exit__(self, *exc):
        if self.held:
            self.path.unlink(missing_ok=True)


class AddnessBridge:
    def __init__(self, cfg: dict, client=None, queue: GitQueue | None = None):
        self.cfg = cfg
        self.a = cfg["addness"]
        self.state = Path(cfg["state_dir"])
        (self.state / "addness").mkdir(parents=True, exist_ok=True)
        self.client = client or make_client(cfg, self.state)
        self.queue = queue or GitQueue(cfg["queue_repo_url"], cfg["queue_branch"],
                                       self.state / "addness" / "queue-repo", cfg["queue_dir"])
        self.ledger = Ledger(self.state / "addness" / "ledger.json")
        self.me = cfg["runner_id"]

    # ------------------------------------------------------------------ bookkeeping
    def history(self, event: str, **kw) -> None:
        entry = {"ts": now_iso(), "runner": self.me, "component": "addness", "event": event, **kw}
        with open(self.state / "history.jsonl", "a", encoding="utf-8") as f:
            f.write(redact(json.dumps(entry, ensure_ascii=False)) + "\n")
        log.info("%s %s", event, redact(json.dumps(kw, ensure_ascii=False))[:400])

    def set_status(self, status: str, detail: str = "") -> None:
        """Local status + (best effort) a file on the queue branch so GPT can see outages
        even when Addness itself is unreachable (e.g. expired Addness login)."""
        s = {"status": status, "detail": detail[:500], "runner": self.me, "updated_at": now_iso()}
        (self.state / "addness" / "status.json").write_text(json.dumps(s, ensure_ascii=False, indent=2),
                                                            encoding="utf-8")
        prev = self.ledger.data.get("_status", {}).get("status")
        if prev == status:
            return
        self.ledger.set("_status", status=status)
        md = (f"# Addness intake status\n\n- **status:** {status}\n- **runner:** `{self.me}`\n"
              f"- **updated:** {s['updated_at']}\n- **detail:** {redact(detail)[:500] or '-'}\n")
        if status.startswith("blocked"):
            md += ("\n**Owner action needed:** re-authenticate the Addness MCP connection in Claude Code "
                   "on the runner PC (`claude` → `/mcp` → addness → authenticate). The runner keeps "
                   "polling and resumes automatically.\n")
        try:
            self.queue.transact(lambda: (self.queue.root / "addness_intake_status.md").write_text(
                md, encoding="utf-8") or True, f"agent-hub: addness intake {status}")
        except Exception as e:  # noqa: BLE001 - status reporting must never break the cycle
            self.history("status_publish_failed", error=str(e)[:200])

    def paused(self) -> bool:
        return (self.state / "PAUSE").exists() or self.queue.paused()

    # ------------------------------------------------------------------ selection
    def eligible(self, g: dict) -> tuple[bool, str]:
        title = str(g.get("title", ""))
        if not title.startswith(self.a["title_prefix"]):
            return False, "title prefix"
        if str(g.get("status", "")).upper() in ("DONE", "COMPLETED", "COMPLETE"):
            return False, "already completed"
        if g["id"] in self.a.get("excluded_goal_ids", []):
            return False, "excluded goal id"
        path = [str(p) for p in g.get("path", [])]
        for kw in self.a.get("excluded_path_keywords", []):
            if any(kw.lower() in p.lower() for p in path):
                return False, f"excluded path keyword {kw!r}"
        parents = self.a.get("allowed_parent_titles", [])
        if parents and not any(p in path[:-1] for p in parents):
            return False, "not under an allowed parent goal"
        owners = self.a.get("allowed_owner_names") or []
        if owners and str(g.get("owner", "")) not in owners:
            return False, "task owner not allowed"
        comments = g.get("comments") or []
        if any(STOP_RE.search(c.get("body", "")) for c in comments):
            return False, "owner stop marker"
        if any(DONE_RE.search(c.get("body", "")) for c in comments):
            return False, "already written back"
        if any(CLAIM_RE.search(c.get("body", "")) for c in comments):
            return False, "already claimed"
        go = self.a.get("require_go_marker")
        if go and not any(go in c.get("body", "") for c in comments) and go not in str(g.get("body", "")):
            return False, "no owner go marker"
        return True, "ok"

    def build_task(self, g: dict) -> dict:
        body = str(g.get("body") or "")
        instr = (f"Addness task: {g['title']}\nAddness goal id: {g['id']}\n\n"
                 f"## Ideal (definition of done)\n{g.get('ideal') or '(none)'}\n\n## Task detail\n{body}")
        limit = self.cfg["security"]["max_instruction_chars"]
        if len(instr) > limit:
            instr = instr[:limit - 80] + "\n\n[truncated: read the full task in Addness]"
        return {"id": task_id_for(g["id"]), "title": g["title"][:200], "instructions": instr,
                "repo": self.a["target_repo"], "base_branch": self.a["base_branch"],
                "mode": self.a.get("mode", "implement"), "requested_by": f"addness:{g['id']}",
                "acceptance": list(self.a.get("acceptance", [])), "created_at": now_iso()}

    # ------------------------------------------------------------------ intake
    def in_queue(self, tid: str) -> str | None:
        for s in STATES:
            if (self.queue.root / s / f"{tid}.json").exists():
                return s
        return None

    def claim(self, g: dict) -> bool:
        tid = task_id_for(g["id"])
        nonce = secrets.token_hex(6)
        self.client.add_comment(g["id"], (
            f"[ai-agent-hub:claim task={tid} runner={self.me} nonce={nonce}]\n"
            f"AI Agent Hubのランナー `{self.me}` がこのタスクを受信しました（{now_iso()}）。"
            "Claude Codeが分割・Codexへ委譲・レビューし、結果をこのタスクに書き戻します。"
            "受信させたくないタスクには `[ai-agent-hub:stop]` だけを1行で書いたコメントを付けてください。"))
        # earliest claim wins: another PC may have claimed between our read and our write
        comments = self.client.get_task(g["id"]).get("comments") or []
        claims = [m for c in comments for m in [CLAIM_RE.search(c.get("body", ""))] if m]
        if not claims or claims[0].group("nonce") != nonce:
            self.history("claim_lost", goal=g["id"], winner=claims[0].group("runner") if claims else None)
            self.ledger.set(g["id"], state="lost", task_id=tid)
            return False
        self.ledger.set(g["id"], state="claimed", task_id=tid, nonce=nonce, title=g["title"])
        return True

    def intake(self) -> list[str]:
        submitted: list[str] = []
        self.queue.sync()
        for item in self.client.search_tasks(self.a["title_prefix"]):
            if len(submitted) >= int(self.a.get("max_tasks_per_cycle", 1)):
                break
            gid = item["id"]
            led = self.ledger.get(gid)
            if led and led.get("state") in ("claimed", "submitted", "written_back", "lost", "skipped"):
                if led.get("state") == "claimed":  # crashed between claim and submit: finish it
                    g = self.client.get_task(gid)
                    self._submit(g)
                    submitted.append(gid)
                continue
            if not item.get("title", "").startswith(self.a["title_prefix"]) or \
                    str(item.get("status", "")).upper() in ("DONE", "COMPLETED"):
                continue
            g = self.client.get_task(gid)
            mine = [m for c in g.get("comments") or [] for m in [CLAIM_RE.search(c.get("body", ""))]
                    if m and m.group("runner") == self.me]
            if mine and not any(DONE_RE.search(c.get("body", "")) for c in g.get("comments") or []):
                # our own claim survived a crash that happened before the ledger was saved
                self.ledger.set(gid, state="claimed", task_id=task_id_for(gid), nonce=mine[0].group("nonce"))
                if not self.in_queue(task_id_for(gid)):
                    self._submit(g)
                    submitted.append(gid)
                else:
                    self.ledger.set(gid, state="submitted")
                continue
            ok, why = self.eligible(g)
            if not ok:
                self.history("skipped", goal=gid, reason=why)
                if why in ("already claimed", "already written back", "excluded goal id") or \
                        why.startswith("excluded path"):
                    self.ledger.set(gid, state="skipped", reason=why)
                continue
            try:
                validate_task(self.build_task(g), self.cfg)
            except TaskRejected as e:
                self.history("skipped", goal=gid, reason=f"invalid task: {e}")
                self.ledger.set(gid, state="skipped", reason=f"invalid task: {e}")
                continue
            if self.in_queue(task_id_for(gid)):
                self.ledger.set(gid, state="submitted", task_id=task_id_for(gid))
                continue
            if not self.claim(g):
                continue
            self._submit(g)
            submitted.append(gid)
        return submitted

    def _submit(self, g: dict) -> None:
        t = self.build_task(g)

        def fn():
            if self.in_queue(t["id"]):
                return "exists"
            self.queue._write(self.queue.root / "inbox" / f"{t['id']}.json", t)
            self.queue.write_status_index()
            return "submitted"
        res = self.queue.transact(fn, f"task: {t['id']} (from Addness)")
        self.ledger.set(g["id"], state="submitted", task_id=t["id"], submitted_at=now_iso())
        self.history("submitted", goal=g["id"], task=t["id"], result=res)

    # ------------------------------------------------------------------ write-back
    def render_writeback(self, gid: str, state: str, result: dict, report: str,
                         auto_complete: bool = False, completion_result: str = "未実施") -> tuple[str, str]:
        verdict = _review_verdict(report)
        g = result.get("git") or {}
        tests = _section(report, "Verification") or "記録なし"
        owner = _section(report, "Needs owner action") or "none"
        codex = result.get("codex_calls") or []
        status = result.get("status", state)
        waiting = status != "done" or verdict != "PASS" or not _no_owner_action(owner)
        head = g.get("head") or "-"
        branch = g.get("work_branch") or "-"
        lines = [
            f"### {now_iso()} AI Agent Hub 実行結果（{'確認待ち' if waiting else '完了報告'}）",
            f"- キュー状態: `{status}`（試行 {result.get('attempt')}回、{result.get('duration_sec')}秒、ランナー `{self.me}`）",
            f"- レビュー判定（Claude Code）: **{verdict}**",
            f"- Addnessタスクの自動完了: {'実施対象（詳細書戻し後に実行）' if auto_complete else '対象外'}",
            f"- Codex呼び出し: {len(codex)}回 — " + (", ".join(
                f"{c.get('tool')}:{'ok' if c.get('exit_code') == 0 else c.get('error_kind')}" for c in codex) or "なし"),
            f"- 作業ブランチ: `{branch}`（push: {'済' if g.get('pushed') else '未'}）／コミットSHA: `{head}`",
        ]
        if result.get("error"):
            lines.append(f"- エラー: `{redact(str(result['error']))[:300]}`")
        for w in result.get("warnings") or []:
            lines.append(f"- 警告: {w}")
        lines += ["", "**テスト・検証**", "", _quote(tests), "", "**未解決事項／本人の操作が必要なこと**", "",
                  _quote("なし" if _no_owner_action(owner) else owner)]
        lines += ["", f"_詳細レポート: キューブランチ `{self.cfg['queue_branch']}` の "
                      f"`{self.cfg['queue_dir']}/results/{task_id_for(gid)}/report.md`。マージ・デプロイはしていません。"
                      "_"]
        comment = (f"[ai-agent-hub:done task={task_id_for(gid)} status={status} verdict={verdict} sha={head}]\n"
                   f"AI Agent Hubの処理が終わりました（{'確認待ち' if waiting else 'レビュー合格'}）。"
                   f"結果・テスト・コミットSHA・未解決事項はタスク詳細に追記しました。Addnessタスク自動完了: {completion_result}。")
        return redact("\n".join(lines)), redact(comment)

    def writeback(self) -> list[str]:
        done: list[str] = []
        self.queue.sync()
        for gid, led in list(self.ledger.data.items()):
            if gid.startswith("_") or led.get("state") != "submitted":
                continue
            tid = led["task_id"]
            state = self.in_queue(tid)
            if state not in TERMINAL:
                continue
            rdir = self.queue.root / "results" / tid
            result = json.loads((rdir / "result.json").read_text(encoding="utf-8")) if (rdir / "result.json").exists() else {}
            report = (rdir / "report.md").read_text(encoding="utf-8") if (rdir / "report.md").exists() else ""
            auto_complete = (self.a.get("complete_on_pass", False) is True and state == "done"
                             and _review_verdict(report) == "PASS")
            detail, _ = self.render_writeback(gid, state, result, report, auto_complete)
            if not led.get("detail_written"):
                self.client.append_detail(gid, detail)
                self.ledger.set(gid, detail_written=True)
            completion_result = "対象外"
            if auto_complete and not led.get("completion_attempted"):
                # Persist before the external call: completion is attempted at most once per goal.
                self.ledger.set(gid, completion_attempted=True)
                try:
                    self.client.complete_task(gid)
                    completion_result = "完了"
                    self.ledger.set(gid, completion="completed")
                    self.history("completed", goal=gid, task=tid)
                except Exception as e:  # completion must not undo a successful detail writeback
                    error = redact(str(e))[:200] or type(e).__name__
                    completion_result = "失敗（" + error + "）"
                    self.ledger.set(gid, completion="complete_failed", completion_error=error)
                    self.history("complete_failed", goal=gid, task=tid, error=error)
            elif auto_complete:
                completion_result = led.get("completion", "試行済み")
            _, comment = self.render_writeback(gid, state, result, report, auto_complete, completion_result)
            self.client.add_comment(gid, comment)
            self.ledger.set(gid, state="written_back", result=result.get("status", state),
                            head=(result.get("git") or {}).get("head"))
            self.history("written_back", goal=gid, task=tid, status=result.get("status", state))
            done.append(gid)
        return done

    # ------------------------------------------------------------------ cycle
    def cycle(self, runner=None) -> dict:
        lock = InstanceLock(self.state / "addness" / "cycle.lock", int(self.a.get("lock_ttl_sec", 7200)))
        with lock:
            if not lock.held:
                return {"status": "locked (another cycle is running)"}
            out: dict = {"status": "ok"}
            try:
                self.queue.sync()
                if self.paused():
                    self.history("paused")
                    return {"status": "paused"}
                out["intake"] = self.intake()
                if runner is not None:
                    out["run"] = runner.run_once()
                out["writeback"] = self.writeback()
                self.set_status("ok", f"intake={out['intake']} writeback={out['writeback']}")
            except AddnessAuthError as e:
                self.history("addness_auth_error", error=str(e)[:300])
                self.set_status("blocked: addness auth", str(e))
                out["status"] = "blocked: addness auth"
            except AddnessError as e:
                self.history("addness_error", error=str(e)[:300])
                self.set_status("error: addness", str(e))
                out["status"] = "error: addness"
            return out


def _section(md: str, name: str) -> str:
    m = re.search(rf"^##\s*{re.escape(name)}\s*\n(.*?)(?=^##\s|\Z)", md, re.S | re.M)
    return m.group(1).strip() if m else ""


def _quote(text: str) -> str:
    return "\n".join("> " + l for l in text.strip()[:2500].splitlines()) or "> -"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="hub.addness_intake")
    ap.add_argument("--config", default=os.environ.get("HUB_CONFIG", "config/hub.config.json"))
    ap.add_argument("command", choices=["cycle", "loop", "intake", "writeback", "status"])
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    if not cfg["addness"].get("enabled"):
        print("addness.enabled is false in config; nothing to do")
        return 0
    Path(cfg["state_dir"], "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(Path(cfg["state_dir"], "logs", "addness.log"),
                                                      encoding="utf-8")])
    bridge = AddnessBridge(cfg)
    if a.command == "status":
        p = Path(cfg["state_dir"], "addness", "status.json")
        print(p.read_text(encoding="utf-8") if p.exists() else "no status yet")
        print(json.dumps(bridge.ledger.data, ensure_ascii=False, indent=2))
        return 0
    if a.command == "intake":
        print(bridge.intake())
        return 0
    if a.command == "writeback":
        print(bridge.writeback())
        return 0
    from .runner import Runner
    runner = Runner(cfg)
    if a.command == "cycle":
        print(json.dumps(bridge.cycle(runner), ensure_ascii=False))
        return 0
    while True:
        res = bridge.cycle(runner)
        print(json.dumps(res, ensure_ascii=False), flush=True)
        if res.get("run") in (None, "idle", "paused") or str(res.get("status")) != "ok":
            time.sleep(cfg["poll_interval_sec"])


if __name__ == "__main__":
    sys.exit(main())
