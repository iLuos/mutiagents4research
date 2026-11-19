"""One graph invocation represents one user turn, committed only on success."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .llm import StructuredModel
from .models import AnalysisResult, PlanContent, ResearchPlan, SessionState
from .prompts import ANALYZE, PLAN


class TurnState(TypedDict, total=False):
    session: SessionState
    user_input: str
    analysis: AnalysisResult


def build_workflow(model: StructuredModel):
    def analyze(turn: TurnState):
        state = turn["session"]
        analysis = model.generate(AnalysisResult, ANALYZE, {
            "current_request": state.request.model_dump(),
            "previous_proposed_defaults": state.proposed_defaults,
            "previous_questions": state.questions,
            "recent_messages": [message.model_dump() for message in state.messages[-12:]],
            "latest_input": turn["user_input"],
        })
        if not analysis.request.topic:
            analysis.questions = ["你希望调研的具体研究主题或核心问题是什么？"]
            analysis.blocking_issues = ["研究主题不能为空。"]
        return {"analysis": analysis}

    def route(turn: TurnState):
        analysis = turn["analysis"]
        return "clarify" if analysis.questions or analysis.blocking_issues else "plan"

    def clarify(turn: TurnState):
        state = turn["session"].model_copy(deep=True)
        analysis = turn["analysis"]
        state.request = analysis.request
        state.questions = analysis.questions
        state.blocking_issues = analysis.blocking_issues
        state.proposed_defaults = analysis.proposed_defaults
        state.defaults_accepted = False
        state.stage = "clarifying"
        return {"session": state}

    def plan(turn: TurnState):
        state = turn["session"].model_copy(deep=True)
        analysis = turn["analysis"]
        content = model.generate(PlanContent, PLAN, {
            "request": analysis.request.model_dump(),
            "proposed_defaults": analysis.proposed_defaults,
            "previous_plan": state.plan.model_dump() if state.plan else None,
            "latest_input": turn["user_input"],
        })
        content.assumptions = list(dict.fromkeys(content.assumptions + analysis.proposed_defaults))
        state.plan = ResearchPlan(
            **content.model_dump(), request=analysis.request,
            version=state.plan.version + 1 if state.plan else 1,
        )
        state.request = analysis.request
        state.questions = []
        state.blocking_issues = []
        state.proposed_defaults = analysis.proposed_defaults
        state.defaults_accepted = False
        state.stage = "review"
        return {"session": state}

    graph = StateGraph(TurnState)
    graph.add_node("analyze", analyze)
    graph.add_node("clarify", clarify)
    graph.add_node("plan", plan)
    graph.add_edge(START, "analyze")
    graph.add_conditional_edges("analyze", route, {"clarify": "clarify", "plan": "plan"})
    graph.add_edge("clarify", END)
    graph.add_edge("plan", END)
    return graph.compile()
