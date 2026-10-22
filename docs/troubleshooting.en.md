# Troubleshooting

Identify the layer first:

| Symptom | Start here |
| --- | --- |
| No GitHub Actions run, or the run is skipped | [Scheduled runs did not start](#scheduled-runs-did-not-start) |
| A run failed with an error | [Cloud run failures](#cloud-run-failures) |
| The run succeeded but Feishu received nothing | [Run succeeded, no message](#run-succeeded-no-message) |
| A local script failed | [Local problems](#local-problems) |
| Duplicate or stale messages | [Duplicates and stale digests](#duplicates-and-stale-digests) |

## Scheduled runs did not start

### The run is skipped, or there is no run today

Check in order:

1. **Is `DAILY_ENABLED` set to `true`?** It must be a **repository variable** under **Settings → Secrets and variables → Actions → Variables**. An environment-level variable does not work, because the workflow reads it before entering the environment.
2. **Was the run started on the default branch?** The job condition targets the default branch; other branches are skipped.
3. **Did you enable Actions after forking?** Open the **Actions** tab. If you see `Workflows aren't being run on this forked repository`, click **I understand my workflows, go ahead and enable them**.
4. **Has a public repository been inactive for 60 days?** GitHub may disable schedules; re-enable them from the Actions tab.
5. **Is the repository archived, or did an organization policy disable Actions?** Check **Settings → Actions → General**.

### A run exists but only performed `check`, or exited early

Scheduled runs use the `tick` operation. Early exits are intentional safeguards:

- The day's batch already completed: the log says `当天批次已完成`;
- Before the off-peak analysis window: from 08:10 Beijing time during US daylight saving, and from 12:17 during US standard time (from 09:10 with `ARXIV_FRESHNESS_PRIORITY=true`);
- A peak-pricing window blocks the model call: the log says it will wait for the next check;
- A digest is ready but `PUBLISH_TIME_BEIJING` (default 09:30) has not arrived: the batch waits;
- There are no new papers: an empty digest is not sent.

If 09:30 has passed and the log shows `::warning::已超过北京时间推送目标`, peak protection blocked analysis. You can:

- wait for the next allowed check at 12:17 or 18:17;
- run `analyze` manually, then `publish`;
- set `LLM_OFFPEAK_ONLY=false` (default `true`) if you accept peak pricing.

### GitHub schedules are late

GitHub's `schedule` event is best-effort and can be delayed or dropped. Multiple checks improve recovery but cannot guarantee punctuality.

For strict timing:

- run locally on an always-on computer; see [Local deployment](local-deployment.en.md);
- or trigger `workflow_dispatch` from an external scheduler with a fine-grained PAT stored securely.

## Cloud run failures

### Missing model configuration

```text
请在 .env 或环境变量中填写 LLM_BASE_URL 和 LLM_MODEL_NAME
```

Verify the secret names exactly:

- `LLM_BASE_URL`
- `LLM_API_KEY`
- `LLM_MODEL_NAME`

Also verify the location:

| Location | Readable by the workflow |
| --- | --- |
| Repository secrets | Yes |
| Environment secrets for `daily-paper-radar` | Yes, and they take precedence |
| Variables | Not as secrets |

The environment name must match `daily-paper-radar`. If the environment requires reviewers, scheduled runs wait for approval; adjust the rules for unattended operation.

### Feishu webhook is missing

```text
飞书群机器人的环境变量未设置
```

Confirm `FEISHU_WEBHOOK` exists and is non-empty. Check both levels: if it was configured as an environment secret, open **Settings → Environments → daily-paper-radar → Environment secrets** and read that value; an environment secret overrides a repository secret with the same name.

### Model returns 401 / 403 / 404 / 429 / timeout

| Symptom | Common cause | Action |
| --- | --- | --- |
| 401 | Wrong, expired, or whitespace-padded key | Re-copy the key; store the value alone |
| 403 | No access to that model or region | Check provider permissions and regions |
| 404 | Wrong `LLM_BASE_URL` path or unknown model name | Follow [Custom models](advanced.md#自定义模型) |
| 429 | Too much concurrency or provider rate limiting | Lower `LLM_CONCURRENCY` to `2` or `1` |
| Timeout | Endpoint unreachable from GitHub runners, or too slow | Use a publicly reachable gateway, or deploy locally |

GitHub-hosted runners are outside mainland China. An endpoint that works in your browser may still time out from a runner. That is not a key problem.

### Feishu error codes

Custom-bot security checks return specific codes:

| Code | Meaning | Action |
| --- | --- | --- |
| 19001 | Incorrect webhook or request parameter | Re-copy the full webhook; check for stray spaces |
| 19021 | Signature verification failed | Check `FEISHU_SECRET`; leave it unset when signatures are off |
| 19022 | Source IP not allowlisted | Disable the IP allowlist, or use a fixed egress IP |
| 19024 | Message does not contain the keyword | Disable the keyword check, or use a word that always appears in the digest, such as `论文` |
| 9499 | Invalid request body format or length (Bad Request) | Check the card JSON structure and body length |
| 11232 | Sending rate limit | Send less often and retry later; this project sends once per day, so normal use rarely hits it |

To fix the egress IP with a self-hosted runner, change `runs-on` in `.github/workflows/paper-job.yml` to your runner label, and install Python 3.10+ and dependencies on that runner. The repository default is `ubuntu-24.04`.

Code meanings follow Feishu's official [custom bot guide](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot); use the actual response when the service changes.

### State artifact expired

Cloud state is stored in the `radar-state` artifact for 90 days. The program always reads the newest `radar-state`; when that artifact has expired, the workflow stops with "latest state expired". Re-running still reads the same expired artifact.

1. There is no command to import state from a local backup; a downloaded backup only preserves records and does not restore automatically;
2. Confirm that a fresh start is acceptable, then delete **all** `radar-state` artifacts, including expired ones;
3. Run `all` again to create new state.

With no artifact, the next run starts from the first run. If `gh` is installed and authenticated locally, list and delete them:

```bash
gh api "repos/OWNER/REPO/actions/artifacts?name=radar-state&per_page=100" --paginate \
  --jq '.artifacts[] | "\(.id) \(.created_at) expired=\(.expired)"'

# For each ID listed above:
gh api -X DELETE repos/OWNER/REPO/actions/artifacts/ARTIFACT_ID
```

A fresh start re-analyzes recent papers and may resend content already delivered. To resend deliberately, use `resend_bot` (group message only) or `reissue` (re-analyze and resend).

### "Subscription configuration changed" after an edit

While an unfinished batch exists, the program refuses to continue it under different settings. "Configuration" means the entire `config/profile.actions.json` except `sinks`: any change to keywords, focus, sources, counts, or model parameters triggers it.

1. Restore the variables used by the previous batch;
2. Finish the batch with `all` or `publish`;
3. Change the configuration again; it applies to the next batch.

## Run succeeded, no message

A green run only means the steps did not throw. It does not prove delivery:

- `preview` never sends;
- an empty digest is skipped;
- peak protection may result in a check-only run.

Look for these log lines:

```text
feishu_bot ok
feishu_doc ok
```

If you see `feishu_bot FAILED`, use the Feishu error-code guidance above. If `feishu_bot` is absent:

- The cloud uses `config/profile.actions.json` generated by `cloud_config.py`, where `feishu_bot` is enabled by default; your local `config/profile.json` plays no part in cloud runs;
- Confirm `FEISHU_WEBHOOK` is set and non-empty;
- Confirm the operation sends messages: `check` validates only, `preview` and `analyze` never send, and `publish`, `all`, and `resend_bot` deliver.

Manual verification:

1. Run `check`.
2. Run `preview`.
3. Run `all` for a real delivery.
4. To resend the last digest only, run `resend_bot` (no model call).

### `all` completed only part of the work

- Analysis finished, delivery failed: run `publish` to reuse the prepared batch without model calls;
- Analysis unfinished: run `all` again; per-paper analysis caches are reused;
- Do not use `reissue` to recover a failed batch: it re-analyzes and resends, adding cost and duplicate messages.

### `DAILY_ENABLED` is set, but scheduled runs are still skipped

The workflow accepts only the lowercase string `true`, case-sensitively. `True`, `TRUE`, `yes`, and `1` all leave schedules disabled.

### Keywords have no effect

`PAPER_KEYWORDS` splits on the ASCII comma `,` only. A full-width comma `，` becomes part of the keyword. Use `reasoning, agent, evaluation`.

### "keywords must not be empty when arXiv RSS is enabled" or "enable at least one paper source"

- With `ARXIV_ENABLED=true`, `PAPER_KEYWORDS` must be non-empty;
- `HF_ENABLED=false` together with `ARXIV_ENABLED=false` disables every source; keep at least one enabled.

## Local problems

### `python` not found or older than 3.10

- macOS uses `python3`;
- on Windows, enable **Add python.exe to PATH** during installation;
- check `python --version` / `python3 --version`;
- if using a virtual environment, install dependencies with that environment's `python -m pip`.

### `.env` parse error

The message shows a line number but hides the value. Common causes:

- `#` or spaces in an unquoted value;
- unmatched quotes;
- multiple variables on one line;
- `$VAR` or command substitution, which this project does not expand.

Correct form:

```dotenv
LLM_BASE_URL=https://api.openai.com/v1
```

Process environment variables override `.env`. If an edit has no effect, check for an existing variable in the OS environment.

### `已有任务正在运行`

A previous run is still active, or a lock file is stale:

- wait for the previous run;
- confirm no Python process is running before retrying;
- do not delete `state/run.lock` while a process is active.

### Windows task did not run

- The default task runs only while the current user is logged in; it does not run after sign-out;
- check `Get-ScheduledTaskInfo -TaskName "daily-paper-radar"`;
- read `state/run.log`;
- confirm the computer was awake and online;
- to run after sign-out, change the task account as described in [Local deployment](local-deployment.en.md#run-after-sign-out).

### macOS LaunchAgent did not run

- check `launchctl print gui/$(id -u)/com.paperradar.daily`;
- read `state/run.log`;
- macOS privacy controls may block the project directory; move it or grant access;
- terminal environment variables are not inherited by LaunchAgents; use `.env` (no extra injection needed).

### `--check` passes but a real run fails

`--check` does not verify network reachability, model keys, CLI login, or Feishu permissions. Run `--dry-run` before a real run.

## Duplicates and stale digests

Possible causes:

- the message was sent but state saving failed or the run was interrupted;
- two schedulers are active (local and cloud);
- `resend_bot` or `reissue` was run manually;
- old state or an old `radar-state` artifact was restored.

Actions:

- keep only one scheduler: local or cloud;
- avoid repeatedly running `all` while a batch is unfinished;
- use `resend_bot` (group message only) or `reissue` (re-analyze and resend) intentionally;
- do not delete `seen.json` to "fix" duplicates.

## What to include in a report

Include:

- environment: Windows / macOS / Linux / GitHub Actions, Python version;
- failing stage: collection, model, rendering, or delivery;
- redacted log excerpt;
- API or CLI backend.

Do not include:

- `LLM_API_KEY`, `FEISHU_WEBHOOK`, `FEISHU_SECRET`, `FEISHU_APP_SECRET`;
- the full `.env` or `config/profile.json`;
- full digests or screenshots containing private research interests.

If a credential may have leaked, revoke and rotate it first, then handle logs and Git history.
