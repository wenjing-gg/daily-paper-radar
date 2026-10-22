# 进阶配置与运行说明

日常使用只需阅读 [快速开始](quickstart.md)。`focus_description` 和 `paper_preferences` 都可留空；`keywords` 既用于可选的字面初筛，也会传入 LLM 判断主题。没有任何关注条件时，默认 HF 来源按通用阅读价值生成简报。本页用于修改来源规则、切换模型后端、多群推送及排查定时任务。

## 联动 Hugging Face Daily Papers

Hugging Face 官方支持按日期获取 Daily Papers；本项目读取公开接口，不需要登录或额外 Token。参见 [Hugging Face 官方 API 文档](https://huggingface.co/docs/huggingface_hub/main/en/package_reference/hf_api#huggingface_hub.HfApi.list_daily_papers)。

```json
{
  "sources": {
    "arxiv": { "enabled": true },
    "huggingface": {
      "enabled": true,
      "lookback_days": 3,
      "min_upvotes": 5,
      "max_papers": 20,
      "keyword_filter": false,
      "request_timeout_s": 30
    }
  }
}
```

- 仅精选：关闭 `arxiv.enabled`，保留 Hugging Face。公开模板默认采用此方式，`min_upvotes` 默认 0，避免新论文票数尚少就被过滤。
- 仅 arXiv：关闭 `huggingface.enabled`，配置分类和关键词。
- 双来源：同时开启，按 arXiv ID 合并去重，保留来源、票数和讨论链接。
- `lookback_days`：按 UTC 日期回看最近 1–14 天，应对时差与投票积累。周末可适当增加。
- `min_upvotes`、`max_papers`：先按票数门槛筛选，再在回看窗口内取票数最高的 N 篇，最后排除已投递论文；这些是候选数量控制，不是质量评分。
- `keyword_filter: false`：HF 精选不受机械关键词限制，交给 LLM 判断相关性；设为 `true` 则先按与 arXiv 相同的关键词规则筛选。

最终日报先按 LLM 相关性、阅读建议排序，再以票数打破同级并列。`render.max_detailed` 默认展开 10 篇，其余保留链接。模型会分析所有本批次候选，不只分析展示出的前 10 篇。

## .env 与凭据

根目录提供 [.env.example](../.env.example)。复制成 `.env`，只填写实际使用的变量；模型地址、密钥、名称统一放在 `.env`，关键词和群组配置放在 `config/profile.json`。

加载规则：**已有进程环境变量优先于项目根目录 `.env`**。所有 Python 入口自动加载 `.env`，不依赖当前工作目录，因此 Windows 定时任务和 macOS LaunchAgent 都能使用。支持单行值、单/双引号、注释与可选 `export` 前缀；不执行命令，也不展开 `$变量` 或 `$(命令)`。复杂值有 `#` 或空格时使用引号，不支持多行值。

`.env` 已被 Git 忽略，模板仅有空值。不要把实际 `.env`、截图或日志中的凭据发到公开 Issue；仅允许运行账户读取该文件。如果原先有 `config/.env.local`，请手工迁移到根目录 `.env`，不再用 shell `source` 加载。

## 自定义模型

配置位置：`config/profile.json` 的 `llm_enrich`。后台选择示例：

```json
{
  "llm_enrich": {
    "backend": "codex",
    "codex": {
      "cli_path": "codex",
      "model": "",
      "batch_size": 10,
      "timeout_s": 600
    }
  }
}
```

`model` 为空时使用 CLI 自身配置；填写模型名时通过 `--model` 传给 CLI。改为 `backend: "claude_code"` 时使用同名 `claude_code` 配置块，将 `cli_path` 改为 `claude`。定时环境建议填写 CLI 的绝对路径，并提前在**运行任务的同一个操作系统账户**下安装、登录、实际调用一次。Windows 支持原生可执行文件，以及标准 npm 安装的 `codex.cmd` / `claude.cmd`；自定义批处理包装器需要改为原生入口。

API 方式统一使用根目录 `.env` 中的三个变量：

| 变量 | 含义 |
| --- | --- |
| `LLM_BASE_URL` | API 根地址、API 前缀或完整接口地址 |
| `LLM_API_KEY` | 对应服务的 API 密钥 |
| `LLM_MODEL_NAME` | 该服务支持的模型名称，按供应商实际名称填写 |

不区分供应商专用变量。切换 OpenAI、Anthropic 或兼容网关时，修改这三个值即可；凭据不写进 JSON。

`profile.json` 中只保留运行参数：

```json
{
  "llm_enrich": {
    "backend": "api",
    "api": {
      "protocol": "auto",
      "max_papers": 100,
      "request_timeout_s": 60,
      "concurrency": 4,
      "max_tokens": 4096
    }
  }
}
```

地址与协议规则：

| `LLM_BASE_URL` 的地址形式 | 默认使用的协议 / 接口 |
| --- | --- |
| `https://api.openai.com` 或 `https://api.openai.com/v1` | OpenAI `/v1/chat/completions` |
| `https://api.anthropic.com` 或 `https://api.anthropic.com/v1` | Anthropic `/v1/messages` |
| 完整地址以 `/chat/completions` 结尾 | OpenAI 兼容协议，保持原地址 |
| 完整地址以 `/messages` 结尾 | Anthropic 协议，保持原地址 |
| 其他网关根地址或 API 前缀 | 默认 OpenAI 兼容协议 |

**无法仅凭任意自建域名判断协议。** Anthropic 兼容网关可直接把完整 `/messages` 地址填入 `LLM_BASE_URL`，或者在 JSON 中将 `api.protocol` 改为 `anthropic`；使用 OpenAI 协议转发 Claude 模型的网关仍选择 `openai`。不根据模型名称猜协议，也不将鉴权失败自动切换到另一协议重试。

根地址自动补 `/v1`；已有路径视作 API 前缀，例如 `/compatible-mode/v1`、`/api/v4` 会原样保留再追加接口名。地址不能包含凭据、查询参数或片段。

Anthropic 请求会使用原生鉴权和 Messages 请求格式，解析文本内容块；OpenAI 使用 Chat Completions。实现参考 [Anthropic 官方 Messages 文档](https://platform.claude.com/docs/en/api/messages/create) 和 [OpenAI 官方 Chat 文档](https://developers.openai.com/api/reference/resources/chat)。不包含 AWS Bedrock、Azure 专有鉴权或仅提供 Responses 的服务。

`temperature` 可选，未配置时不传入。`max_tokens` 是 Anthropic 输出上限；本地无鉴权服务可显式设置 `require_api_key: false`，其余服务默认要求密钥。超过 `max_papers` 会报错等待调整，避免静默丢弃论文。

旧 `openai_compatible` 后端名暂作为 `api` 的别名保留，但地址、密钥和模型都必须迁移到这三个通用环境变量，旧 JSON 字段和供应商专用变量不再读取。CLI 后端仍使用前面的 CLI 配置和登录方式；这三个变量用于直接 API 调用。

## 自定义飞书群

在目标群创建自定义机器人。每个群对应一个机器人地址，群名称只是本地备注；不是输入群名就能查找并发到群里。

```json
{
  "sinks": [
    {
      "type": "feishu_bot",
      "name": "论文研究群",
      "enabled": true,
      "webhook_env": "FEISHU_RESEARCH_WEBHOOK",
      "secret_env": "FEISHU_RESEARCH_SECRET",
      "body": "concise"
    },
    {
      "type": "feishu_bot",
      "name": "团队交流群",
      "enabled": true,
      "webhook_env": "FEISHU_TEAM_WEBHOOK",
      "body": "concise"
    }
  ]
}
```

在根目录 `.env` 中填写对应机器人的地址和签名密钥，也可以通过操作系统环境变量或密钥管理系统提供。Windows 用户环境变量由任务入口补充到运行进程；直接运行 Python 时需新开终端以读取更新后的系统环境。不要把真实值写入 `profile.json` 或提交到仓库。未开启机器人签名验证时，删除该目标的 `secret_env` 字段；开启时必须提供对应变量。

每增加一个群，就增加一个 `feishu_bot` 配置，引用该群独立的环境变量。`body` 可选 `concise` 或 `full`；默认精简版。飞书默认直连，如需使用系统代理，设 `use_proxy: true`。机器人配置了关键词或 IP 白名单时，需确保日报内容及运行电脑满足限制。

其他目标包括 `local_file`、`obsidian`、`notion`、`feishu_bitable` 和通用 `webhook`，参数见 `scripts/sinks/` 对应脚本。显式设置 `sinks: []` 表示不推送，只输出本地日报。没有 `sinks` 字段时才使用旧配置兼容逻辑。

## 定时运行

Windows、macOS 和 Linux 的完整准备、预览、安装、日志、卸载与排错步骤，见 [本地部署](local-deployment.md)。

需要自定义任务名、Python 路径、配置或状态目录时，Windows 可以覆盖安装器参数：

```powershell
powershell -NoProfile -File scripts\install_task.ps1 -Time "21:00" -TaskName "daily-paper-radar" -Python "C:\Python312\python.exe" -Profile "C:\Tools\daily-paper-radar\config\profile.windows.json" -StateDir "C:\Tools\daily-paper-radar\state"
```

macOS 使用 `bash scripts/install_launchd.sh --time HH:MM`；Linux 用 cron 调用 `scripts/run_daily.sh`。

## 安装到 Claude Code 和 Codex

两个客户端共用同一份项目目录和状态，避免复制后重复订阅。macOS 在项目根目录执行：

```bash
mkdir -p ~/.claude/skills ~/.agents/skills
ln -s "$PWD" ~/.claude/skills/daily-paper-radar
ln -s "$PWD" ~/.agents/skills/daily-paper-radar
```

Windows 在项目根目录执行，使用目录联接，无需依赖 Unix 符号链接：

```powershell
$SkillRoot = (Get-Location).Path
New-Item -ItemType Directory -Force "$HOME\.claude\skills", "$HOME\.agents\skills" | Out-Null
New-Item -ItemType Junction -Path "$HOME\.claude\skills\daily-paper-radar" -Target $SkillRoot
New-Item -ItemType Junction -Path "$HOME\.agents\skills\daily-paper-radar" -Target $SkillRoot
```

若目标已存在，先检查它，不要覆盖已有安装。Claude Code 中使用 `/daily-paper-radar`，Codex 中使用 `$daily-paper-radar`；未发现时重启客户端。当前会话分析采用 `--prepare` → 生成摘要 → `--finish`，详细规则见 [SKILL.md](../SKILL.md)。仅查看时使用 `--dry-run`。

CLI 参数与安装目录依据 [Codex 官方命令参考](https://developers.openai.com/codex/cli/reference)、[Codex 技能文档](https://developers.openai.com/codex/skills) 和 [Claude Code 命令参考](https://code.claude.com/docs/en/cli-reference)。Windows 设置依据 [任务计划程序设置文档](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasksettingsset)。

## 运行可靠性和限制

- 抓取后先保留待处理批次；所有启用目标成功后才记录 `seen.json`。RSS 分类不完整、模型失败或推送失败都会停止并保留批次。
- `pending.json` 记录阶段和日期；再次运行先续跑上一批。每个目标成功后立即落盘投递记录，避免普通重试反复发送成功群。更改目标配置可能使它被视为新目标。
- 网络超时发生在服务端接收之后、或进程恰好在接收后崩溃，仍可能重复发送；飞书机器人不提供本项目可用的端到端恰好一次保证。
- 无新增论文时不主动打扰飞书群，但仍写本地日报。新批次清理上批次临时摘要、全文与笔记，持久收件箱不删除。
- 长时间关机可能错过 RSS 已滚动消失的论文；arXiv 来源没有历史日期回补功能，HF 来源仅覆盖配置的回看窗口。批次连续失败时后续抓取会暂停，需查看日志处理。
- `keywords` 每行内部按空格分词取 AND，多行之间取 OR。可自定义分类、研究方向、相关性信号、标题和 Markdown 展示模板；会议截止日期由用户维护。
- `.env`、`config/profile.json`、`config/profile.*.json`、运行状态、日志和缓存被 `.gitignore` 排除；分享代码时只提供模板。已有文件曾经被 Git 跟踪时，增加忽略规则不会自动移除历史，提交前仍需扫描实际暂存文件。

离线回归测试：

```bash
python -m unittest discover -s tests -v
```

## 开发与许可证

测试、提交和发布流程见 [参与贡献](../CONTRIBUTING.md)。核心脚本不需要 `pip install`；可选 PDF 阅读依赖按需安装：`python -m pip install pypdf`。项目使用 [MIT 许可证](../LICENSE)。

提交问题时请提供操作系统、Python 版本、后端类型、失败阶段和脱敏错误信息，不要附带 `.env` 或完整个人配置。
