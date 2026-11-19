"""Interactive UTF-8 terminal entry point."""

import argparse
import sys
from pathlib import Path

from .config import AgentError, PROJECT_ROOT, Settings
from .llm import JsonChatModel
from .session import AgentSession


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")#处理数据格式

    parser = argparse.ArgumentParser(description="科研调研主 Agent：需求澄清与计划生成")
    parser.add_argument("--env", type=Path, default=PROJECT_ROOT / ".env", help="独立模型配置文件")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "runs", help="会话结果根目录")
    args = parser.parse_args(argv)#添加启动参数

    session = None
    try:
        settings = Settings.load(args.env.resolve())
        session = AgentSession(JsonChatModel(settings), args.output_dir.resolve(), settings.redactor)
        print("科研调研主 Agent\n请输入研究主题和调研要求。")
        print("命令：/show 查看，/confirm 确认，/retry 重试，/exit 保存草稿退出。")
        while session.state.stage not in ("confirmed", "exited"):
            try:
                message = input("\n你 > ")
            except (EOFError, KeyboardInterrupt):
                print("\n" + session.exit())
                return 0
            print("\n主 Agent > " + session.send(message))
        return 0
    except AgentError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError:
        print("无法读写配置或保存结果。请检查目录权限与剩余空间后重新运行。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
