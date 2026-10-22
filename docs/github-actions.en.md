# GitHub Actions Deployment Reference

This page is the detailed reference behind [GitHub Actions in 5 steps](quickstart.en.md). It covers secrets, variables, operations, state, costs, and recovery.

For pricing-window and schedule internals, see the scheduling reference (Simplified Chinese). For failures, see [Troubleshooting](troubleshooting.en.md).

## 1. Secrets

Store them under **Settings → Environments → daily-paper-radar → Environment secrets**, or under **Settings → Secrets and variables → Actions → Secrets**. Pick one location; environment secrets take precedence when names collide. Repository secrets alone are sufficient, so creating the environment is optional.

| Name | Value |
| --- | --- |
| `LLM_BASE_URL` | Publicly reachable model API base URL, or a supported full endpoint |
| `LLM_API_KEY` | The provider's real API key |
| `LLM_MODEL_NAME` | A model identifier the provider supports |
| `FEISHU_WEBHOOK` | Webhook of a custom bot in the target group |
| `FEISHU_SECRET` | Only when the bot enables signature verification |
| `FEISHU_APP_ID`, `FEISHU_APP_SECRET` | Only for Feishu document archiving |
| `FEISHU_DOC_ID` | Document URL or ID; may also be a repository Variable |

Both OpenAI-compatible and Anthropic-native APIs work. For a self-hosted Anthropic gateway, use the full `/messages` URL; for an OpenAI-compatible gateway, the full `/chat/completions` URL is also accepted. The endpoint must be reachable from GitHub-hosted runners.

Never put real values in workflows, the README, or chat messages. `.env` is not needed in the cloud.

## 2. Variables

Set these under **Settings → Secrets and variables → Actions → Variables**. Keep `DAILY_ENABLED` at repository level: it must be readable before the job enters the environment.

`DAILY_ENABLED` accepts only the lowercase string `true`; `True`, `TRUE`, `yes`, and `1` do not enable the schedule. `PAPER_KEYWORDS` splits on the ASCII comma `,`; a full-width comma `，` becomes part of the keyword. When `ARXIV_ENABLED=true`, keywords are required.

| Name | Required | Value |
| --- | --- | --- |
| `PAPER_KEYWORDS` | Recommended | Comma-separated English keywords for the topic you follow |
| `PAPER_FOCUS` | Recommended | A research direction |
| `PAPER_PREFERENCES` | Optional | Reading preferences |
| `DIGEST_TITLE` | Optional | Message title prefix |
| `DAILY_ENABLED` | Required for schedules | `true` enables scheduled runs; `false` or unset disables them |

Source and cost controls (defaults shown):

| Name | Default | Effect |
| --- | --- | --- |
| `HF_ENABLED` | `true` | Enable Hugging Face Daily Papers |
| `HF_LOOKBACK_DAYS` | `3` | Look-back window, 1–14 |
| `HF_MIN_UPVOTES` | `0` | Minimum community upvotes |
| `HF_MAX_PAPERS` | `20` | Candidate cap after removing delivered papers |
| `ARXIV_ENABLED` | `false` | Enable arXiv keyword candidates |
| `ARXIV_CATEGORIES` | `cs.AI,cs.CL,cs.LG` | arXiv categories |
| `PAPER_METADATA_ENABLED` | `true` | Fetch author affiliations and code links |
| `MAX_DETAILED_PAPERS` | `10` | Papers expanded in the digest, 1–20 |
| `MAX_LOW_PAPERS` | `5` | Low-relevance links kept, 0–20 |
| `LLM_CONCURRENCY` | `4` | API concurrency, 1–16 |
| `LLM_MAX_PAPERS` | `100` | Hard cap on analyzed papers |
| `LLM_TIMEOUT_SECONDS` | `60` | Per-request timeout, up to 600 |
| `LLM_OFFPEAK_ONLY` | `true` | Analyze only inside off-peak windows; set `false` to allow peak-priced calls |

Optional source screening: `SOURCE_GATE_ENABLED`, `MAX_QS_RANK`, `UNKNOWN_INSTITUTION_POLICY`, `CODE_POLICY`, `PDF_AFFILIATION_FALLBACK`, `MAX_METADATA_CANDIDATES`. See the [source screening guide](source-screening.md) (Simplified Chinese).

## 3. Manual operations

Open **Actions → 每日论文推送 → Run workflow** on the default branch.

| Operation | Behavior | Model call | Feishu message |
| --- | --- | --- | --- |
| `tick` | Resume the scheduled process using Beijing time and saved progress | Conditional | Conditional |
| `check` | Validate configuration without network or model calls | No | No |
| `preview` | Build an isolated preview artifact | Yes | No |
| `analyze` | Build and store a pending digest | Yes | No |
| `publish` | Deliver a pending digest; never generates one | No | Yes |
| `all` | Build and deliver, or resume an unfinished batch | Yes | Yes |
| `resend_bot` | Resend the last digest to the configured bot | No | Yes |
| `reissue` | Re-analyze and resend the previous batch | Yes | Yes |

`allow_peak` allows peak-priced model calls **for that run only**. Scheduled runs never enable it.

## 4. Schedule and timing

The unified workflow uses explicit UTC cron expressions and decides analysis, waiting, or delivery in Beijing time:

| UTC cron | Beijing time | Purpose |
| --- | --- | --- |
| `10,25,40,55 0-3 * * *` | 08:10–11:55, every 15 min | Resume missing analysis or delivery |
| `30 1 * * *` | 09:30 | Main delivery check |
| `17 4,10 * * *` | 12:17, 18:17 | Recovery checks in allowed windows |

With the default off-peak protection, analysis starts at 08:10–08:50 Beijing time during US daylight saving, and from 12:17 during US standard time (or from 09:10 with `ARXIV_FRESHNESS_PRIORITY=true`). The delivery target is 09:30 all year, once a digest exists. GitHub schedules are best-effort and may be late or dropped.

To change the target time, update both `PUBLISH_TIME_BEIJING` and the UTC cron entries in `.github/workflows/daily.yml`. Changing only the variable does not move the GitHub trigger.

## 5. Off-peak protection

`LLM_OFFPEAK_ONLY` defaults to `true`: scheduled analysis, PDF affiliation extraction, and recovery calls run only inside the configured off-peak windows, so the default trades some punctuality for lower token cost. GitHub schedules are best-effort anyway, which makes that trade worth taking: during US daylight saving the digest usually goes out around 09:30, while during US standard time the first window is 12:00 and the 12:17 check analyzes and delivers.

- **Keep the default** when you want the lowest model cost.
- **Set `LLM_OFFPEAK_ONLY=false`** to allow peak-priced calls and prioritize timeliness all year; `PUBLISH_TIME_BEIJING` still controls the earliest automatic delivery of a prepared digest.
- **Set `ARXIV_FRESHNESS_PRIORITY=true`** to keep only the winter morning exception: analysis may run from 09:10 in the 09:00–10:30 window at peak prices, so the winter digest can still arrive at 09:30.

Related variables: `LLM_BILLING_TIMEZONE`, `LLM_PEAK_WINDOWS`, `LLM_PEAK_WEEKDAYS`, `LLM_OFFPEAK_HOLIDAYS`, `LLM_PEAK_GUARD_MINUTES`, `WINTER_PEAK_UNTIL`, `MAX_DIGEST_AGE_HOURS`. Full table and trade-offs: [scheduling reference](scheduling.md) (Simplified Chinese).

A prepared digest can always be delivered during peak hours without a model call.

## 6. Feishu document archive

Add `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, and `FEISHU_DOC_ID`. A group webhook cannot edit documents; archiving requires a Feishu custom app with edit access to the target document.

Setup steps: [document archive guide](feishu-archive.md) (Simplified Chinese). The workflow appends the full digest; it does not erase existing content or recreate a deleted document.

## 7. State, cost, and failure handling

- Deduplication, unfinished batches, per-paper analysis caches, and delivery receipts live in the `radar-state` artifact with 90-day retention.
- State never enters Git. It contains no `.env` or credentials, but paper titles and summaries can reflect your interests; public-repository artifacts are not private storage.
- A failed run can be resumed by the next run. Channels already delivered are skipped on retry.
- If the message was sent but state upload failed, or the runner was cancelled, duplicates are still possible. Exactly-once delivery is not guaranteed.
- Keep the newest `radar-state` during normal operation. If the newest artifact has expired, the run stops to avoid resends. To start fresh, delete every `radar-state` artifact as described in [State artifact expired](troubleshooting.en.md#state-artifact-expired); recent papers may be delivered again.
- While an unfinished batch exists, restore the original variables before changing topics.
- GitHub-hosted runner minutes and artifact storage follow your plan and billing settings; model usage is billed separately by your provider.

## 8. When configuration looks complete but the run reports missing values

- Confirm the environment name is exactly `daily-paper-radar`, and check its deployment branch rules.
- If the environment requires reviewers, unattended scheduled runs will wait for approval.
- After changing workflow code, start a new run from the latest default branch. **Re-run jobs** uses the old commit and may still lack the environment binding. Updating secrets alone is the case where re-running an old job is fine.

## 9. Resending

- **Changed groups**: update `FEISHU_WEBHOOK` and `FEISHU_SECRET`, then run `resend_bot`. This resends the last digest without a model call or document append.
- **Changed layout**: run `reissue` to re-analyze and resend the previous batch. This incurs model charges and new messages.
- If a resend fails, do not run `reissue` again. Use `all` to resume unfinished analysis (per-paper caches are reused), or `publish` when analysis is complete and only delivery failed.
- If the archive document was deleted, restore it from the recycle bin or create a new one, grant the app edit access, and update `FEISHU_DOC_ID`. The program never creates or deletes documents on its own.
## 日报语言

在仓库 Variables 中设置 `DIGEST_LANGUAGE`：`zh` 为中文（默认），`en` 为英文。输出包括模型分析、阅读建议和卡片固定文案。自定义 `DIGEST_TITLE` 及模板不自动翻译；存在待发批次时请先完成，再切换语言。
