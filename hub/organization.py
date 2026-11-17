"""Phase 7: deterministic CEO -> department delegation for sandbox scenarios.

This is a rule-based organization model, not a live autonomous GPT CEO.
No CrowdWorks submissions or outside communications occur.
"""
from dataclasses import dataclass
from .control_plane import ControlPlane

DEPARTMENTS = ("sales", "production", "qa", "admin")
SCENARIOS = {
    "website_prototype": (
        ("sales", "Check task requirements"),
        ("production", "Build mock website deliverable"),
        ("qa", "Review mock website deliverable"),
        ("admin", "Record mock completion report"),
    ),
    "research_report": (
        ("sales", "Define research requirements"),
        ("production", "Draft mock research report"),
        ("qa", "Check citations and quality"),
        ("admin", "Record mock completion report"),
    ),
}
ROLES = {"sales": "sales_manager", "production": "production_manager",
         "qa": "qa_manager", "admin": "admin_manager"}

class Organization:
    def __init__(self, store, control=None):
        self.store = store
        self.control = control or ControlPlane(store)

    def delegate(self, project_id, *, scenario, manager="ceo"):
        if not self.control.allow(manager, "plan"):
            raise PermissionError("manager cannot plan")
        if scenario not in SCENARIOS:
            raise ValueError("only approved internal demo scenarios are supported")
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id required")
        ids=[]
        for index,(department,title) in enumerate(SCENARIOS[scenario]):
            item=self.store.create(
                project_id, title, department,
                key=f"demo:{project_id}:{scenario}:{index}", actor=manager)
            task_id=item["task_id"]
            if item["state"] == "created":
                self.store.transition(task_id, "screened", actor=ROLES[department],
                                      note="internal demonstration; no external authority")
                self.store.transition(task_id, "queued", actor=ROLES[department])
            ids.append(task_id)
        for first,second in zip(ids,ids[1:]):
            self.control.depend_on(second,first)
        return [{"task_id":task_id, "department":department,
                 "manager":ROLES[department], "title":title}
                for task_id,(department,title) in zip(ids,SCENARIOS[scenario])]

    def executive_report(self, project_id):
        tasks=self.store.list_tasks(project_id)
        breakdown={}
        for t in tasks:
            dept=t["department"]
            breakdown.setdefault(dept,{"total":0,"completed":0,"blocked":0})
            breakdown[dept]["total"]+=1
            if t["state"]=="completed":breakdown[dept]["completed"]+=1
            if t["state"] in {"blocked","failed","awaiting_approval"}:
                breakdown[dept]["blocked"]+=1
        return {"project_id":project_id, "overall":self.control.dashboard(project_id),
                "departments":breakdown, "requires_owner_attention":
                any(t["state"] in {"blocked","failed","awaiting_approval"} for t in tasks)}
