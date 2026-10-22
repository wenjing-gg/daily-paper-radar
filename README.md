<div align="center">

<img src="assets/banner.png" alt="daily-paper-radar：追踪研究前沿，生成并推送每日论文简报" width="100%">

# daily-paper-radar

**A daily paper digest for the research topics you follow — explained and delivered to your Feishu group.**

[![CI](https://github.com/wjmZZZ/daily-paper-radar/actions/workflows/tests.yml/badge.svg)](https://github.com/wjmZZZ/daily-paper-radar/actions/workflows/tests.yml)
[![Release](https://img.shields.io/github/v/release/wjmZZZ/daily-paper-radar?include_prereleases&sort=semver)](https://github.com/wjmZZZ/daily-paper-radar/releases)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)](#quick-start-local)
[![Feishu](https://img.shields.io/badge/delivery-Feishu-3370FF)](docs/feishu-archive.md)

**English** · [简体中文](README.zh-CN.md)

</div>

Tell it what you follow. Every day it collects new candidates from **Hugging Face Daily Papers and arXiv**, has the LLM score each one against **your research topic**, explains the ones that matter, and delivers a Chinese digest to Feishu. Optionally append the full report to a Feishu document as a searchable archive.

Use it as a **GitHub Actions workflow** that runs while your computer is off, a **local scheduled job** on Windows or macOS, or a **Claude Code / Codex skill** for on-demand reading.

先看 [中文样例](examples/digest-full.zh.md) / [英文样例](examples/digest-full.en.md)。默认中文；通过本地 `digest_language` 或 Actions 的 `DIGEST_LANGUAGE` 选择 `zh` / `en`。无需密钥可运行 `python3 scripts/render_demo.py --language en` 查看离线排版演示。

## Why this one

- **Your topic, not a generic paper dump.** Give it the keywords or research direction you follow; the LLM ranks every candidate against that topic instead of listing all new papers. Use both for a sharper filter, and add reading preferences for style. With no topic set, it falls back to general highlights.
- **Summaries you can act on.** Each paper gets its problem, method, contribution, available evidence, limitations, and a reading recommendation. Analysis is based on abstracts by default and never claims a full-paper read.
- **Readable titles.** `date–venue–first-author institution–core contribution`, with unknown fields omitted.
- **Recoverable runs.** Paper analysis, pending batches, and per-target delivery receipts are persisted, so a failed run resumes instead of resending what already arrived.
- **Optional source screening.** Keep only first-author institutions in a versioned QS top-100 snapshot or your own team allowlist; fall back to the PDF title page when HTML metadata is missing.
- **Flexible models, cheaper by default.** OpenAI-compatible Chat Completions and Anthropic Messages share three environment variables. Off-peak-only analysis is on by default, so scheduled runs use discounted windows; prepared digests are still delivered on time without a model call.

## Quick start: GitHub Actions

1. **Fork** this repository.
2. Open your fork's **Actions** tab and enable workflows. GitHub disables them in forks by default.
3. Under **Settings → Secrets and variables → Actions → Secrets**, add `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL_NAME`, and `FEISHU_WEBHOOK`.
4. Under **Variables**, add the topic you follow in `PAPER_KEYWORDS` (English keywords) or `PAPER_FOCUS` (a research direction). This is the filter that decides which papers reach your digest. Leave `DAILY_ENABLED` unset for now.
5. Open **Actions → 每日论文推送 → Run workflow**: run `preview`, download the `paper-preview` artifact, then run `all` for the first real delivery. After it succeeds, set `DAILY_ENABLED` to `true`.

The whole loop is **topic + model API key + Feishu webhook → automatic daily delivery**. Scheduled analysis waits for off-peak pricing windows by default (`LLM_OFFPEAK_ONLY=true`); delivery targets **09:30 Beijing time** once a digest is ready. GitHub schedules are best-effort, so delivery can be late; see [Why delivery is not always punctual](docs/quickstart.en.md#why-delivery-is-not-always-punctual).

Full menu paths, Feishu webhook setup, and expected results: **[GitHub Actions in 5 Steps](docs/quickstart.en.md)**.

## Quick start: local

Requires **Python 3.10+**. Collection and rendering use the standard library; `pypdf` is optional for PDF affiliation extraction.

```bash
git clone https://github.com/wjmZZZ/daily-paper-radar.git
cd daily-paper-radar
python scripts/init_config.py
python scripts/run_daily.py --check
python scripts/run_daily.py --dry-run
python scripts/run_daily.py
```

Use `python3` on macOS if needed. `init_config.py` creates `.env` and `config/profile.json` without overwriting existing files. Fill in model and Feishu credentials in `.env`, then adjust `keywords` and `sinks` in `config/profile.json`.

Schedule it locally with `scripts/install_task.ps1` on Windows or `scripts/install_launchd.sh` on macOS. The computer must stay on and connected. See **[Local Deployment](docs/local-deployment.en.md)** for the complete walkthrough, API vs. Claude Code/Codex backends, logs, upgrades, and removal.

首次预览中的 `--allow-peak` 仅对本次放开高峰限制，可能增加费用；定时配置不变。凭据通过受控进程环境注入。

## Documentation

| Topic | English | 简体中文 |
| --- | --- | --- |
| GitHub Actions in 5 steps | [Quick start](docs/quickstart.en.md) | [快速开始](docs/quickstart.md) |
| Windows / macOS local setup | [Local deployment](docs/local-deployment.en.md) | [本地部署](docs/local-deployment.md) |
| Common failures | [Troubleshooting](docs/troubleshooting.en.md) | [常见问题与排错](docs/troubleshooting.md) |
| All Secrets and Variables | [Actions reference](docs/github-actions.en.md) | [云端配置](docs/github-actions.md) |
| Timing, pricing, full variable table | — | [调度与省钱](docs/scheduling.md) |
| Model backends, multiple groups, `.env` | — | [进阶配置](docs/advanced.md) |
| Institution screening | — | [来源筛选](docs/source-screening.md) |
| Feishu document archive | — | [飞书文档归档](docs/feishu-archive.md) |

The complete index, including which documents are Chinese-only, is in **[docs/README.md](docs/README.md)**.

## What the digest looks like

以下为已有部署的实际飞书截图（2026-10-20），新版栏目以当前代码和样例为准。页首主图为概念视觉，实际推送效果如下。

<img src="assets/screenshots/feishu-digest-zh.png" alt="中文论文日报在飞书中的实际展示" width="760">


- Candidates are ranked by LLM-judged relevance; 🔥 marks topic relevance, not scientific quality.
- Medium/high-relevance papers are expanded with a Chinese summary and inspiration. Low-relevance papers keep title links only (five by default).
- Titles follow `年月日-会议/期刊-一作机构中文简称-核心贡献`. The date is the Beijing-time digest date; missing venue or affiliation is omitted.
- The model name shown at the top is the one actually used for that batch.
- When no new papers are found, the group stays quiet by default.


## Limits and privacy

Community votes indicate attention, not correctness, and candidate limits can miss relevant work. Affiliation extraction depends on attributable author metadata. Retries reduce duplicate delivery but cannot guarantee exactly-once behavior after lost state or an ambiguous network failure. Model API costs and availability depend on your provider.

Credentials, `config/profile.json`, runtime state, logs, and editor history are excluded from Git. Never commit a real `.env` or webhook. Public repository artifacts can still reveal research interests through paper abstracts.

## Contributing

Bug reports, documentation improvements, and focused pull requests are welcome. Read [CONTRIBUTING](CONTRIBUTING.md), the [code of conduct](CODE_OF_CONDUCT.md), and the [security policy](SECURITY.md). These documents and the advanced guides are currently written in Simplified Chinese.

```bash
python -m unittest discover -s tests -v
```

Unit tests need no API keys and send no Feishu messages. CI covers Windows, macOS, and Ubuntu on Python 3.10 and 3.12.

## License

[MIT](LICENSE).
