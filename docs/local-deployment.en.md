# Local Deployment: Windows and macOS

Run the digest on your own computer when you want to:

- reuse an existing Claude Code or Codex login instead of paying for an API key;
- keep paper state entirely local;
- follow your machine's clock instead of relying on GitHub's best-effort schedule.

The trade-off: **your computer must stay on and online**. If you do not want to maintain a local environment, use [GitHub Actions in 5 steps](quickstart.en.md) instead.

## Choose a run mode

| Mode | Best for | Computer must be on | CLI login required |
| --- | --- | --- | --- |
| GitHub Actions | Most users | No | No |
| Local API backend | You have an API key and want local state | Yes | No |
| Local Claude Code / Codex backend | You already have a CLI login | Yes | Yes, under the same OS account that runs the job |

The default below is the **API backend**. See "Model backends" for CLI options.

## Common setup

### 1. Install Python 3.10+

- Windows: install from [python.org](https://www.python.org/downloads/) and enable **Add python.exe to PATH**.
- macOS: install from [python.org](https://www.python.org/downloads/), or check `python3 --version` in Terminal.

Basic collection and Feishu delivery need no `pip install`. Install optional dependencies only for PDF affiliation fallback:

```bash
python -m pip install -r requirements.txt
```

Windows uses `python`; macOS uses `python3`. Replace `python` with `python3` in the commands below on macOS.

### 2. Get the project

```bash
git clone https://github.com/wjmZZZ/daily-paper-radar.git
cd daily-paper-radar
```

Without Git, download the Release ZIP or use **Code → Download ZIP**, then extract it to a permanent directory. Avoid temporary or auto-cleaned download folders.

### 3. Create local configuration

```bash
python scripts/init_config.py
```

This creates two files without overwriting existing ones:

| File | Purpose | Committed to Git? |
| --- | --- | --- |
| `config/profile.json` | Keywords, sources, delivery targets, model settings | No |
| `.env` | API key, Feishu webhook, other credentials | No |

### 4. Add keywords

Open `config/profile.json`. A minimal usable configuration is:

```json
{
  "keywords": ["large language model", "reasoning", "agent"]
}
```

Keep the other template values. Optional:

```json
{
  "focus_description": "LLM reasoning, agents, and retrieval-augmented generation",
  "paper_preferences": "Prefer papers with concrete methods and comparative experiments",
  "keywords": []
}
```

With all three empty, the default Hugging Face source still produces a general highlights digest. Fields starting with `_` are Chinese inline help; keep or delete them.

### 5. Fill `.env`

Open the `.env` file in the project root:

```dotenv
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL_NAME=your-model-name
```

Supply `LLM_API_KEY` and `FEISHU_WEBHOOK` through your process environment or secret manager. Credential assignments are omitted from examples. Local `.env` loading is also supported; never commit or share a file containing credentials.

- `LLM_BASE_URL` accepts OpenAI-compatible and Anthropic-native endpoints. See [Custom models](advanced.md#自定义模型) for URL rules.
- To send to a Feishu group, set the sink's `enabled` to `true` in `config/profile.json`:

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

- Supply the signing secret through the `FEISHU_SECRET` environment variable and set `"secret_env": "FEISHU_SECRET"` in the sink.
- Process environment variables take precedence over `.env`. Never paste `.env`, keys, or webhook URLs into chats, issues, or screenshots.

### 6. Check and preview

```bash
python scripts/run_daily.py --check
python scripts/run_daily.py --dry-run --allow-peak
```

- `--check` validates local configuration only; it does not access the network or send messages.
- `--dry-run` collects papers and calls the model, writes `state/preview.md`, sends nothing, and does not change deduplication state.
- Preview consumes model quota.

Off-peak protection is on by default: `--dry-run` and real runs call the model only outside `LLM_PEAK_WINDOWS`, favoring cheaper windows. To debug at any hour, set `LLM_OFFPEAK_ONLY=false` in `.env`; see the [scheduling reference](scheduling.md) (Simplified Chinese).

Review `state/preview.md`, then run for real:

```bash
python scripts/run_daily.py
```

A real run writes `state/output/digest.md` and `state/inbox/<date>.md`, and delivers to enabled targets.

## Model backends

Switch `llm_enrich.backend` in `config/profile.json`:

| Backend | Use case | Preparation |
| --- | --- | --- |
| `api` | Default, most stable | Three model variables in `.env` |
| `claude_code` | You have a Claude Code login | `claude` CLI installed and logged in under the same OS account |
| `codex` | You have a Codex login | `codex` CLI installed and logged in under the same OS account |

Example CLI configuration:

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

Notes:

- Scheduled jobs run as your OS account, so the CLI must be logged in under **that same account**.
- A logged-in desktop app does not prove the command-line tool is logged in. Run `claude` or `codex` once in a terminal first.
- On Windows, use the standard npm-installed `claude.cmd` / `codex.cmd`. Custom batch wrappers may not be invoked correctly by Task Scheduler.
- Local scheduled mode performs abstract-level analysis. Deep reading happens interactively inside Claude Code or Codex.

## Windows: daily automation

### Install the task

In PowerShell, from the project directory:

```powershell
powershell -NoProfile -File scripts/install_task.ps1 -Time "10:30"
```

The installer validates the configuration, then registers a task named `daily-paper-radar`. Default behavior:

- Runs as the current logged-in account. **It runs while locked but not after sign-out.**
- Catches up after a missed start and requests wake-up, subject to power policy.
- Retries every 15 minutes, up to 3 times; each run is limited to 3 hours.
- Skips a new instance while one is already running.
- Credentials are not written into the task XML; they come from `.env` and user environment variables at runtime.

### Inspect and trigger

```powershell
Get-ScheduledTask -TaskName "daily-paper-radar"
Get-ScheduledTaskInfo -TaskName "daily-paper-radar"
```

After confirming the configuration, you can trigger a real run:

```powershell
# This performs a real delivery. Use only when ready.
Start-ScheduledTask -TaskName "daily-paper-radar"
```

### Logs

```powershell
Get-Content state\run.log -Tail 100
```

### Uninstall

```powershell
powershell -NoProfile -File scripts/install_task.ps1 -Uninstall
```

### Run after sign-out

Open **Task Scheduler → Task Scheduler Library → daily-paper-radar → Properties → General** and choose "Run whether user is logged on or not", then set the account as prompted. Do not switch to the SYSTEM account: it cannot see your personal CLI login or user directory.

### Execution policy blocks the script

Follow your organization's policy. Do not permanently disable execution policy on an unmanaged machine. Where allowed, you can run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_task.ps1 -Time "10:30"
```

## macOS: daily automation

### Install the task

```bash
python3 scripts/run_daily.py --check
python3 scripts/run_daily.py --dry-run
bash scripts/install_launchd.sh --time 10:30
```

The installer creates the user LaunchAgent `com.paperradar.daily`, using the absolute path of the current Python and your machine's local time. Credentials are read from `.env` or the process environment and are not copied into the plist.

The system `python3` on macOS may be 3.9 or older. Run `python3 --version` first; when it is older than 3.10, install 3.10+ from [python.org](https://www.python.org/downloads/) and run the installer with that interpreter. The installer records the project's absolute path and the current Python; reinstall after moving or renaming the project, or after changing Python.

### Inspect

```bash
launchctl print gui/$(id -u)/com.paperradar.daily
```

Logs:

```bash
tail -n 100 state/run.log          # run log
tail -n 100 state/launchd.err.log  # early startup errors
```

A job missed while the computer is asleep runs once after wake; multiple missed intervals are coalesced into one. A job missed while the computer is powered off does not run later; run `python3 scripts/run_daily.py` manually when needed.

### Uninstall

```bash
bash scripts/install_launchd.sh --uninstall
```

### Directory permissions

macOS privacy controls can block background access to Desktop, Documents, and Downloads. Put the project in a stable, accessible location such as `~/daily-paper-radar`, or grant terminal / Python access when the system prompts.

## Linux: manual scheduling (secondary)

Linux is not the primary local-deployment target; GitHub Actions is recommended. To run locally:

```bash
python3 scripts/run_daily.py --check
python3 scripts/run_daily.py --dry-run
python3 scripts/run_daily.py
```

For a daily schedule, call the existing entry script from cron:

```cron
# Runs daily at 10:30; adjust the path and Python interpreter.
30 10 * * * cd /opt/daily-paper-radar && PYTHON=/usr/bin/python3 ./scripts/run_daily.sh >> state/cron.log 2>&1
```

Cron follows the system timezone. For Beijing time, set the system timezone to `Asia/Shanghai`, or set `CRON_TZ=Asia/Shanghai` in the crontab if your cron implementation supports it.

## Files, state, and backups

| Path | Contents | Back up? |
| --- | --- | --- |
| `.env` | Model and Feishu credentials | Yes, securely |
| `config/profile.json` | Keywords, sources, delivery settings | Yes |
| `state/seen.json` | Delivered-paper deduplication | Yes |
| `state/pending.json` | Unfinished batch | Yes, before upgrades |
| `state/output/` | Raw candidates, analysis, digest | Optional |
| `state/run.log` | Run log | Keep for troubleshooting |
| `state/preview.md` | Latest preview | No |

Do not delete `state/seen.json` merely to resend papers. Use:

```bash
python scripts/run_daily.py --reissue
```

To resend only the already-generated digest to the currently configured group:

```bash
python scripts/publish.py --resend-bot
```

## Upgrading

1. Back up `.env`, `config/profile.json`, and `state/`.
2. Pull the new code. The init script never overwrites existing configuration.
3. Compare `config/_template.json` for new fields and merge what you need.
4. Run `python scripts/run_daily.py --check` and `--dry-run`.
5. Re-enable the scheduled task.

Never replace your `.env`, profile, or `state/` with another user's files.

## Troubleshooting

- Scheduled task did not run: check `state/run.log`, then confirm Task Scheduler / LaunchAgent is enabled.
- `.env` format error: the message hides values and shows the line number; check quotes and `#`.
- `已有任务正在运行`: a previous run is still active, or a stale lock exists. Confirm no Python process is running before intervening.
- Model 401 / 404 / timeout, Feishu signature or keyword errors: see [Troubleshooting](troubleshooting.en.md).

## First preview and digest language

Run `python scripts/render_demo.py` for an offline Chinese sample, or add `--language en` for English. This does not call a model or send messages.

For a live preview, run `python scripts/run_daily.py --dry-run --allow-peak`. The flag permits peak-hour model calls for this run only, may increase costs, and leaves scheduled settings unchanged.

Set `digest_language` in your local profile to `zh` (default) or `en`. Custom titles and templates are not translated. Complete pending batches before changing languages; resending does not translate saved content.
