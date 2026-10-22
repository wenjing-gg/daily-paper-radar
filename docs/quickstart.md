# 5 步跑通 GitHub Actions

本文只讲最短路径：**Fork 仓库 → 填 4 个 Secrets → 预览 → 首次推送 → 开启每天自动运行**。电脑关机也能跑，不需要安装本地 skill，不需要 Claude Code / Codex 登录。

完整参数表见 [GitHub 云端每日推送](github-actions.md)，定时与计费规则见 [错峰分析与定时推送](scheduling.md)，遇到问题先查 [常见问题与排错](troubleshooting.md)。

## 开始前准备

| 需要 | 说明 |
| --- | --- |
| GitHub 账号 | 公开仓库的 Actions 免费；私有仓库消耗账户额度。 |
| 一个可公网访问的模型 API | OpenAI 兼容接口或 Anthropic 原生接口均可。GitHub 托管 runner 在境外，接口需要能从境外访问；仅限中国大陆网络的地址会超时。 |
| 一个飞书群 | 能在群里添加「自定义机器人」。 |
| 3–5 分钟 | 首次预览需要等模型返回。 |

## 第 1 步：Fork 或复制仓库

- **Fork（推荐）**：打开仓库右上角 **Fork → Create fork**。之后可以随时从上游同步更新。
- **Use this template**：仓库启用 Template repository 后才会出现该按钮；适合想完全独立维护的仓库。入口在 **Use this template → Create a new repository**。

Fork 完成后，打开你自己仓库的 **Actions** 标签。GitHub 对 fork 默认禁用工作流，页面会提示启用：

> Workflows aren't being run on this forked repository.

点击 **I understand my workflows, go ahead and enable them**。如果看不到提示，说明工作流已启用，继续下一步。

> 定时任务也受这个开关控制。没有启用 Actions 时，第 5 步设置的定时不会运行。

## 第 2 步：填模型与飞书 Secrets

打开 **Settings → Secrets and variables → Actions → Secrets → New repository secret**，填写下面 4 个必填项：

| Secret | 填什么 | 示例 |
| --- | --- | --- |
| `LLM_BASE_URL` | 模型 API 地址 | `https://api.openai.com/v1`、`https://api.anthropic.com/v1`，或你的兼容网关地址 |
| `LLM_API_KEY` | 该服务的真实 API Key | 不要把 Key 发给任何人或写进仓库文件 |
| `LLM_MODEL_NAME` | 该服务支持的模型名 | 按服务商文档填写，不要照抄示例 |
| `FEISHU_WEBHOOK` | 飞书群自定义机器人的 Webhook | `https://open.feishu.cn/open-apis/bot/v2/hook/...` |

选填：

| Secret | 什么时候填 |
| --- | --- |
| `FEISHU_SECRET` | 飞书机器人开启了「签名校验」时填写；没有开启就不要创建。 |
| `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_DOC_ID` | 需要把完整日报追加到飞书文档时填写，见 [飞书文档归档](feishu-archive.md)。 |

也可以用 **Settings → Environments → daily-paper-radar → Environment secrets**。两种位置任选一种；同名时环境级优先。只使用仓库级 Secrets 时，**不需要先创建环境**。

### 怎么拿到飞书 Webhook

1. 打开目标飞书群，点右上角 **··· → 设置 → 群机器人**。
2. 点 **添加机器人 → 自定义机器人**，起一个名字（例如「论文日报」）。
3. 复制 **Webhook 地址**，填到 `FEISHU_WEBHOOK`。
4. 如果勾选了「签名校验」，复制密钥并填到 `FEISHU_SECRET`；否则不要创建这个 Secret。
5. 如果设置了「关键词」或「IP 白名单」，见下面的注意事项。

> **关键词校验**：机器人只允许包含指定关键词的消息。请关闭关键词校验，或把关键词设为日报里一定会出现的词，例如 `论文`。
>
> **IP 白名单**：GitHub 托管 runner 的出口 IP 不固定。请关闭 IP 白名单，或改用固定出口的代理。改用自建 runner 时，需要把 `.github/workflows/paper-job.yml` 的 `runs-on` 改成你的 runner 标签，并在 runner 上安装 Python 3.10+ 和依赖。
>
> 飞书群机器人只能发消息，不能编辑文档。文档归档需要另外创建企业自建应用，见 [飞书文档归档](feishu-archive.md)。

## 第 3 步：填你关注的主题 Variables

打开 **Settings → Secrets and variables → Actions → Variables → New repository variable**。

| Variable | 是否必填 | 填什么 |
| --- | --- | --- |
| `PAPER_KEYWORDS` | 建议填写 | 你关注的主题词，英文，用英文逗号分隔，例如 `reasoning, agent, evaluation` |
| `PAPER_FOCUS` | 建议填写 | 研究方向，例如「大模型推理与智能体评估」 |
| `PAPER_PREFERENCES` | 选填 | 阅读偏好，例如「优先有代码和对比实验的论文」 |
| `DIGEST_TITLE` | 选填 | 消息标题前缀，例如「论文讨论组日报」 |
| `DAILY_ENABLED` | **开启定时时必填** | 第一次先不填；第 5 步验证成功后再设为小写 `true` |

**这一步定义你的订阅。** 关键词和方向会作为 LLM 判断相关性的目标，不是标题字面搜索：HF 与 arXiv 的候选都会按这个主题打分排序，填得越具体，日报越贴近你关注的工作。`PAPER_KEYWORDS` 和 `PAPER_FOCUS` 一起填更聚焦；三项都留空时，才会退回到通用精选。Variables 不是秘密存储，不要填写密钥或私人研究计划。

> `PAPER_KEYWORDS` 用英文逗号 `,` 分隔；中文逗号 `，` 会成为关键词内容的一部分。
>
> `DAILY_ENABLED` 必须放在 **仓库级 Variables**，不要放在环境级。工作流在进入环境之前就会读取它；放到环境里会导致定时任务一直被跳过。
>
> `DAILY_ENABLED` 只认小写字符串 `true`。`True`、`yes`、`1` 都不会启用定时。
>
> **错峰调用（默认开启）**：`LLM_OFFPEAK_ONLY` 默认为 `true`，定时分析只在低峰窗口调用模型，避开高峰价格。GitHub 定时本来就不保证准点，因此默认优先省钱：夏令时通常在 09:30 左右送达；冬令时的第一轮分析落在高峰，会顺延到 12:17 之后。想按时优先，把 `LLM_OFFPEAK_ONLY` 设为 `false`；只想保留冬令时上午窗口，设 `ARXIV_FRESHNESS_PRIORITY=true`。

## 第 4 步：手动预览

1. 打开 **Actions → 每日论文推送 → Run workflow**。
2. 分支选择默认分支（通常是 `main`）。
3. 操作选择 `preview`，点击 **Run workflow**。
4. 等运行变成绿色后，打开这次运行，在页面底部 **Artifacts** 下载 **`paper-preview`**。

压缩包里：

| 文件 | 用途 |
| --- | --- |
| `preview.md` | 完整日报，最先看这个 |
| `preview-feishu.md` | 飞书群精简正文 |
| `preview-feishu.json` | 飞书卡片结构，用于排版调试 |

`preview` 会调用模型并产生费用，但**不会发飞书、不会修改去重记录**。如果任务失败，先看失败步骤的日志，再对照 [排错页](troubleshooting.md)。

## 第 5 步：首次真实推送并开启定时

1. 确认预览内容符合预期后，打开 **Actions → 每日论文推送 → Run workflow**。
2. 操作选择 `all`，点击 **Run workflow**。这次会**真实发送飞书消息**。
3. 在群里确认收到日报。运行日志里应出现 `feishu_bot ok`；如果配置了文档归档，还会出现 `feishu_doc ok`。
4. 回到 **Settings → Secrets and variables → Actions → Variables**，把 `DAILY_ENABLED` 设为 `true`。

完成后，定时工作流会自动运行。默认目标：

| 项目 | 北京时间 |
| --- | --- |
| 夏令时低峰分析窗口 | 08:10–08:50 |
| 冬令时默认分析时间 | 12:17 起（低峰）；`ARXIV_FRESHNESS_PRIORITY=true` 时 09:10 起 |
| 主推送目标 | 09:30（分析已完成时） |
| 检查频率 | 08:10–11:55 每 15 分钟；12:17、18:17 补查 |

已有日报时只投递、不重复调用模型；当天成功完成后，后续检查直接退出。

## 第二天怎么确认成功

1. 打开 **Actions → 每日论文推送**，确认当天有新的运行记录。
2. 打开运行日志，搜索 `定时检查`，核对日志里的 UTC 时间、北京时间和 `cron`。
3. 在飞书群确认收到当天日报。
4. 如果运行显示 **skipped**，通常是 `DAILY_ENABLED` 没有设为 `true`，或这次运行不在默认分支。

## 为什么有时不准时

GitHub 的 `schedule` 是尽力而为的：触发可能延迟几分钟到几十分钟，极端情况下会被丢弃。本项目通过「08:10–11:55 每 15 分钟检查 + 09:30 主触发 + 12:17/18:17 补查」提高送达机会，但**不能承诺 09:30 绝对送达**。

默认的谷时模式还会主动让分析等待低价时段：冬令时首轮分析在 12:17 之后，日报随之后移。这会延后送达时间，实际折扣取决于服务商；需要上午送达时，按第 3 步调整 `LLM_OFFPEAK_ONLY` 或 `ARXIV_FRESHNESS_PRIORITY`。

如果你必须严格准点，两个选择：

- **本地常开电脑**：用 Windows 任务计划程序或 macOS launchd 运行，见 [本地部署](local-deployment.md)。
- **外部定时触发**：用一台常开服务器或可信调度器，在 09:30 调用 GitHub 的 `workflow_dispatch` 接口。这需要创建一个细粒度 PAT，并把它保存在调度器一侧；不要把 PAT 写进仓库或公开文档。

## 常见操作速查

| 操作 | 会做什么 | 会调用模型吗 | 会发飞书吗 |
| --- | --- | --- | --- |
| `check` | 只检查配置 | 否 | 否 |
| `preview` | 生成预览包 | 是 | 否 |
| `analyze` | 生成待发日报 | 是 | 否 |
| `publish` | 投递已生成日报 | 否 | 是 |
| `all` | 生成并投递 | 是 | 是 |
| `resend_bot` | 只重发上一份日报 | 否 | 是 |
| `reissue` | 重新分析并重发上一批 | 是 | 是 |

更多操作说明见 [GitHub 云端每日推送](github-actions.md)。

## 首次预览与日报语言

想立即预览时，在 Run workflow 勾选 `allow_peak`，仅允许本次高峰模型调用，可能增加费用。首次 `all` 推送需要即时运行时同样勾选；无需修改定时的谷时设置。

仓库 Variables 的 `DIGEST_LANGUAGE` 可填 `zh` 或 `en`，默认 `zh`。`DIGEST_TITLE` 留空时标题跟随语言；填写后原样保留。若有待发批次，先完成该批次再切换语言；`publish` / `resend_bot` 不会重新生成英文。

无需密钥可先查看 [日报样例](../examples/README.md)。
