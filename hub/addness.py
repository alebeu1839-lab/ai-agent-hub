"""Addness access for the runner PC.

Two interchangeable clients expose the same small surface:

* ``FakeAddnessClient`` — a local JSON file. Used for isolated end-to-end tests so no real
  Addness goal (and never My Addness) is touched.
* ``ClaudeMcpAddnessClient`` — runs ``claude -p`` with **only** the Addness MCP tools the
  operation needs. It reuses the Addness MCP login the owner already has in Claude Code
  on the PC, so no Addness token is stored in this repository or config.

Every write the runner makes is a comment carrying a machine-readable marker
(``[ai-agent-hub:...]``) or an append to the goal detail. Nothing is deleted, completed,
moved or reassigned: completing a task stays with the owner.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .billing import subscription_env
from .redact import redact

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
AUTH_MARKERS = ("unauthorized", "401", "403", "not authenticated", "authentication",
                "re-authenticate", "reauth", "login required", "token expired", "invalid_token",
                "needs authentication", "oauth")


class AddnessError(Exception):
    """Addness call failed (network, malformed answer...). Retried next cycle."""


class AddnessAuthError(AddnessError):
    """Addness login expired / missing. Only the owner can fix it; the runner reports and waits."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- fake
class FakeAddnessClient:
    """File-backed stand-in. Store layout::

        {"goals": {"<uuid>": {"id", "title", "status", "path": [titles...], "ideal", "body",
                              "comments": [{"author", "body", "created_at"}]}}}

    ``FAKE_ADDNESS_FAIL=auth|network`` simulates outages (for recovery tests).
    """

    def __init__(self, store: str | Path, author: str = "ai-agent-hub"):
        self.store = Path(store)
        self.author = author

    def _load(self) -> dict:
        return json.loads(self.store.read_text(encoding="utf-8"))

    def _save(self, data: dict) -> None:
        self.store.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _check(self):
        fail = os.environ.get("FAKE_ADDNESS_FAIL")
        if fail == "auth":
            raise AddnessAuthError("Addness MCP: 401 unauthorized (token expired)")
        if fail == "network":
            raise AddnessError("Addness MCP: connection reset")

    def search_tasks(self, prefix: str) -> list[dict]:
        self._check()
        return [{"id": g["id"], "title": g["title"], "status": g.get("status", "NONE")}
                for g in self._load()["goals"].values() if g["title"].startswith(prefix)]

    def get_task(self, goal_id: str) -> dict:
        self._check()
        g = self._load()["goals"].get(goal_id)
        if not g:
            raise AddnessError(f"goal not found: {goal_id}")
        return json.loads(json.dumps(g))

    def add_comment(self, goal_id: str, body: str) -> None:
        self._check()
        data = self._load()
        data["goals"][goal_id].setdefault("comments", []).append(
            {"author": self.author, "body": body, "created_at": _now()})
        self._save(data)

    def append_detail(self, goal_id: str, markdown: str) -> None:
        self._check()
        data = self._load()
        g = data["goals"][goal_id]
        g["body"] = (g.get("body") or "").rstrip() + "\n\n" + markdown.strip() + "\n"
        self._save(data)

    def list_children(self, goal_id: str) -> list[dict]:
        self._check()
        data = self._load()
        direct = (data.get("children") or {}).get(goal_id)
        if direct is None:
            direct = data.get("goals", {}).get(goal_id, {}).get("children")
        if direct is None:
            direct = [g for g in data.get("goals", {}).values() if g.get("parent_id") == goal_id]
        goals = data.get("goals", {})
        children = []
        for stub in direct or []:
            if not isinstance(stub, dict):
                continue
            gid = str(stub.get("id", ""))
            if not UUID_RE.match(gid):
                children.append({**stub, "invalid_id": True})
                continue
            detail = goals.get(gid)
            if detail is None:
                children.append({**stub, "deleted": True})
            else:
                children.append({**detail, **stub, "body": detail.get("body", ""),
                                 "comments": detail.get("comments", []),
                                 "ai_activity": detail.get("ai_activity", "")})
        return json.loads(json.dumps(children))

    @staticmethod
    def _today_goal_id(value) -> str:
        value = str(value.get("goal_id") or value.get("id") or value.get("task_id") or "") if isinstance(value, dict) else str(value)
        return value[len("addness-"):] if value.startswith("addness-") else value

    def list_today_ids(self) -> set[str]:
        self._check()
        data = self._load()
        return {self._today_goal_id(item) for item in data.get("today", []) if self._today_goal_id(item)}

    def add_today_todo(self, goal_id: str) -> None:
        self._check()
        if not UUID_RE.match(goal_id):
            raise AddnessError("invalid goal id")
        data = self._load()
        today = data.setdefault("today", [])
        if goal_id not in {self._today_goal_id(item) for item in today}:
            today.append(goal_id)
            self._save(data)


# --------------------------------------------------------------------------- claude + MCP
CLIENT_SYSTEM = """You are a strict data-transport helper for the AI Agent Hub runner.
Call exactly the Addness MCP tools named in the request, with exactly the given arguments.
Never call any other tool, never complete/delete/move/assign goals, never invent data.
Reply with ONLY one line: JSON wrapped as <<<JSON {...} JSON>>> . If a tool fails, reply
<<<JSON {"error": "<short reason>", "auth": true|false} JSON>>> where auth=true when the
failure is a login / authorization / expired-token problem."""


class ClaudeMcpAddnessClient:
    """Talks to Addness through Claude Code's own Addness MCP connection on this PC."""

    def __init__(self, cfg: dict, run_dir: Path):
        self.cfg = cfg
        self.acfg = cfg["addness"]
        self.server = self.acfg.get("mcp_server_name", "addness")
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def _tool(self, name: str) -> str:
        return f"mcp__{self.server}__{name}"

    def _call(self, tools: list[str], request: str) -> dict:
        claude_bin = os.environ.get("CLAUDE_BIN", self.cfg["claude"]["bin"])
        claude_bin = shutil.which(claude_bin) or claude_bin
        prefix = [sys.executable] if claude_bin.endswith(".py") else []
        settings = self.run_dir / "addness-client-settings.json"
        settings.write_text(json.dumps({"permissions": {
            "defaultMode": "default", "allow": [self._tool(t) for t in tools],
            "deny": ["Bash", "Edit", "Write", "WebFetch", "WebSearch"]}}), encoding="utf-8")
        cmd = [*prefix, claude_bin, "-p", "--output-format", "json",
               "--settings", str(settings), "--permission-mode", "default",
               "--tools", "", "--allowedTools", ",".join(self._tool(t) for t in tools),
               "--append-system-prompt", CLIENT_SYSTEM]
        if self.acfg.get("model"):
            cmd += ["--model", self.acfg["model"]]
        try:
            proc = subprocess.run(cmd, input=request, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", env=subscription_env(),
                                  timeout=int(self.acfg.get("claude_timeout_sec", 300)))
        except FileNotFoundError:
            raise AddnessError("claude CLI not found")
        except subprocess.TimeoutExpired:
            raise AddnessError("Addness call via claude timed out")
        blob = f"{proc.stdout}\n{proc.stderr}"
        try:
            outer = json.loads(proc.stdout.strip().splitlines()[-1])
            text = str(outer.get("result", ""))
        except (json.JSONDecodeError, IndexError):
            outer, text = {}, ""
        m = re.search(r"<<<JSON\s*(\{.*\})\s*JSON>>>", text, re.S)
        if proc.returncode != 0 or not m:
            low = blob.lower()
            if any(k in low for k in AUTH_MARKERS):
                raise AddnessAuthError(redact(blob.strip())[-400:])
            raise AddnessError(f"bad Addness answer (exit {proc.returncode}): {redact(blob.strip())[-400:]}")
        data = json.loads(m.group(1))
        if data.get("error"):
            if data.get("auth"):
                raise AddnessAuthError(str(data["error"])[:400])
            raise AddnessError(str(data["error"])[:400])
        return data

    def search_tasks(self, prefix: str) -> list[dict]:
        req = (f"Call {self._tool('search_goals')} with query={json.dumps(prefix, ensure_ascii=False)} "
               "and limit=50. Return {\"items\": [{\"id\": <uuid>, \"title\": <title>, "
               "\"status\": \"DONE\" if the goal is marked completed ([x]) else \"NONE\"}]}.")
        items = self._call(["search_goals"], req).get("items", [])
        return [i for i in items if isinstance(i, dict) and UUID_RE.match(str(i.get("id", "")))]

    def get_task(self, goal_id: str) -> dict:
        if not UUID_RE.match(goal_id):
            raise AddnessError("invalid goal id")
        req = (f"Call {self._tool('get_goal')} with goal_id=\"{goal_id}\" and "
               "sections=[\"body\",\"path\",\"comments\"]. Return {\"id\", \"parent_id\", \"title\", "
               "\"status\" (\"DONE\" or \"NONE\"), \"owner\": <owner display name>, \"path\": [ancestor titles from the root, ending "
               "with this goal's title], \"ideal\": <Ideal text>, \"body\": <detail body markdown>, "
               "\"comments\": [{\"author\", \"body\", \"created_at\"}]} copying text verbatim.")
        data = self._call(["get_goal"], req)
        if data.get("id") != goal_id:
            raise AddnessError("Addness answer did not match the requested goal")
        return data

    def add_comment(self, goal_id: str, body: str) -> None:
        req = (f"Call {self._tool('add_comment')} on goal_id=\"{goal_id}\" with this exact body "
               f"(verbatim, including the bracket marker):\n-----\n{body}\n-----\nReturn {{\"ok\": true}}.")
        self._call(["add_comment"], req)

    def append_detail(self, goal_id: str, markdown: str) -> None:
        req = (f"Call {self._tool('write_goal_detail')} with goal_id=\"{goal_id}\", mode=\"append\" and "
               f"this exact markdown (verbatim):\n-----\n{markdown}\n-----\nReturn {{\"ok\": true}}.")
        self._call(["write_goal_detail"], req)

    def list_children(self, goal_id: str) -> list[dict]:
        if not UUID_RE.match(goal_id):
            raise AddnessError("invalid goal id")
        req = (f"Call {self._tool('get_goal')} with goal_id=\"{goal_id}\" and sections=[\"children\"]. "
               "Return {\"children\": [{\"id\", \"title\", \"status\"}]} in display order.")
        data = self._call(["get_goal"], req)
        children = []
        for row in data.get("children", data.get("items", [])):
            if not isinstance(row, dict):
                continue
            child = dict(row)
            child_id = str(child.get("id", ""))
            if not UUID_RE.match(child_id):
                child["invalid_id"] = True
                children.append(child)
                continue
            detail_req = (f"Call {self._tool('get_goal')} with goal_id=\"{child_id}\" and "
                          "sections=[\"body\",\"comments\"]. Return {\"body\": <markdown>, "
                          "\"comments\": [{\"author\", \"body\", \"created_at\"}], "
                          "\"ai_activity\": <activity status if present>} copying text verbatim.")
            try:
                detail = self._call(["get_goal"], detail_req)
            except AddnessAuthError:
                raise
            except AddnessError as e:
                if re.search(r"not found|does not exist|deleted|削除", str(e), re.I):
                    child["deleted"] = True
                    children.append(child)
                    continue
                raise
            if detail.get("deleted"):
                child["deleted"] = True
            else:
                child.update(body=detail.get("body", ""), comments=detail.get("comments", []),
                             ai_activity=detail.get("ai_activity", ""))
            children.append(child)
        return children

    def list_today_ids(self) -> set[str]:
        req = (f"Call {self._tool('list_today_todos')} with no arguments. Return "
               "{\"items\": [{\"goal_id\": <Addness goal id>}]} for today's todos.")
        data = self._call(["list_today_todos"], req)
        return {FakeAddnessClient._today_goal_id(item) for item in data.get("items", [])
                if FakeAddnessClient._today_goal_id(item)}

    def add_today_todo(self, goal_id: str) -> None:
        if not UUID_RE.match(goal_id):
            raise AddnessError("invalid goal id")
        req = (f"Call {self._tool('create_today_todo')} with objective_id=\"{goal_id}\". "
               "Return {\"ok\": true}.")
        self._call(["create_today_todo"], req)


def make_client(cfg: dict, state_dir: Path):
    a = cfg["addness"]
    if a.get("client") == "fake":
        return FakeAddnessClient(a["fake_store"])
    if a.get("client") == "claude_mcp":
        return ClaudeMcpAddnessClient(cfg, state_dir / "addness" / "client")
    raise ValueError(f"unknown addness.client {a.get('client')!r}")
