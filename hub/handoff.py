"""Pure selection rules for handing an unfinished child goal to today's queue."""
from __future__ import annotations

from dataclasses import dataclass
import re


DEFAULT_APPROVAL_KEYWORDS = ("課金", "契約", "公開", "メール送信", "マージ", "デプロイ", "本番")
DONE_STATUSES = {"DONE", "COMPLETED", "COMPLETE"}
WAITING_MARKERS = ("確認待ち", "承認待ち", "[ai-agent-hub:waiting]")
CLAIM_RE = re.compile(r"\[ai-agent-hub:claim\b")
DONE_RE = re.compile(r"\[ai-agent-hub:done\b")
STOP_RE = re.compile(r"^\s*\[ai-agent-hub:stop\]\s*$", re.M)
DEPENDENCY_RE = re.compile(r"依存\s*[:：]\s*([^\s,;，；、]+)")


@dataclass
class Selection:
    next: dict | None
    skipped: list[tuple[str, str]]
    remaining: list[dict]


def _comments(goal: dict) -> list[str]:
    values = goal.get("comments") or []
    return [str(c.get("body", "")) if isinstance(c, dict) else str(c) for c in values]


def _body(goal: dict) -> str:
    return str(goal.get("body") or goal.get("detail") or "")


def _completed(goal: dict) -> bool:
    return str(goal.get("status", "")).upper() in DONE_STATUSES or bool(goal.get("completed_at"))


def _activity(goal: dict) -> str:
    for key in ("ai_activity", "ai_activity_status", "activity"):
        val = goal.get(key)
        if isinstance(val, dict):
            val = val.get("status")
        if val:
            return str(val).lower()
    return ""


def _normal_title(title: str) -> str:
    title = re.sub(r"^\s*(?:【[^】]*】\s*)+", "", title)
    return re.sub(r"\s+", "", title)


def _deps(body: str) -> set[str]:
    return {x.strip("`<>（）()。．").lower() for x in DEPENDENCY_RE.findall(body)}


def _is_in_progress(goal: dict, text: str, queue_ids: set[str]) -> bool:
    if CLAIM_RE.search(text) and not DONE_RE.search(text):
        return True
    gid = str(goal.get("id", ""))
    if f"addness-{gid}" in queue_ids:
        return True
    return _activity(goal) == "working"


def select_next(parent: dict, children: list[dict], today_ids: set[str],
                queue_ids: set[str], cfg: dict) -> Selection:
    """Select the first runnable child in display order, without performing I/O."""
    del parent  # Reserved for parent-aware rules; selection is currently child-local.
    today_ids = {str(x) for x in today_ids}
    queue_ids = {str(x) for x in queue_ids}
    unfinished_ids = {str(c.get("id", "")) for c in children if not _completed(c)}
    handoff_cfg = cfg.get("handoff") or ((cfg.get("addness") or {}).get("handoff") or {})
    keywords = handoff_cfg.get("approval_keywords")
    if keywords is None:
        keywords = DEFAULT_APPROVAL_KEYWORDS
    skipped: list[tuple[str, str]] = []
    remaining: list[dict] = []
    seen_titles: set[str] = set()
    selected = None

    already_queued_before_candidate = False
    for child in children:
        gid = str(child.get("id", ""))
        title = str(child.get("title", ""))
        body = _body(child)
        comments = _comments(child)
        text = "\n".join([body, *comments])
        complete = _completed(child)
        if not complete:
            remaining.append(child)

        reason = None
        if complete:
            reason = "completed"
        elif any(marker in text for marker in WAITING_MARKERS) or _activity(child) == "waiting":
            reason = "waiting_approval"
        elif _deps(body) & (unfinished_ids - {gid}):
            reason = "blocked_by_dependency"
        elif any(str(kw) and (str(kw) in title or str(kw) in body) for kw in keywords):
            reason = "needs_owner_approval"
        elif any(STOP_RE.search(comment) for comment in comments):
            reason = "stopped"
        elif _is_in_progress(child, text, queue_ids):
            reason = "in_progress_elsewhere"
        elif gid in today_ids:
            reason = "already_queued_next"
        else:
            normalized = _normal_title(title)
            if normalized and normalized in seen_titles:
                reason = "duplicate_title"
        normalized = _normal_title(title)
        if normalized:
            seen_titles.add(normalized)
        if reason:
            skipped.append((gid, reason))
            if reason == "already_queued_next" and selected is None:
                already_queued_before_candidate = True
            continue
        if selected is None and not already_queued_before_candidate:
            selected = child

    return Selection(next=selected, skipped=skipped, remaining=remaining)
