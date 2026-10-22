<div align="center">

<img src="assets/banner.png" alt="daily-paper-radar: follow research and receive daily paper digests" width="100%">

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

Tell it what you follow. Every day it collects new candidates from **Hugging Face Daily Papers and arXiv**, has the LLM score each one against **your research topic**, explains the ones that matter, and delivers a digest to Feishu in Chinese or English (Chinese by default). Optionally append the full report to a Feishu document as a searchable archive.

Use it as a **GitHub Actions workflow** that runs while your computer is off, a **local scheduled job** on Windows or macOS, or a **Claude Code / Codex skill** for on-demand reading.

See the [English sample](examples/digest-full.en.md) or [Chinese sample](examples/digest-full.zh.md). Set `digest_language` locally or `DIGEST_LANGUAGE` in Actions to `en` or `zh`. Run `python3 scripts/render_demo.py --language en` for an offline layout preview without API credentials.

## Why this one

- **Your topic, not a generic paper dump.** Give it the keywords or research direction you follow; the LLM ranks every candidate against that topic instead of listing all new papers. Use both for a sharper filter, and add reading preferences for style. With no topic set, it falls back to general highlights.
- **Summaries you can act on.** Each paper gets its problem, method, contribution, available evidence, limitations, and a reading recommendation. Analysis is based on abstracts by default and never claims a full-paper read.
- **Readable titles.** `date–venue–first-author institution–core contribution`, with unknown fields omitted.
- **Recoverable runs.** Paper analysis, pending batches, and per-target delivery receipts are persisted, so a failed run resumes instead of resending what already arrived.
- **Optional source screening.** Keep only first-author institutions in a versioned QS top-100 snapshot or your own team allowlist; fall back to the PDF title page when HTML metadata is missing.
- **Configurable models and calling hours.** OpenAI-compatible Chat Completions and Anthropic Messages share three environment variables. Off-peak-only analysis is on by default, so scheduled runs respect the configured calling hours. Any discount depends on your provider. Prepared digests can be delivered without another model call.

## Quick start: GitHub Actions

1. **Fork** this repository.
2. Open your fork's **Actions** tab and enable workflows. GitHub disables them in forks by default.
3. Under **Settings → Secrets and variables → Actions → Secrets**, add `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL_NAME`, and `FEISHU_WEBHOOK`.
4. Under **Variables**, add the topic you follow in `PAPER_KEYWORDS` (English keywords) or `PAPER_FOCUS` (a research direction). This is the filter that decides which papers reach your digest. Leave `DAILY_ENABLED` unset for now.
5. Open **Actions → daily.yml → Run workflow** (the daily delivery workflow): run `preview`, download the `paper-preview` artifact, then run `all` for the first real delivery. After it succeeds, set `DAILY_ENABLED` to `true`.

The whole loop is **topic + model API key + Feishu webhook → automatic daily delivery**. Scheduled analysis waits for off-peak pricing windows by default (`LLM_OFFPEAK_ONLY=true`); delivery targets **09:30 Beijing time** once a digest is ready. GitHub schedules are best-effort, so delivery can be late; see [Why delivery is not always punctual](docs/quickstart.en.md#why-delivery-is-not-always-punctual).

Full menu paths, Feishu webhook setup, and expected results: **[GitHub Actions in 5 Steps](docs/quickstart.en.md)**.

## Quick start: local

Requires **Python 3.10+**. Collection and rendering use the standard library; `pypdf` is optional for PDF affiliation extraction.

```bash
git clone https://github.com/wjmZZZ/daily-paper-radar.git
cd daily-paper-radar
python scripts/init_config.py
python scripts/run_daily.py --check
python scripts/run_daily.py --dry-run --allow-peak
python scripts/run_daily.py
```

Use `python3` on macOS if needed. `init_config.py` creates `.env` and `config/profile.json` without overwriting existing files. Supply model and Feishu credentials through your process environment or secret manager, then adjust `keywords` and `sinks` in `config/profile.json`.

Schedule it locally with `scripts/install_task.ps1` on Windows or `scripts/install_launchd.sh` on macOS. The computer must stay on and connected. See **[Local Deployment](docs/local-deployment.en.md)** for the complete walkthrough, API vs. Claude Code/Codex backends, logs, upgrades, and removal.

For the first preview, `--allow-peak` permits model calls outside the configured off-peak hours for this run only. It may increase costs and does not change scheduled settings.

## Documentation

| Topic | English | Chinese |
| --- | --- | --- |
| GitHub Actions in 5 steps | [Quick start](docs/quickstart.en.md) | [Quick start](docs/quickstart.md) |
| Windows / macOS local setup | [Local deployment](docs/local-deployment.en.md) | [Local deployment](docs/local-deployment.md) |
| Common failures | [Troubleshooting](docs/troubleshooting.en.md) | [Troubleshooting](docs/troubleshooting.md) |
| All Secrets and Variables | [Actions reference](docs/github-actions.en.md) | [Actions reference](docs/github-actions.md) |
| Timing, pricing, full variable table | — | [Scheduling and costs](docs/scheduling.md) |
| Model backends, multiple groups, `.env` | — | [Advanced configuration](docs/advanced.md) |
| Institution screening | — | [Source screening](docs/source-screening.md) |
| Feishu document archive | — | [Feishu archive](docs/feishu-archive.md) |

The complete index, including which documents are Chinese-only, is in **[docs/README.md](docs/README.md)**.

## What the digest looks like

This screenshot shows a real delivery from an existing deployment on October 20, 2026. See the samples for the current layout. The banner is a conceptual illustration.

<img src="assets/screenshots/feishu-digest-zh.png" alt="A Chinese paper digest delivered to Feishu" width="760">

- Candidates are ranked by LLM-judged relevance; 🔥 marks topic relevance, not scientific quality.
- Medium/high-relevance papers are expanded with a summary, implications, limitations, and reading recommendation. Low-relevance papers keep title links only (five by default).
- Titles follow `date–venue–first-author institution–core contribution`. The date is the Beijing-time digest date; missing venue or affiliation is omitted.
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
