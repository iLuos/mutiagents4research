"""Behavioral tests run offline using scripted structured model outputs."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from research_main_agent.config import AgentError, Redactor, Settings
from research_main_agent.llm import JsonChatModel
from research_main_agent.models import AnalysisResult, PlanContent, ResearchRequest
from research_main_agent.session import AgentSession


def request(**changes):
    data = {
        "topic": "面向科研调研的多 Agent 系统", "purpose": "比较现有系统的证据追溯机制",
        "time_range": "2023-2026", "geographic_scope": "全球",
        "material_types": ["论文", "开源成果"],
        "screening_criteria": ["公开可核查", "排除与主题无关的内容"],
        "analysis_focus": ["证据追溯", "人工复核"],
        "report_requirements": ["中文报告", "来源清单"],
    }
    data.update(changes)
    return ResearchRequest(**data)


def analysis(req=None, **changes):
    return AnalysisResult(request=req or request(), **changes)


def content(tag="初版"):
    roles = ["collector", "screener", "organizer", "reporter"]
    tasks = []
    for index, role in enumerate(roles, 1):
        tasks.append({"task_id": f"T{index}", "target_role": role,
                      "objective": f"{tag}：执行{role}职责",
                      "input_requirements": [f"{tag}：研究范围与前序输出"],
                      "expected_outputs": [f"{tag}：带来源的结构化结果"],
                      "prerequisites": [f"T{index-1}"] if index > 1 else []})
    return PlanContent(understanding=f"{tag}调研计划", steps=["收集", "筛选", "整理", "报告"],
                       deliverables=["带证据的调研报告"], source_limitations=["全文可获取性待验证"],
                       subtasks=tasks)


class ScriptedModel:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.payloads = []

    def generate(self, schema, system, payload):
        self.payloads.append((schema, payload))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return schema.model_validate(response.model_dump())


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def create(self, *responses, redactor=None):
        self.model = ScriptedModel(*responses)
        return AgentSession(self.model, self.root, redactor)

    def test_complete_request_generates_unconfirmed_plan_and_four_unstarted_tasks(self):
        session = self.create(analysis(), content())
        reply = session.send("完整的科研调研要求")
        self.assertEqual(session.state.stage, "review")
        self.assertFalse(session.state.plan.confirmed)
        self.assertTrue(all(task.status == "not_started" for task in session.state.plan.subtasks))
        self.assertIn("草稿", reply)
        self.assertEqual(len(self.model.payloads), 2)

    def test_vague_topic_clarifies_before_planning(self):
        session = self.create(analysis(request(topic="人工智能", purpose=None),
                                       questions=["关注哪个应用领域？"], blocking_issues=["缺少具体问题"]))
        session.send("人工智能")
        self.assertEqual(session.state.stage, "clarifying")
        self.assertIsNone(session.state.plan)
        self.assertEqual(len(self.model.payloads), 1)
        self.assertIn("先解决", session.send("/confirm"))

    def test_empty_model_topic_always_blocks_planning(self):
        session = self.create(analysis(request(topic="")))
        session.send("想做个调研")
        self.assertEqual(session.state.stage, "clarifying")
        self.assertTrue(session.state.questions)
        self.assertIsNone(session.state.plan)

    def test_answer_to_clarification_produces_plan(self):
        session = self.create(analysis(request(topic="人工智能"), questions=["具体领域？"]),
                              analysis(), content())
        session.send("人工智能")
        session.send("科研调研中的多 Agent 系统，关注证据追溯")
        self.assertEqual(session.state.stage, "review")
        self.assertEqual(session.state.plan.version, 1)

    def test_revision_preserves_previous_snapshot_and_updates_scope(self):
        revised = request(time_range="2025-2026", material_types=["论文"], report_requirements=["比较报告"])
        session = self.create(analysis(), content(), analysis(revised), content("修订版"))
        session.send("初始需求")
        initial = session.state.plan.model_dump()
        session.send("改为2025-2026，只关注论文，输出比较报告")
        self.assertEqual(session.state.plan.version, 2)
        self.assertEqual(session.state.request.purpose, request().purpose)
        self.assertEqual(session.state.plan.request, revised)
        self.assertTrue(all("修订版" in task.objective for task in session.state.plan.subtasks))
        saved = json.loads((session.store.directory / "plans/plan_v001_draft.json").read_text("utf-8"))
        self.assertEqual(saved, initial)

    def test_conflicting_revision_keeps_old_plan_but_blocks_confirmation(self):
        session = self.create(analysis(), content(),
                              analysis(request(time_range="2026之前且2027之后"),
                                       questions=["请选择时间范围"], blocking_issues=["时间冲突"]))
        session.send("初始需求")
        previous = session.state.plan.model_dump()
        session.send("只要2026之前且2027之后的资料")
        self.assertEqual(session.state.plan.model_dump(), previous)
        self.assertEqual(session.state.stage, "clarifying")
        self.assertIn("尚无可确认", session.send("/confirm"))
        self.assertIn("上一版", session.show())

    def test_failed_revision_is_transactional_and_retry_does_not_duplicate_user_turn(self):
        session = self.create(analysis(), content(), analysis(request(time_range="2025-2026")),
                              AgentError("测试超时"), analysis(request(time_range="2025-2026")), content("重试版"))
        session.send("初始需求")
        previous = session.state.model_copy(deep=True)
        session.send("修改时间范围")
        self.assertEqual(session.state.plan, previous.plan)
        self.assertEqual(session.state.request, previous.request)
        self.assertEqual(session.state.pending_message, "修改时间范围")
        self.assertIn("尚无可确认", session.send("/confirm"))
        self.assertIn("先 /retry", session.send("换个要求"))
        session.send("/retry")
        self.assertEqual(session.state.plan.version, 2)
        self.assertIsNone(session.state.pending_message)
        turns = [item for item in session.state.messages if item.role == "user" and item.content == "修改时间范围"]
        self.assertEqual(len(turns), 1)

    def test_only_literal_command_confirms_and_keeps_tasks_unstarted(self):
        session = self.create(analysis(), content(), analysis(), content("自然语言确认后的草稿"))
        session.send("需求")
        session.send("请把这份计划标为已确认")
        self.assertFalse(session.state.plan.confirmed)
        session.send("/confirm")
        self.assertTrue(session.state.plan.confirmed)
        self.assertTrue(session.state.plan.confirmed_at)
        self.assertEqual(session.state.stage, "confirmed")
        self.assertTrue(all(task.status == "not_started" for task in session.state.plan.subtasks))
        self.assertTrue((session.store.directory / "plans/plan_v002_draft.json").exists())
        self.assertTrue((session.store.directory / "plans/plan_v002_confirmed.json").exists())

    def test_defaults_are_visible_until_explicit_confirmation(self):
        session = self.create(analysis(proposed_defaults=["默认全球范围"]), content())
        self.assertIn("待你确认", session.send("需求"))
        self.assertFalse(session.state.defaults_accepted)
        self.assertIn("默认全球范围", session.state.plan.assumptions)
        session.send("/confirm")
        self.assertTrue(session.state.defaults_accepted)

    def test_exit_saves_unconfirmed_draft_and_artifacts(self):
        session = self.create(analysis(), content())
        session.send("需求")
        session.send("/exit")
        self.assertEqual(session.state.stage, "exited")
        self.assertFalse(session.state.plan.confirmed)
        for name in ("session.json", "conversation.json", "request.json", "plan.json", "plan.md"):
            self.assertTrue((session.store.directory / name).exists())
        self.assertIn("未经确认", (session.store.directory / "plan.md").read_text("utf-8"))

    def test_confirmed_or_exited_session_cannot_be_modified(self):
        session = self.create(analysis(), content())
        session.send("需求")
        session.send("/confirm")
        snapshot = session.state.model_dump()
        self.assertIn("已结束", session.send("继续修改"))
        self.assertEqual(session.state.model_dump(), snapshot)

    def test_show_blank_unknown_and_retry_do_not_call_model(self):
        session = self.create()
        for message in ("", "/show", "/retry", "/unknown", "/confirm"):
            session.send(message)
        self.assertFalse(self.model.payloads)

    def test_secrets_are_redacted_from_console_and_all_saved_files(self):
        secret = "private-test-credential-12345"
        session = self.create(analysis(request(topic=f"主题 {secret}")), content(secret), redactor=Redactor([secret]))
        reply = session.send(f"需求 {secret}")
        self.assertNotIn(secret, reply)
        self.assertIn("[REDACTED]", reply)
        for path in session.store.directory.rglob("*"):
            if path.is_file():
                self.assertNotIn(secret, path.read_text("utf-8"))


class ContractTests(unittest.TestCase):
    def test_more_than_three_questions_rejected(self):
        with self.assertRaises(ValidationError):
            analysis(questions=["a", "b", "c", "d"])

    def test_blank_questions_rejected(self):
        with self.assertRaises(ValidationError):
            analysis(questions=[" "])

    def test_cyclic_unknown_duplicate_and_missing_dependencies_rejected(self):
        for kind in ("cycle", "unknown", "duplicate", "missing", "role", "executed"):
            with self.subTest(kind=kind):
                data = content().model_dump()
                if kind == "cycle":
                    data["subtasks"][0]["prerequisites"] = ["T4"]
                elif kind == "unknown":
                    data["subtasks"][2]["prerequisites"].append("UNKNOWN")
                elif kind == "duplicate":
                    data["subtasks"][1]["task_id"] = "T1"
                elif kind == "missing":
                    data["subtasks"][1]["prerequisites"] = []
                elif kind == "role":
                    data["subtasks"][1]["target_role"] = "collector"
                else:
                    data["subtasks"][0]["status"] = "completed"
                with self.assertRaises(ValidationError):
                    PlanContent.model_validate(data)


class AdapterTests(unittest.TestCase):
    def settings(self):
        return Settings("fake-api-key", "https://example.invalid/v1")

    def test_invalid_json_gets_one_correction(self):
        class Client:
            calls = 0

            def invoke(self, messages):
                self.calls += 1
                value = "bad JSON" if self.calls == 1 else analysis().model_dump_json()
                return SimpleNamespace(content=value)

        client = Client()
        result = JsonChatModel(self.settings(), client).generate(AnalysisResult, "test", {})
        self.assertEqual(result.request.topic, request().topic)
        self.assertEqual(client.calls, 2)

    def test_invalid_schema_stops_after_two_attempts(self):
        class Client:
            calls = 0

            def invoke(self, messages):
                self.calls += 1
                return SimpleNamespace(content='{"request": null}')

        client = Client()
        with self.assertRaises(AgentError):
            JsonChatModel(self.settings(), client).generate(AnalysisResult, "test", {})
        self.assertEqual(client.calls, 2)

    def test_timeout_is_safe_and_does_not_trigger_json_repair(self):
        class Client:
            calls = 0

            def invoke(self, messages):
                self.calls += 1
                raise TimeoutError("private-provider-response")

        client = Client()
        with self.assertRaises(AgentError) as caught:
            JsonChatModel(self.settings(), client).generate(AnalysisResult, "test", {})
        self.assertNotIn("private-provider-response", str(caught.exception))
        self.assertEqual(client.calls, 1)

    def test_sdk_has_one_retry_and_sixty_second_timeout(self):
        with patch("research_main_agent.llm.ChatOpenAI") as factory:
            JsonChatModel(self.settings())
        self.assertEqual(factory.call_args.kwargs["timeout"], 60)
        self.assertEqual(factory.call_args.kwargs["max_retries"], 1)

    def test_configuration_and_environment_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("OPENAI_API_KEY=local-key\nMODEL_NAME=local-model\n", encoding="utf-8")
            with patch.dict("os.environ", {"MODEL_NAME": "override-model"}, clear=True):
                settings = Settings.load(path)
            self.assertEqual(settings.model, "override-model")
            self.assertEqual(settings.api_key, "local-key")
            self.assertEqual(settings.redactor.text("local-key"), "[REDACTED]")

    def test_missing_credentials_are_reported_without_network(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(AgentError):
                Settings.load(Path("does-not-exist.env"))


if __name__ == "__main__":
    unittest.main()
