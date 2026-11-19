# 科研调研主 Agent

独立的命令行科研调研规划程序：理解研究主题、澄清必要条件、生成四类专业子任务，接受修改后由用户显式确认。

当前只生成计划，所有子任务均为未开始。程序不检索资料、不调用子 Agent，也不撰写调研报告。

## 环境与安装

使用已经部署的 Conda 环境，无需创建新环境。PowerShell 中运行：

```powershell
Set-Location D:\download\mutiagents4research
& D:\download\anaconda3\envs\gpt-researcher\python.exe -m pip install -e . --no-deps --no-build-isolation
```

项目采用 `src` 布局；完成可编辑安装后，修改源码直接生效。运行时不导入 GPT Researcher 的业务代码。

## 模型配置

使用项目自己的 `.env`，字段参考 `.env.example`：

- `OPENAI_API_KEY`：模型服务凭据。
- `OPENAI_BASE_URL`：已经验证可用的 OpenAI 兼容接口地址。
- `MODEL_NAME`：模型名，默认 `glm-4.7-flash`，不带 `openai:` 前缀。
- `REQUEST_TIMEOUT`：单次模型请求超时秒数，默认 60。
- `LLM_EXTRA_BODY`：可选 JSON 对象。GLM 默认关闭 thinking，以减少响应耗时。

环境变量优先于 `.env`。显式配置其他模型时，应根据服务兼容性调整 `LLM_EXTRA_BODY`。

首次导入现有本地配置可使用以下命令。脚本只读取模型配置，创建独立 `.env`；不会显示密钥或覆盖已有配置。

```powershell
& D:\download\anaconda3\envs\gpt-researcher\python.exe scripts\bootstrap_config.py --from-env 'C:\Users\Nhx\Documents\Codex\2026-10-19\zhe\outputs\gpt-researcher\.env'
```

`.env` 和 `runs/` 已列入 `.gitignore`。对话、计划和会话文件会遮盖已加载的凭据；不要在调研需求中输入其他敏感信息。

## 启动与对话

双击 `RUN_MAIN_AGENT.cmd`，或运行：

```powershell
& D:\download\anaconda3\envs\gpt-researcher\python.exe -m research_main_agent
```

示例输入：

> 调研2023至2026年面向科研文献调研的多 Agent 系统，比较证据追溯与人工复核机制。覆盖全球中英文公开论文和开源项目，排除无可核查来源的材料，最终要求中文比较报告和资料清单。

主 Agent 每轮最多提出三个必要问题。需求完整时生成草稿，未指定的可选条件作为默认建议披露。

- 直接输入自然语言补充或修改要求。
- `/show`：查看当前需求、待处理问题与计划。
- `/confirm`：确认当前计划及已披露的默认建议，保存确认版并结束本次会话。自然语言中的“确认”不会替代该命令。
- `/retry`：重试上一条失败的模型请求。
- `/exit`：保存未确认草稿并退出；Ctrl+C 或输入流结束也会保存草稿。

若一次修改失败，原需求与有效草稿保持不变，失败要求单独保留；必须先重试或退出，以免把旧计划误认为新要求的结果。存在必要澄清或失败请求时，程序拒绝确认。

模型网络调用最多重试一次；JSON 或数据校验失败时最多纠正一次。每次重试调用本身也受网络重试限制。模型响应速度和调研规划质量取决于服务与模型。

可用 `--env 路径` 指定配置文件，`--output-dir 路径` 指定会话结果根目录。默认路径相对于项目目录，不受启动时当前目录影响。

## 输出

每次启动在 `runs/` 下创建独立会话目录，持续保存：

- `conversation.json`：用户与主 Agent 的对话。
- `request.json`：当前有效的结构化调研需求。
- `session.json`：完整会话状态、阻塞问题、失败请求与默认建议接受状态。
- `plan.json`、`plan.md`：最新有效计划的机器可读版与可读版，有计划后才生成。
- `plans/plan_v001_draft.json` 等：各版草稿快照。
- `plans/plan_v001_confirmed.json` 等：用户显式确认的版本，保留原草稿。

若需求已发生变更但尚未形成有效新计划，`plan.md` 会说明当前保留的是旧草稿。只有 `session.stage=confirmed` 且 `plan.confirmed=true` 的结果才是确认版。

计划中的 `request` 固定记录该版本的范围。每个 `subtasks` 项含编号、目标角色、目标、输入要求、预期输出、前置任务和 `not_started` 状态。角色依次为 `collector`、`screener`、`organizer`、`reporter`。后续执行系统可以读取已确认的计划，但当前程序不会自动启动任务。

第一版不支持退出后的会话恢复；重新启动会建立新会话。JSON 与 Markdown 文件是本地记录，不具备数据库级多文件事务保证。

## 测试

离线行为测试不调用 API：

```powershell
& D:\download\anaconda3\envs\gpt-researcher\python.exe -m unittest discover -s tests -v
```

显式调用真实模型的验收测试会产生少量 API 费用，结果保存在 `runs/verification/`，是测试会话，不是实际科研任务：

```powershell
& D:\download\anaconda3\envs\gpt-researcher\python.exe scripts\smoke_test_live.py --live
```

## 代码结构

`src/research_main_agent` 中，`models.py` 定义数据契约，`workflow.py` 管理 LangGraph 流程，`prompts.py` 定义职责，`llm.py` 适配模型，`session.py` 控制修改与确认，`storage.py` 保存结果，`cli.py` 接收命令行输入。

下一阶段可让资料收集 Agent 读取 `collector` 子任务；当前阶段的重点是先检验计划是否准确表达用户的调研意图。
