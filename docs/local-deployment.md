# 本地部署：Windows 与 macOS

本地部署适合以下情况：

- 想用 Claude Code / Codex 的现有登录，不想单独申请 API Key；
- 想完全掌控数据，不把论文状态放到 GitHub；
- 想严格按本机时间运行，而不是依赖 GitHub 的尽力而为定时。

代价是**电脑需要保持开机和联网**。如果不想维护本地环境，优先使用 [GitHub Actions 5 步跑通](quickstart.md)。

## 先选运行方式

| 方式 | 适合谁 | 电脑要开机吗 | 需要登录 CLI 吗 |
| --- | --- | --- | --- |
| GitHub Actions | 大多数人，电脑经常关机 | 否 | 否 |
| 本地 API 后端 | 有 API Key，想本地保存状态 | 是 | 否 |
| 本地 Claude Code / Codex 后端 | 已登录客户端，不想再买 API | 是 | 是，且要用运行任务的同一系统账户 |

下面默认使用 **API 后端**。切换到 CLI 后端见「选择模型后端」。

## 通用准备

### 1. 安装 Python 3.10+

- Windows：从 [python.org](https://www.python.org/downloads/) 安装，勾选 **Add python.exe to PATH**。
- macOS：从 [python.org](https://www.python.org/downloads/) 安装，或在终端确认 `python3 --version`。

不需要 `pip install` 就能完成基础抓取和飞书推送。只有开启 PDF 首页机构识别时，才需要安装依赖：

```bash
python -m pip install -r requirements.txt
```

Windows 用 `python`，macOS 用 `python3`。下文命令里的 `python` 在 macOS 上替换为 `python3`。

### 2. 下载项目

```bash
git clone https://github.com/wjmZZZ/daily-paper-radar.git
cd daily-paper-radar
```

没有 Git 时，下载 Release ZIP 或仓库的 **Code → Download ZIP**，解压到固定目录。不要放在临时目录或会被系统清理的下载目录。

### 3. 生成配置文件

```bash
python scripts/init_config.py
```

会生成两个文件，已有文件不会被覆盖：

| 文件 | 作用 | 会提交到 Git 吗 |
| --- | --- | --- |
| `config/profile.json` | 关键词、来源、推送目标、模型参数 | 不会 |
| `.env` | API Key、飞书 Webhook 等凭据 | 不会 |

### 4. 填关键词（只填这一项也能用）

打开 `config/profile.json`，最小可用配置：

```json
{
  "keywords": ["large language model", "reasoning", "agent"]
}
```

其余字段保留模板默认值。可选：

```json
{
  "focus_description": "大语言模型推理、智能体和检索增强生成",
  "paper_preferences": "优先看有具体方法和实验对比的论文，不重点看纯综述",
  "keywords": []
}
```

三项都留空时，默认 Hugging Face 来源仍会生成通用精选简报。以 `_` 开头的字段是中文填写说明，可保留或删除。

### 5. 填 `.env`

打开根目录 `.env`：

```dotenv
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL_NAME=你的模型名
```

凭据 `LLM_API_KEY` 与 `FEISHU_WEBHOOK` 请通过受控进程环境或密钥管理工具注入。示例不提供凭据赋值行；本地 `.env` 读取仍兼容，但不要将真实文件提交或分享。

- `LLM_BASE_URL` 支持 OpenAI 兼容接口和 Anthropic 原生接口，规则见 [自定义模型](advanced.md#自定义模型)。
- 需要发飞书群时，再把 `config/profile.json` 中 `sinks` 的 `enabled` 改为 `true`：

```json
{
  "sinks": [
    {
      "type": "feishu_bot",
      "enabled": true,
      "webhook_env": "FEISHU_WEBHOOK"
    }
  ]
}
```

- 机器人开启签名校验时，通过受控环境变量 `FEISHU_SECRET` 注入签名密钥，并在对应 sink 增加 `"secret_env": "FEISHU_SECRET"`。
- 系统环境变量优先于 `.env`；不要把 `.env` 或真实密钥发到聊天、Issue 或截图里。

### 6. 检查并预览

```bash
python scripts/run_daily.py --check
python scripts/run_daily.py --dry-run --allow-peak
```

- `--check` 只检查本地配置，不联网、不推送。
- `--dry-run` 会抓取论文、调用模型，结果写入 `state/preview.md`，**不发飞书、不改变正式去重状态**。
- 预览会消耗模型额度。

低峰保护默认开启：`--dry-run` 和正式运行只在 `LLM_PEAK_WINDOWS` 之外调用模型，优先谷时省钱。需要白天随时调试时，在 `.env` 设 `LLM_OFFPEAK_ONLY=false`；规则见 [调度与省钱](scheduling.md)。

打开 `state/preview.md` 检查内容。确认后再正式运行：

```bash
python scripts/run_daily.py
```

正式运行会写入 `state/output/digest.md` 和 `state/inbox/日期.md`，并发送到已启用的目标。

## 选择模型后端

在 `config/profile.json` 的 `llm_enrich.backend` 切换：

| 后端 | 适用场景 | 需要的准备 |
| --- | --- | --- |
| `api` | 默认，最稳定 | `.env` 中的三个模型变量 |
| `claude_code` | 已登录 Claude Code，不想用 API Key | 同一系统账户已安装并登录 `claude` CLI |
| `codex` | 已登录 Codex | 同一系统账户已安装并登录 `codex` CLI |

CLI 后端示例：

```json
{
  "llm_enrich": {
    "backend": "claude_code",
    "claude_code": {
      "cli_path": "claude",
      "model": "",
      "batch_size": 10,
      "timeout_s": 600
    }
  }
}
```

注意：

- 定时任务由系统账户运行，CLI 必须在**同一个账户**下登录。
- CLI 桌面客户端已登录，不等于命令行已登录。先在终端实际运行一次 `claude` 或 `codex`。
- Windows 使用标准 npm 安装的 `claude.cmd` / `codex.cmd`；自定义批处理包装器可能无法被任务计划程序正确调用。
- 本地定时模式只做摘要级分析；全文深读在 Claude Code / Codex 当前会话中执行。

## Windows：每天自动运行

### 安装任务

在项目目录打开 PowerShell：

```powershell
powershell -NoProfile -File scripts/install_task.ps1 -Time "10:30"
```

安装器会先执行一次配置检查，然后注册名为 `daily-paper-radar` 的计划任务。默认行为：

- 使用当前登录账户，**锁屏可运行，注销后不运行**。
- 错过时间后补跑；请求唤醒，但能否唤醒取决于电源策略。
- 失败后每隔 15 分钟重试，最多 3 次；单次最长 3 小时。
- 已有实例运行时跳过新实例。
- 凭据不写入任务 XML；运行时从 `.env` 和用户环境变量读取。

### 检查与手动触发

```powershell
Get-ScheduledTask -TaskName "daily-paper-radar"
Get-ScheduledTaskInfo -TaskName "daily-paper-radar"
```

`Get-ScheduledTaskInfo` 会显示上次运行时间、下次运行时间和上次结果。确认配置后可以手动触发一次：

```powershell
# 会执行真实推送，仅在准备好后使用。
Start-ScheduledTask -TaskName "daily-paper-radar"
```

### 查看日志

```powershell
Get-Content state\run.log -Tail 100
```

### 卸载

```powershell
powershell -NoProfile -File scripts/install_task.ps1 -Uninstall
```

### 注销后仍运行

打开 **任务计划程序 → 任务计划程序库 → daily-paper-radar → 属性 → 常规**，选择「不管用户是否登录都要运行」，按提示设置账户。不要直接改成 SYSTEM 账户，否则找不到个人 CLI 登录信息和用户目录。

### 执行策略阻止脚本

如果公司或系统策略阻止 `.ps1`，按组织规范处理。不要在不受控环境永久关闭执行策略。可以先在允许的范围内运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_task.ps1 -Time "10:30"
```

## macOS：每天自动运行

### 安装任务

```bash
python3 scripts/run_daily.py --check
python3 scripts/run_daily.py --dry-run
bash scripts/install_launchd.sh --time 10:30
```

安装器会生成用户级 LaunchAgent `com.paperradar.daily`，使用当前 Python 的绝对路径，时间按本机时区。凭据从项目根目录 `.env` 或已注入的进程环境读取，不会复制进 plist。

macOS 自带的 `python3` 可能是 3.9 或更早。先运行 `python3 --version` 确认；低于 3.10 时，从 [python.org](https://www.python.org/downloads/) 安装 3.10+，再用该解释器运行安装器。安装器记录的是当前项目的绝对路径和当前 Python；移动项目、重命名目录或更换 Python 后，重新运行安装器。

### 检查状态

```bash
launchctl print gui/$(id -u)/com.paperradar.daily
```

日志：

```bash
tail -n 100 state/run.log          # 运行日志
tail -n 100 state/launchd.err.log  # 启动阶段错误
```

电脑休眠期间错过的任务，会在唤醒后补跑一次；多个错过的时段合并为一次。关机期间错过的任务不会补跑，需要时手动执行一次 `python3 scripts/run_daily.py`。

### 卸载

```bash
bash scripts/install_launchd.sh --uninstall
```

### 目录权限

macOS 对桌面、文稿、下载等目录有隐私控制。后台任务可能无法读取项目目录。建议把项目放在固定、可访问的位置（例如 `~/daily-paper-radar`），或按系统提示给终端 / Python 授予访问权限。

## Linux：手动定时（非重点）

Linux 不是本地部署的主要目标，推荐直接用 GitHub Actions。如果确实要本地运行，使用现成入口脚本即可：

```bash
python3 scripts/run_daily.py --check
python3 scripts/run_daily.py --dry-run
python3 scripts/run_daily.py
```

需要每天定时，可用 cron 调用 `scripts/run_daily.sh`：

```cron
# 每天 10:30 运行；路径和 Python 按实际情况修改。
30 10 * * * cd /opt/daily-paper-radar && PYTHON=/usr/bin/python3 ./scripts/run_daily.sh >> state/cron.log 2>&1
```

cron 的时区跟随系统。希望按北京时间运行，就把系统时区设为 `Asia/Shanghai`，或在 crontab 中设置 `CRON_TZ=Asia/Shanghai`（是否支持取决于 cron 实现）。

## 目录、状态与备份

| 路径 | 内容 | 要备份吗 |
| --- | --- | --- |
| `.env` | 模型与飞书凭据 | 是，安全保存 |
| `config/profile.json` | 关键词、来源、推送配置 | 是 |
| `state/seen.json` | 已推送论文去重记录 | 是 |
| `state/pending.json` | 未完成批次 | 是，升级前 |
| `state/output/` | 本批原始候选、分析、日报 | 按需 |
| `state/run.log` | 运行日志 | 排错时保留 |
| `state/preview.md` | 最近一次预览 | 否 |

不要为了让论文重发而直接删除 `state/seen.json`。需要重发上一批时使用：

```bash
python scripts/run_daily.py --reissue
```

只需要把已生成日报重发到当前飞书群时：

```bash
python scripts/publish.py --resend-bot
```

## 升级

1. 备份 `.env`、`config/profile.json`、`state/`。
2. 拉取新代码。初始化脚本不会覆盖已有配置。
3. 对比 `config/_template.json` 的新字段，手动合并需要的配置。
4. 运行 `python scripts/run_daily.py --check` 和 `--dry-run`。
5. 确认无误后恢复定时任务。

不要用别人的 `.env`、profile 或 `state/` 覆盖自己的文件。

## 排错入口

- 定时任务没有运行：先看 `state/run.log`，再检查任务计划程序 / LaunchAgent 是否启用。
- `.env` 格式错误：错误信息会隐藏内容，只显示行号；检查引号和 `#`。
- 提示 `已有任务正在运行`：上一次运行还没结束，或锁文件残留。确认没有 Python 进程后再处理。
- 模型 401 / 404 / 超时、飞书签名或关键词错误：见 [常见问题与排错](troubleshooting.md)。

## 首次试用与日报语言

先运行 `python scripts/render_demo.py` 可离线查看中文样例，添加 `--language en` 查看英文样例，不调用模型、不发送消息。

首次真实预览可运行 `python scripts/run_daily.py --dry-run --allow-peak`。此参数明确允许本次在高峰调用模型，可能增加费用，不修改后续定时设置。

本地配置 `digest_language` 支持 `zh`（默认中文）与 `en`（英文）。自定义标题和模板不自动翻译。已有待发批次请先完成，再修改语言；只重发不会翻译旧内容。
