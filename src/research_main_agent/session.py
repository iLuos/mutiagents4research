"""Program-controlled confirmation and transactional model turns."""

from pathlib import Path

from .config import AgentError, Redactor
from .llm import StructuredModel
from .models import ChatMessage, SessionState, now
from .storage import SessionStore, render_plan, render_request
from .workflow import build_workflow


class AgentSession:
    def __init__(self, model: StructuredModel, output_dir: Path, redactor: Redactor | None = None):
        self.state = SessionState()
        self.redactor = redactor or Redactor()
        self.store = SessionStore(output_dir, self.state, self.redactor)
        self.graph = build_workflow(model)
        self.store.save(self.state)

    def _save_reply(self, text: str) -> str:
        text = self.redactor.text(text)
        self.state.messages.append(ChatMessage(role="assistant", content=text))
        self.state.updated_at = now()
        self.store.save(self.state)
        return text

    def show(self) -> str:
        state = self.state
        lines = ["当前调研需求：", render_request(state.request)]
        if state.last_error:
            lines.extend(["", state.last_error])
        if state.stage == "clarifying":
            lines.extend(["", "需要澄清："])
            lines.extend(f"- {issue}" for issue in state.blocking_issues)
            lines.extend(f"{index}. {question}" for index, question in enumerate(state.questions, 1))
            if not state.questions:
                lines.append("请补充或调整上述条件。")
        if state.proposed_defaults and not state.defaults_accepted:
            lines.extend(["", "默认建议（待你确认）："])
            lines.extend(f"- {item}" for item in state.proposed_defaults)
        if state.plan is not None:
            if state.stage == "clarifying" or state.pending_message:
                lines.extend(["", "以下是上一版有效草稿，最新要求尚未完成处理，暂不能确认："])
            lines.extend(["", render_plan(state.plan)])
        if state.stage == "review" and not state.pending_message:
            lines.append("可继续输入修改意见；/confirm 确认本计划及以上默认建议，/exit 保存草稿退出。")
        return self.redactor.text("\n".join(lines))

    def _attempt(self, message: str) -> str:
        self.state.pending_message = message
        self.state.last_error = None
        self.store.save(self.state)
        # The graph receives a deep copy: a failed revision cannot overwrite a valid draft.
        try:
            result = self.graph.invoke({"session": self.state.model_copy(deep=True), "user_input": message})
        except AgentError as exc:
            self.state.last_error = str(exc)
            return self._save_reply(str(exc))
        self.state = result["session"]
        self.state.pending_message = None
        self.state.last_error = None
        return self._save_reply(self.show())

    def send(self, message: str) -> str:
        message = message.strip()
        if self.state.stage in ("confirmed", "exited"):
            return "本次会话已结束，请启动新会话。"
        if not message:
            return "请输入研究主题、补充要求或命令。"
        if message == "/show":
            return self.show()
        if message == "/retry":
            if not self.state.pending_message:
                return "没有失败的请求需要重试。"
            return self._attempt(self.state.pending_message)
        if message == "/exit":
            return self.exit()
        if message == "/confirm":
            self.state.messages.append(ChatMessage(role="user", content=message))
            if (self.state.stage != "review" or self.state.plan is None
                    or self.state.pending_message or self.state.questions or self.state.blocking_issues
                    or self.state.plan.request != self.state.request):
                return self._save_reply("当前尚无可确认的有效计划。请先解决澄清问题或重试失败的修改。")
            self.state.plan.confirmed = True
            self.state.plan.confirmed_at = now()
            self.state.stage = "confirmed"
            self.state.defaults_accepted = True
            return self._save_reply(
                f"调研计划 v{self.state.plan.version} 已由你确认，默认建议已接受。"
                "所有子任务仍为未开始，本程序不会执行检索或调研。\n"
                f"结果目录：{self.store.directory}")
        if message.startswith("/"):
            return "未知命令。可用命令：/show、/confirm、/retry、/exit。"
        if self.state.pending_message:
            return self._save_reply("上一条要求尚未处理成功。请先 /retry 重试，或 /exit 保存草稿退出。")
        self.state.messages.append(ChatMessage(role="user", content=message))
        return self._attempt(message)

    def exit(self) -> str:
        if self.state.stage == "confirmed":
            return "计划已确认并保存。"
        if self.state.stage == "exited":
            return "会话已保存并退出。"
        self.state.messages.append(ChatMessage(role="user", content="/exit"))
        self.state.stage = "exited"
        return self._save_reply(f"已保存未确认草稿并退出。\n结果目录：{self.store.directory}")
