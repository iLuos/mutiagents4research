"""Validated contracts for the planner and its future specialist agents."""

from datetime import datetime, timedelta, timezone
from typing import Literal, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResearchRequest(Contract):
    topic: str = ""
    purpose: str | None = None
    time_range: str | None = None
    geographic_scope: str | None = None
    focus_entities: list[str] = Field(default_factory=list)
    material_types: list[str] = Field(default_factory=list)
    screening_criteria: list[str] = Field(default_factory=list)
    analysis_focus: list[str] = Field(default_factory=list)
    report_requirements: list[str] = Field(default_factory=list)


Role = Literal["collector", "screener", "organizer", "reporter"]
ROLE_ORDER = ("collector", "screener", "organizer", "reporter")


class SubTask(Contract):
    task_id: str = Field(min_length=1)
    target_role: Role
    objective: str = Field(min_length=1)
    input_requirements: list[str] = Field(min_length=1)
    expected_outputs: list[str] = Field(min_length=1)
    prerequisites: list[str] = Field(default_factory=list)
    status: Literal["not_started"] = "not_started"

    @field_validator("input_requirements", "expected_outputs")
    @classmethod
    def nonempty_items(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("Task input and output descriptions must not be empty")
        return values


class PlanContent(Contract):
    understanding: str = Field(min_length=1)
    steps: list[str] = Field(min_length=4)
    deliverables: list[str] = Field(min_length=1)
    source_limitations: list[str] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    subtasks: list[SubTask] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def valid_task_dependencies(self) -> Self:
        if tuple(task.target_role for task in self.subtasks) != ROLE_ORDER:
            raise ValueError("Exactly four tasks are required in collector/screener/organizer/reporter order")
        seen: set[str] = set()
        previous = None
        for task in self.subtasks:
            if task.task_id in seen:
                raise ValueError("Task IDs must be unique")
            if any(dependency not in seen for dependency in task.prerequisites):
                raise ValueError("Dependencies must reference earlier task IDs")
            if previous is not None and previous not in task.prerequisites:
                raise ValueError("Each stage must depend on the preceding stage")
            seen.add(task.task_id)
            previous = task.task_id
        return self


class ResearchPlan(PlanContent):
    version: int = Field(ge=1)
    request: ResearchRequest
    created_at: str = Field(default_factory=now)
    confirmed: bool = False
    confirmed_at: str | None = None


class AnalysisResult(Contract):
    request: ResearchRequest
    questions: list[str] = Field(default_factory=list, max_length=3)
    blocking_issues: list[str] = Field(default_factory=list)
    proposed_defaults: list[str] = Field(default_factory=list)

    @field_validator("questions", "blocking_issues", "proposed_defaults")
    @classmethod
    def no_blank_entries(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("Entries must not be blank")
        return values


class ChatMessage(Contract):
    role: Literal["user", "assistant"]
    content: str
    timestamp: str = Field(default_factory=now)


class SessionState(Contract):
    session_id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)
    stage: Literal["new", "clarifying", "review", "confirmed", "exited"] = "new"
    request: ResearchRequest = Field(default_factory=ResearchRequest)
    plan: ResearchPlan | None = None
    messages: list[ChatMessage] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)
    proposed_defaults: list[str] = Field(default_factory=list)
    pending_message: str | None = None
    last_error: str | None = None
    defaults_accepted: bool = False
