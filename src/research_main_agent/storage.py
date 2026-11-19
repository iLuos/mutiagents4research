"""Versioned local artifacts with redaction and atomic per-file replacement."""

import json
import os
from pathlib import Path

from .config import Redactor
from .models import ResearchPlan, ResearchRequest, SessionState

REQUEST_LABELS = {
    "topic": "研究主题", "purpose": "调研目的", "time_range": "时间范围",
    "geographic_scope": "地域范围", "focus_entities": "关注主体",
    "material_types": "成果类型", "screening_criteria": "筛选条件",
    "analysis_focus": "分析重点", "report_requirements": "报告要求",
}
ROLE_LABELS = {
    "collector": "资料收集", "screener": "资料筛选",
    "organizer": "信息整理", "reporter": "总结报告",
}


def render_request(request: ResearchRequest) -> str:
    lines = []
    for key, label in REQUEST_LABELS.items():
        value = getattr(request, key)
        if isinstance(value, list):
            value = "；".join(value)
        lines.append(f"- {label}：{value or '未指定'}")
    return "\n".join(lines)


def render_plan(plan: ResearchPlan) -> str:
    status = "已确认" if plan.confirmed else "草稿，未经确认"
    lines = [f"# 科研调研计划 v{plan.version}", "", f"状态：{status}",
             "执行状态：所有子任务均未开始。", "", "## 任务理解", "", plan.understanding,
             "", "## 调研需求", "", render_request(plan.request)]
    sections = (("阶段步骤", plan.steps), ("预期交付物", plan.deliverables),
                ("资料获取限制", plan.source_limitations), ("默认建议与假设", plan.assumptions))
    for title, items in sections:
        lines.extend(["", f"## {title}", ""])
        lines.extend(f"- {item}" for item in items)
        if not items:
            lines.append("无。")
    lines.extend(["", "## 后续专业子任务", ""])
    for task in plan.subtasks:
        lines.extend([
            f"### {task.task_id} {ROLE_LABELS[task.target_role]}", "",
            f"目标：{task.objective}", f"状态：未开始",
            f"前置任务：{'、'.join(task.prerequisites) or '无'}", "",
            "输入要求：", "", *(f"- {item}" for item in task.input_requirements), "",
            "预期输出：", "", *(f"- {item}" for item in task.expected_outputs), "",
        ])
    return "\n".join(lines).rstrip() + "\n"


class SessionStore:
    def __init__(self, root: Path, state: SessionState, redactor: Redactor):
        stamp = state.created_at[:19].replace("-", "").replace(":", "").replace("T", "_")
        self.directory = root / f"{stamp}_{state.session_id}"
        self.redactor = redactor

    def _write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(self.redactor.text(content), encoding="utf-8")
        os.replace(temporary, path)

    def _json(self, path: Path, value) -> None:
        data = self.redactor.data(value)
        self._write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    def save(self, state: SessionState) -> None:
        self._json(self.directory / "conversation.json", [item.model_dump() for item in state.messages])
        self._json(self.directory / "request.json", state.request.model_dump())
        if state.plan is not None:
            self._json(self.directory / "plan.json", state.plan.model_dump())
            notice = ""
            if state.stage == "clarifying" or state.pending_message:
                notice = "> 最新需求尚未形成有效计划。以下保留上一版草稿，不能据此执行。\n\n"
            self._write(self.directory / "plan.md", notice + render_plan(state.plan))
            suffix = "confirmed" if state.plan.confirmed else "draft"
            version_path = self.directory / "plans" / f"plan_v{state.plan.version:03d}_{suffix}.json"
            # Keep the original draft when confirmation adds another snapshot.
            if not version_path.exists():
                self._json(version_path, state.plan.model_dump())
        self._json(self.directory / "session.json", state.model_dump())
