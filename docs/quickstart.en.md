# GitHub Actions in 5 Steps

This is the shortest path: **fork the repository → add 4 secrets → preview → first delivery → enable the daily schedule**. It runs while your computer is off. No local skill, no Claude Code or Codex login required.

For every parameter, see [the deployment reference](github-actions.en.md). For timing and pricing rules, see the [scheduling reference](scheduling.md) (Simplified Chinese). For failures, start with [Troubleshooting](troubleshooting.en.md).

## Before you start

| Requirement | Notes |
| --- | --- |
| A GitHub account | Actions is free for public repositories; private repositories consume your plan's minutes. |
| A model API reachable from the public internet | OpenAI-compatible Chat Completions or the Anthropic Messages API. GitHub-hosted runners run outside mainland China, so endpoints reachable only from there may time out. |
| A Feishu group | You need permission to add a custom bot to it. |
| 3–5 minutes | The first preview waits for model responses. |

## Step 1: Fork or copy the repository

- **Fork (recommended)**: click **Fork → Create fork**. You can sync upstream updates later.
- **Use this template**: available after the repository owner enables Template repository; use it when you want a fully independent repository.

Then open the **Actions** tab of your own repository. GitHub disables workflows in forks by default and shows:

> Workflows aren't being run on this forked repository.

Click **I understand my workflows, go ahead and enable them**. If you do not see this notice, workflows are already enabled.

> Scheduled runs are controlled by the same switch. Until Actions is enabled, the schedule you enable in Step 5 will not run.

## Step 2: Add model and Feishu secrets

Open **Settings → Secrets and variables → Actions → Secrets → New repository secret** and add these four required secrets:

| Secret | Value |
| --- | --- |
| `LLM_BASE_URL` | Your API base URL, for example `https://api.openai.com/v1`, `https://api.anthropic.com/v1`, or your compatible gateway |
| `LLM_API_KEY` | Your provider's real API key. Never share it or commit it. |
| `LLM_MODEL_NAME` | A model identifier your provider supports |
| `FEISHU_WEBHOOK` | The webhook of a custom bot in your target group |

Optional:

| Secret | When to add it |
| --- | --- |
| `FEISHU_SECRET` | Only when the bot has signature verification enabled. |
| `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_DOC_ID` | Only when appending the full digest to a Feishu document; see the [document archive guide](feishu-archive.md) (Simplified Chinese). |

You may use **Settings → Environments → daily-paper-radar → Environment secrets** instead. Pick one location; environment secrets win when names collide. Repository secrets alone are enough, so you do **not** have to create the environment first.

### Getting the Feishu webhook

1. Open the target group, then **··· → Settings → Group bots**.
2. Choose **Add bot → Custom bot**, and give it a name such as "Paper digest".
3. Copy the **webhook URL** into `FEISHU_WEBHOOK`.
4. If signature verification is enabled, copy that secret into `FEISHU_SECRET`. Otherwise, leave `FEISHU_SECRET` unset.
5. Check the keyword and IP restrictions below.

> **Keyword restriction**: the bot then accepts only messages containing the keyword. Either disable it or use a word that always appears in the digest, such as `论文`.
>
> **IP allowlist**: GitHub-hosted runners do not use fixed egress IPs. Disable the allowlist, or use a proxy with a fixed egress IP. To use a self-hosted runner, change `runs-on` in `.github/workflows/paper-job.yml` to your runner label, and install Python 3.10+ and dependencies on that runner.
>
> A group webhook can only send messages. Document archiving needs a separate Feishu app; see the document archive guide (Simplified Chinese).

## Step 3: Add the topic you follow

Open **Settings → Secrets and variables → Actions → Variables → New repository variable**.

| Variable | Required | Value |
| --- | --- | --- |
| `PAPER_KEYWORDS` | Recommended | The topic in English keywords, comma-separated, for example `reasoning, agent, evaluation` |
| `PAPER_FOCUS` | Recommended | A research direction, for example "LLM reasoning and agent evaluation" |
| `PAPER_PREFERENCES` | Optional | Reading preferences |
| `DIGEST_TITLE` | Optional | A title prefix for messages |
| `DAILY_ENABLED` | Required to enable the schedule | Leave it unset until Step 5 finishes, then set lowercase `true` |

**This step defines your subscription.** The keywords and focus are the relevance target the LLM scores every candidate against — not a literal title search. HF and arXiv candidates are ranked by how well they match your topic, so the more specific you are, the closer the digest gets to the work you follow. Use `PAPER_KEYWORDS` and `PAPER_FOCUS` together for a sharper filter; with all three empty, the digest falls back to general highlights.

> `PAPER_KEYWORDS` splits on the ASCII comma `,`; a full-width comma `，` becomes part of the keyword.
>
> `DAILY_ENABLED` must be a **repository variable**, not an environment variable. The workflow reads it before entering the environment; an environment-level value leaves scheduled runs skipped.
>
> `DAILY_ENABLED` accepts only the lowercase string `true`. `True`, `yes`, and `1` do not enable the schedule.
>
> **Off-peak tokens (on by default):** `LLM_OFFPEAK_ONLY` defaults to `true`, so scheduled analysis calls the model only inside off-peak windows instead of paying peak prices. GitHub schedules are best-effort anyway, so the default favors saving tokens: during US daylight saving the digest usually arrives around 09:30; during US standard time the first analysis window falls in peak hours and moves to after 12:17. Set `LLM_OFFPEAK_ONLY=false` to prioritize timeliness, or set `ARXIV_FRESHNESS_PRIORITY=true` to keep only the winter morning window.

## Step 4: Preview

1. Open **Actions → 每日论文推送 → Run workflow**.
2. Select the default branch (usually `main`).
3. Choose the `preview` operation and click **Run workflow**.
4. When the run turns green, open it and download the **`paper-preview`** artifact.

| File | Purpose |
| --- | --- |
| `preview.md` | The full digest; read this first |
| `preview-feishu.md` | The concise body sent to the group |
| `preview-feishu.json` | The card payload, useful for layout debugging |

`preview` calls the model and incurs charges, but sends nothing to Feishu and does not touch deduplication state. If the run fails, read the failing step's log and check [Troubleshooting](troubleshooting.en.md).

## Step 5: First real delivery, then enable the schedule

1. Once the preview looks right, open **Actions → 每日论文推送 → Run workflow**.
2. Choose the `all` operation. This **sends real Feishu messages**.
3. Confirm the digest arrives. The log should show `feishu_bot ok`, plus `feishu_doc ok` when archiving is configured.
4. Go back to **Settings → Secrets and variables → Actions → Variables** and set `DAILY_ENABLED` to `true`.

The scheduled workflow then runs on its own. Default targets, in Beijing time:

| Item | Beijing time |
| --- | --- |
| Off-peak analysis window during US daylight saving | 08:10–08:50 |
| Default analysis time during US standard time | from 12:17 (off-peak); from 09:10 with `ARXIV_FRESHNESS_PRIORITY=true` |
| Main delivery target | 09:30 when analysis is already complete |
| Check frequency | 08:10–11:55 every 15 minutes; recovery checks at 12:17 and 18:17 |

When a digest is already prepared, runs only deliver it without calling the model again. After a successful day, later checks exit immediately.

## Confirming success the next day

1. Open **Actions → 每日论文推送** and confirm a new run exists.
2. In the log, search for `定时检查` and compare the UTC time, Beijing time, and `cron` value.
3. Confirm the digest arrived in the group.
4. A **skipped** run usually means `DAILY_ENABLED` is not `true`, or the run was not on the default branch.

## Why delivery is not always punctual

GitHub's `schedule` event is best-effort: triggers can be delayed by minutes or tens of minutes, and can occasionally be dropped. This project checks every 15 minutes from 08:10 to 11:55, adds a dedicated 09:30 trigger, and retries at 12:17 and 18:17, but it **cannot guarantee delivery at exactly 09:30**.

The default off-peak mode also makes analysis wait for cheaper windows: during US standard time the first analysis runs after 12:17, and the digest moves with it. That is the trade-off for saving tokens; adjust `LLM_OFFPEAK_ONLY` or `ARXIV_FRESHNESS_PRIORITY` in Step 3 when you need morning delivery.

If you need strict punctuality:

- **Keep a computer on** and schedule locally with Windows Task Scheduler or macOS launchd; see [Local deployment](local-deployment.en.md).
- **Trigger externally**: call GitHub's `workflow_dispatch` API at 09:30 from an always-on server or a trusted scheduler. That requires a fine-grained PAT stored on the scheduler side; never put the PAT in the repository or public documentation.

## Operations at a glance

| Operation | What it does | Calls the model | Sends to Feishu |
| --- | --- | --- | --- |
| `check` | Validates configuration only | No | No |
| `preview` | Builds a preview artifact | Yes | No |
| `analyze` | Builds a pending digest | Yes | No |
| `publish` | Delivers a prepared digest | No | Yes |
| `all` | Builds and delivers | Yes | Yes |
| `resend_bot` | Resends the last digest | No | Yes |
| `reissue` | Re-analyzes and resends the previous batch | Yes | Yes |

See [the deployment reference](github-actions.en.md) for details.
## First preview and digest language

To preview immediately, select `allow_peak` under Run workflow. This permits peak-hour model calls for this run and may increase costs. Select it for the first `all` run as well if immediate delivery is needed; scheduled settings stay unchanged.

Set the repository variable `DIGEST_LANGUAGE` to `zh` (default) or `en`. Leave `DIGEST_TITLE` empty to use the language-specific default title; custom titles are used as written. Complete pending batches before switching languages. Neither `publish` nor `resend_bot` translates saved digests.

See the [English sample](../examples/digest-full.en.md) or [Chinese sample](../examples/digest-full.zh.md) without configuring credentials.
