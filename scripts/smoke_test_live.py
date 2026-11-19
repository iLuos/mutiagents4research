"""Explicit live API acceptance test; writes only a labeled verification session."""

import argparse
import json

from research_main_agent.config import AgentError, PROJECT_ROOT, Settings
from research_main_agent.llm import JsonChatModel
from research_main_agent.session import AgentSession


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Allow real model API calls")
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to explicitly enable API calls.")
    settings = Settings.load(PROJECT_ROOT / ".env")
    session = AgentSession(JsonChatModel(settings), PROJECT_ROOT / "runs" / "verification", settings.redactor)
    initial = (
        "这是主 Agent 的接口验收测试，仅生成计划，不执行调研。"
        "研究主题：面向科研文献调研的多 Agent 系统中的证据追溯机制。"
        "目的：比较现有方案，供研究选题。时间：2023至2026年；地域：全球；"
        "资料：中英文公开论文和开源项目；排除无可核查来源的材料。"
        "分析重点：来源追溯、逐条筛选、人工复核；输出：中文比较报告和资料清单，引用原始来源。"
        "其他可选条件采用你的默认建议，并在计划中明确列出。"
    )
    print("LIVE_STEP initial", flush=True)
    session.send(initial)
    if session.state.last_error or session.state.stage != "review":
        raise AgentError("真实接口未生成初版计划，请查看验收会话记录。")
    print("LIVE_STEP revision", flush=True)
    session.send("将时间范围缩小为2025年至2026年，成果类型只保留论文，其他要求保持不变。")
    if session.state.last_error or session.state.stage != "review" or session.state.plan.version != 2:
        raise AgentError("真实接口未生成修订计划，请查看验收会话记录。")
    session.send("/confirm")
    if not session.state.plan.confirmed:
        raise AgentError("测试确认失败。")
    summary = {
        "kind": "live_api_verification", "model": settings.model,
        "confirmed": session.state.plan.confirmed, "version": session.state.plan.version,
        "time_range": session.state.request.time_range,
        "material_types": session.state.request.material_types,
        "task_statuses": [task.status for task in session.state.plan.subtasks],
        "output_dir": str(session.store.directory),
    }
    session.store._json(session.store.directory / "verification.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
