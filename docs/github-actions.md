# GitHub 云端每日推送

电脑关机也能运行。统一定时工作流按北京时间检查进度：低峰保护默认开启，夏令时在 08:10 起分析、通常 09:30 推送；冬令时首轮低峰分析在 12:17 之后（开启 `ARXIV_FRESHNESS_PRIORITY` 可回到 09:10）。上午多次检查可恢复漏跑的分析，12:17、18:17 继续补查；已生成日报的投递不调用模型。日常只需维护仓库设置，不需要打开 Claude Code 或 Codex。时区换算、按时优先与配置表见[调度与省钱配置](scheduling.md)。

> **第一次使用？** 先按 [GitHub Actions 5 步跑通](quickstart.md) 完成 Fork、启用 Actions、填 Secrets、预览和首次推送，再回本文查完整参数。遇到失败先看 [常见问题与排错](troubleshooting.md)。

## 0. 前置步骤

Fork 后启用 Actions、填写 Secrets 与 Variables、获取飞书 Webhook 的完整步骤，见 [GitHub Actions 5 步跑通](quickstart.md)。本页只列完整参数和运行机制。

手动运行 `workflow_dispatch` 时必须选择默认分支；工作流只对默认分支生效。

## 1. 填模型与飞书 Secrets

支持两种存放位置，任选一种，无需重复填写：

- **Repository secrets**：打开 **Settings → Secrets and variables → Actions → Secrets → New repository secret**。这是最简单的做法，**不需要先创建环境**。
- **Environment secrets**：打开 **Settings → Environments → daily-paper-radar → Add environment secret**。工作流已绑定 `daily-paper-radar` 环境；环境名必须一致。需要按环境隔离凭据或设置审批规则时再用这种方式。

若两处存在同名 Secret，环境中的值优先。逐项填写：

| 名称 | 填什么 |
| --- | --- |
| `LLM_BASE_URL` | 公网可访问的模型 API 地址 |
| `LLM_API_KEY` | 该服务的真实调用密钥 |
| `LLM_MODEL_NAME` | 该服务支持的模型名称 |
| `FEISHU_WEBHOOK` | 目标飞书群内自定义机器人的 Webhook 地址 |
| `FEISHU_SECRET` | 仅机器人开启签名校验时填写，否则不创建 |

OpenAI 兼容接口和 Anthropic 原生接口均可使用。自建 Anthropic 网关请填完整 `/messages` 地址；OpenAI 网关可填完整 `/chat/completions` 地址。公网 API 需能被 GitHub 托管 runner 访问，并支持对应协议。

Webhook 获取、关键词校验和 IP 白名单的处理见[快速开始](quickstart.md#怎么拿到飞书-webhook)。群名本身不能定位推送目标；更换群时修改 `FEISHU_WEBHOOK`，同一个群改名通常可以沿用原机器人。

不要把真实参数写进 workflow、README 或聊天消息；不需要将 `.env` 上传到 GitHub。Secrets 只在执行相关步骤时注入环境变量。[GitHub Secrets 官方说明](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)。

## 2. 填关注主题 Variables

打开 **Settings → Secrets and variables → Actions → Variables → New repository variable**。这些 Variables 保持仓库级，尤其 `DAILY_ENABLED` 必须在任务进入环境前可读取：

| 名称 | 填什么 | 是否必填 |
| --- | --- | --- |
| `PAPER_KEYWORDS` | 你关注的主题词，英文，用英文逗号分隔，例如 `reasoning, agent, evaluation` | 建议填写 |
| `PAPER_FOCUS` | 研究方向，例如“大模型推理与智能体评估” | 建议填写 |
| `PAPER_PREFERENCES` | 阅读偏好，例如“优先有代码和对比实验的论文” | 选填 |
| `DIGEST_TITLE` | 消息标题前缀，例如“论文讨论组日报”，不影响实际群目标 | 选填 |
| `DAILY_ENABLED` | 预览完成后填写 `true` 开启定时；`false` 或未填写则关闭定时 | 开启定时时必填 |

> `DAILY_ENABLED` 必须放在仓库级 Variables。放到环境级不会生效：工作流在进入环境之前就会判断它，任务会一直显示 skipped。
>
> 值只认小写字符串 `true`；`True`、`TRUE`、`yes`、`1` 都不会启用定时。
>
> `PAPER_KEYWORDS` 用英文逗号 `,` 分隔；中文逗号 `，` 会成为关键词内容的一部分。启用 `ARXIV_ENABLED=true` 时必须填写关键词。

**这一步定义你的订阅。** 关键词和方向是 LLM 判断相关性的目标，不是标题字面搜索；HF 与 arXiv 的候选都会按这个主题打分排序，两项一起填更聚焦。三项都不填时才退回通用精选。Variables 不是秘密存储，不要填写密钥或私人研究计划。

低峰保护默认开启（`LLM_OFFPEAK_ONLY=true`）：定时分析只在 `LLM_PEAK_WINDOWS` 之外调用模型，按服务商的分时价格控制费用。夏令时通常 09:30 送达；冬令时首轮分析等到 12:17。设为 `false` 改为全年按时优先，详见 [调度与省钱](scheduling.md)。

默认从 HF 最近 3 天精选中排除已推送论文，再选票数最高的最多 20 篇新候选，让 LLM 判断相关性并总结；最多详细展开 10 篇，低相关论文仅列标题链接。HF 精选不保证覆盖每个细分方向。需要当天 arXiv 的关键词候选时，将仓库 Variable `ARXIV_ENABLED` 设置为 `true`。其他数量与来源配置见 [完整变量表](scheduling.md)。

## 3. 手动预览，然后开启每日推送

1. 打开 **Actions → 每日论文推送 → Run workflow**，使用默认分支，操作选择 `preview`。低峰保护默认开启，预览也需要处于允许的模型调用时段；需要立即测试时勾选仅本次允许高峰调用。
2. 成功后在运行页面 **Artifacts → paper-preview** 下载预览包：`preview.md` 是完整日报，`preview-feishu.md` 是默认飞书精简正文，`preview-feishu.json` 是对应卡片结构，可用于飞书卡片调试。预览会调用 LLM、产生模型费用，但不发飞书、不修改去重记录。
3. 确认模型总结符合预期后，把 Variable `DAILY_ENABLED` 设置成 `true`，统一定时工作流随即启用。
4. 手动操作：`analyze` 只生成正式待发批次；`publish` 只投递已生成批次，绝不补调 LLM；`all` 立即生成并发送；`check` 只验证配置，不访问论文或模型。无新增论文时默认跳过群消息，不发送空日报。

不要同时启用本机定时器；本地与云端不共享去重记录，可能重复发送。云端每次开始都会恢复上次状态，同一仓库的定时和手动任务串行执行。

定时检查统一在 `.github/workflows/daily.yml`，cron使用UTC；共用执行逻辑在 `paper-job.yml`，`cloud_run.py tick`按北京时间决定分析、等待或投递。手动 `analyze` 入口也由 `daily.yml` 的 `workflow_dispatch` 提供。成功投递后持久化当天完成标记，后续检查跳过；显式手动 `all`、`reissue` 不受当天标记限制。修改目标时间时，同时改 `PUBLISH_TIME_BEIJING` 与UTC cron。GitHub定时任务可能延迟或丢弃；公开仓库连续60天无活动可能停用定时任务。[GitHub定时任务说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。

## 参数已填写但任务仍报缺失

先确认 Secrets 放在哪一层：使用仓库级 Secrets 时不需要创建环境；使用环境级 Secrets 时，环境名称必须为 `daily-paper-radar`，并查看环境的部署分支规则是否允许默认分支。如果设置了必需审核人，运行会等待人工批准。定时无人值守时，请使用符合你审批要求的环境配置。

定时任务显示 skipped 时，优先检查 `DAILY_ENABLED` 是否为仓库级 `true`、是否在默认分支运行、fork 后是否启用了 Actions。更多现象与处理见 [常见问题与排错](troubleshooting.md)。

修复工作流代码后，要在 **Actions → 每日论文推送 → Run workflow** 基于最新默认分支发起新任务。旧任务的 **Re-run jobs** 使用旧提交，可能仍缺少环境绑定；只更新 Secrets、未改代码时才直接重跑旧任务。

## 飞书群每天看到什么

需要长期留存时，可同时把完整日报追加到同一篇飞书文档，按日期组织。详见 **[创建归档文档、获取应用凭据与授权](feishu-archive.md)**。未配置文档时仍只推群。

- 顶部区分“候选数量”与相关性；🔥 表示主题相关程度，不代表论文质量。
- 中高相关论文逐篇编号并以分隔线区分。标题为 `年月日-会议/期刊-一作机构中文简称-核心贡献`，日期是北京时间日报收录日；缺失的会议或机构直接省略。群内保留摘要、启发、局限及阅读建议；文档完整版还展示模型提供的证据说明。
- 一作机构从 arXiv HTML 中与第一位作者明确绑定的机构字段提取，来源链接保留在批次数据中；标题使用中文简称，遇到 HTML 不可用或机构对应不明则省略。不把任意合作者或文中提及的单位当成一作机构。`paper_metadata.enabled` 控制此补充抓取，默认开启；与旧的启发式 `resolve_orgs` 不同。
- 展示 HF 关联或论文摘要中提供的 GitHub/GitLab 仓库链接；有仓库不等于已核验开源许可证或可复现。没有发现链接不等于未开源。
- 开头显示本批次实际调用时记录的模型名称（API 模式对应 `LLM_MODEL_NAME`），不是重新读取当前设置去覆盖历史批次。旧数据未记录时会明确说明。
- 低相关论文默认最多保留 5 篇标题链接供人工复查（`MAX_LOW_PAPERS` 可配置），不声称实现交互式折叠。HF 精选加候选数量上限并不能保证不漏论文；如需要更广覆盖，可开启 `sources.arxiv.enabled` 并填写合适的英文关键词。已推送论文不会占用当天 HF 新候选名额。

## 完整部署流程速查

**上传或 Fork 仓库 → 确认 Actions 可用 → 填 Secrets → 填仓库 Variables → 最新 main 手动预览 → 检查飞书预览 → 开启 `DAILY_ENABLED` → 每天查看群消息及失败通知。**

只需 GitHub 和公网 API，无需安装本地 skill、保持电脑开机或维持 CLI 登录。第一次正式投递仍需验证飞书机器人的签名、关键词及访问限制；预览成功只能证明抓取、模型和渲染链路成功。出现红色失败时，先打开失败步骤日志，修正配置后重试，不要只看顶部 `exit code 1`。

## 状态、费用与失败处理

- 去重列表、待完成批次、论文分析和投递记录保存在 `radar-state` artifact 中，申请保留 90 天；每次正式运行都会更新快照。实际保留期受仓库策略限制。[GitHub artifact 保留期说明](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/remove-workflow-artifacts)。
- 状态不进入 Git 提交，不包含 `.env`、配置文件和运行日志。但论文摘要可能体现关注方向；公开仓库的 Actions 产物不适合保存私人研究内容。
- 抓取、模型或发送失败时，任务显示失败；下一次正式运行会尝试恢复上次批次。成功发送的目标有投递记录，正常重试会跳过它们。消息已发送但状态上传失败、强制取消或 runner 中断时，仍可能重复投递，无法承诺严格只发送一次。
- 正常运行时保留最新 `radar-state`。最新 artifact 已过期时，程序会停止推送以避免重复；需要重新开始时，按 [状态 artifact 过期](troubleshooting.md#状态-artifact-过期) 删除全部 `radar-state`，最近论文可能会再次推送。
- 存在未完成批次时，不允许同时改变主题配置后继续旧批次。先恢复原 Variables 并重跑成功，再修改订阅方向。
- 可在运行页面查看失败步骤；调整 API、飞书 Secrets 后，选择 **Re-run jobs** 重试。不要把含密钥的错误原文粘贴到公开 issue。
- GitHub 托管 runner 用量和 artifact 存储受账户套餐、账单及预算约束；LLM API 另计费用。可在 GitHub 的 Billing 页面和模型服务商控制台设置预算，不能理解为永久免费。[GitHub Actions 计费说明](https://docs.github.com/en/billing/concepts/product-billing/github-actions)。

## 修改排版后重发上一批

仅需要重发时，在 **每日论文推送 → Run workflow** 中选择 `reissue`。它读取最近保留的论文批次，按最新提示词重新分析，重新发群并追加文档，因此会再次产生模型费用和消息；不会清空历史去重，也不会导致明天重复抓取这些论文。高峰时默认被拦截，确需立即测试可勾选仅本次允许高峰调用。

若重发过程中失败，不要再次选择 `reissue`：分析未完成选 `all` 继续（可复用成功单篇缓存）；已分析完成、仅投递失败选 `publish`，会跳过已成功渠道。存在未完成批次时程序禁止再次重建重发批次。

若只清空归档文档的正文，保留原文档链接即可。若删除了整篇文档，需要先从回收站恢复，或新建文档、授予应用编辑权限，并更新 GitHub 中 `FEISHU_DOC_ID`；程序不会自动新建或删除文档。`reissue` 会重新追加完整的本批日报，并非恢复全部历史归档。

## 更换群机器人后只重发消息

更新同一配置位置的 `FEISHU_WEBHOOK` 与 `FEISHU_SECRET` 后，选择 `resend_bot`。这个操作读取上一份已生成日报，保留原收录日期，只发到当前启用的飞书群机器人；不调用 LLM，不追加文档，不清空历史去重。多群配置会重发到全部启用的飞书机器人。

此操作是明确的手动重发，每执行一次都会发送一次。存在未完成批次时先用 `all` 或 `publish` 完成批次。注意环境 Secrets 优先于仓库 Secrets：如果之前在 `daily-paper-radar` 环境配置过机器人，应更新那里的值。

## 分析之前筛选来源

可开启 `SOURCE_GATE_ENABLED`，先核实一作机构，再应用 QS 前100与团队白名单；代码默认优先而非强制。PDF 首页回退、配置变量、名单维护和审计说明见 [来源筛选](source-screening.md)。

## 日报语言

在仓库 Variables 中设置 `DIGEST_LANGUAGE`：`zh` 为中文（默认），`en` 为英文。输出包括模型分析、阅读建议和卡片固定文案。自定义 `DIGEST_TITLE` 及模板不自动翻译；存在待发批次时请先完成，再切换语言。
