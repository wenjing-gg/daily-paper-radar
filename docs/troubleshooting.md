# 常见问题与排错

先判断问题在哪一层：

| 现象 | 先看 |
| --- | --- |
| GitHub Actions 没有运行，或运行显示 skipped | [云端定时没有触发](#云端定时没有触发) |
| 运行失败，日志有报错 | [云端运行失败](#云端运行失败) |
| 运行成功，但飞书没收到消息 | [运行成功但没收到消息](#运行成功但没收到消息) |
| 本地脚本报错 | [本地运行问题](#本地运行问题) |
| 收到了重复消息或旧日报 | [重复推送与旧日报](#重复推送与旧日报) |

## 云端定时没有触发

### 运行显示 skipped，或当天没有新的运行记录

按顺序检查：

1. **`DAILY_ENABLED` 是否设为 `true`**。它必须是 **仓库级 Variable**：
   **Settings → Secrets and variables → Actions → Variables**。
   放到环境级 Variables 不会生效，因为工作流在进入环境之前就读取它。
2. **是否在默认分支运行**。工作流的条件是默认分支；从其他分支手动运行会被跳过。
3. **Fork 后是否启用了 Actions**。打开 **Actions** 标签，如果看到
   `Workflows aren't being run on this forked repository`，点击
   **I understand my workflows, go ahead and enable them**。
4. **公开仓库是否连续 60 天没有活动**。GitHub 可能停用定时工作流；打开 Actions 重新启用。
5. **仓库是否被归档或 Actions 被组织策略禁用**。查看 **Settings → Actions → General**。

### 有运行记录，但只跑了 `check` 或什么都没有做

定时触发使用 `tick` 操作。它可能因为以下原因提前退出，这是正常保护：

- 当天批次已完成：日志显示「当天批次已完成」；
- 还没到低峰分析窗口：夏令时 08:10 起；冬令时默认 12:17 起（开启 `ARXIV_FRESHNESS_PRIORITY` 时 09:10 起）；
- 处于低峰保护的高峰时段：日志会说明等待下一次检查；
- 已生成日报但还没到 `PUBLISH_TIME_BEIJING`（默认 09:30）：保留待发批次；
- 当天没有新论文：不发送空日报。

如果已经过了 09:30 仍没有日报，日志里出现 `::warning::已超过北京时间推送目标`，说明高峰保护阻止了分析。处理方式：

- 等下一个允许分析的检查（12:17 或 18:17）；
- 或手动运行 `analyze`，完成后再运行 `publish`；
- 或在确认费用可接受时，把 `LLM_OFFPEAK_ONLY`（默认 `true`）设为 `false`，让高峰也能分析。

### GitHub 定时本身延迟

GitHub 的 `schedule` 是尽力而为，可能延迟几十分钟，极端情况下丢失。项目通过多次检查提高恢复机会，但不能保证准点。

需要严格准点时：

- 改用本地常开电脑，见 [本地部署](local-deployment.md)；
- 或用外部调度器在目标时间调用 `workflow_dispatch`，并安全保存细粒度 PAT。

## 云端运行失败

### 提示缺少模型配置

日志出现：

```text
请在 .env 或环境变量中填写 LLM_BASE_URL 和 LLM_MODEL_NAME
```

检查 Secrets 名称是否完全一致：

- `LLM_BASE_URL`
- `LLM_API_KEY`
- `LLM_MODEL_NAME`

是否填在正确位置：

| 位置 | 能否被工作流读取 |
| --- | --- |
| Repository secrets | 能 |
| Environment secrets（环境名 `daily-paper-radar`） | 能，同名优先 |
| Variables | 不能当作密钥使用 |

环境名必须与工作流中的 `daily-paper-radar` 一致。如果环境设置了「必需审核人」，定时运行会等待人工批准；无人值守时请调整环境规则。

### 提示飞书 Webhook 未设置

```text
飞书群机器人的环境变量未设置
```

确认 `FEISHU_WEBHOOK` 已创建且非空。仓库级和环境级都要检查：如果之前只在环境级配置过，打开 **Settings → Environments → daily-paper-radar → Environment secrets** 查看该值；同名时环境级覆盖仓库级。

### 模型返回 401 / 403 / 404 / 429 / 超时

| 现象 | 常见原因 | 处理 |
| --- | --- | --- |
| 401 | Key 错误、过期、复制时带了空格 | 重新复制 Key，只填值本身 |
| 403 | Key 无权访问该模型或该地区 | 检查服务商权限与可用区域 |
| 404 | `LLM_BASE_URL` 路径不对，或模型名不存在 | 按 [自定义模型](advanced.md#自定义模型) 检查地址和模型名 |
| 429 | 并发过高或触发限流 | 把 `LLM_CONCURRENCY` 降到 `2` 或 `1` |
| 超时 | 接口无法被 GitHub runner 访问，或响应过慢 | 换公网可达的网关；或改用本地部署 |

GitHub 托管 runner 在境外。只允许中国大陆访问的模型接口可能一直超时，这不是密钥问题。用浏览器或本地 `curl` 能访问，不代表 GitHub runner 能访问。

### 飞书返回错误码

自定义机器人的安全校验失败会返回明确错误码：

| 错误码 | 含义 | 处理 |
| --- | --- | --- |
| 19001 | Webhook 地址或请求参数不正确 | 重新复制完整 Webhook，确认没有多余空格 |
| 19021 | 签名校验失败 | 检查 `FEISHU_SECRET` 是否与机器人一致；没有开启签名就不要填 |
| 19022 | 来源 IP 不在白名单 | 关闭 IP 白名单，或改用固定出口 IP |
| 19024 | 消息未命中关键词 | 关闭关键词校验，或把关键词设为日报里一定出现的词，例如 `论文` |
| 9499 | 请求体格式或长度不合法（Bad Request） | 检查卡片 JSON 结构与正文长度 |
| 11232 | 触发发送频率限制 | 降低发送频率，稍后重试；本项目每天只发一次，正常使用很少遇到 |

使用自建 runner 固定出口 IP 时，需要把 `.github/workflows/paper-job.yml` 的 `runs-on` 改成你的 runner 标签，并在 runner 上安装 Python 3.10+ 和依赖。仓库默认使用 `ubuntu-24.04`。

错误码含义以飞书官方[自定义机器人使用指南](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot)为准；服务端调整后以实际返回为准。

### 状态 artifact 过期

云端把去重和未完成批次保存在 `radar-state` artifact 中，保留 90 天。程序始终读取最新的 `radar-state`；最新状态过期时会停止推送并报「最新状态已过期」，此时直接重新运行仍会读到同一个过期 artifact。

处理：

1. 程序没有从本地备份导入状态的命令；已经下载的备份只用于保留记录，不会自动恢复；
2. 确认可以接受重新开始后，删除**所有** `radar-state` artifact，包括已过期的；
3. 重新运行 `all`，建立新的状态。

没有 artifact 时，下一次运行会从首次运行开始。本机安装并登录 `gh` 后，可以列出并逐个删除：

```bash
gh api "repos/OWNER/REPO/actions/artifacts?name=radar-state&per_page=100" --paginate \
  --jq '.artifacts[] | "\(.id) \(.created_at) expired=\(.expired)"'

# 对上面列出的每个 ID 执行：
gh api -X DELETE repos/OWNER/REPO/actions/artifacts/ARTIFACT_ID
```

重新开始会重新分析最近论文，可能重复推送已经发过的内容。需要重发时明确使用 `resend_bot`（只发群）或 `reissue`（重新分析并重发）。

### 配置改了之后任务报「订阅配置已变化」

存在未完成批次时，程序不允许在配置变化后继续旧批次。这里的配置指 `config/profile.actions.json` 的全部内容（sinks 除外）：关键词、方向、来源、数量、模型参数等任何变化都会触发。

处理顺序：

1. 把 Variables 恢复成上一批使用的配置；
2. 运行 `all` 或 `publish` 完成批次；
3. 再修改配置，下一批生效。

## 运行成功但没收到消息

先区分「任务成功」和「消息送达」：

- 绿色运行记录只代表工作流步骤没有抛错；
- `preview` 永远不发消息；
- 当天没有新论文时，默认不发送空日报；
- 高峰保护下，运行可能只做检查而不分析。

检查日志中是否出现：

```text
feishu_bot ok
feishu_doc ok
```

如果出现 `feishu_bot FAILED`，按上面的飞书错误码处理。如果没有出现 `feishu_bot`：

- 云端使用 `cloud_config.py` 生成的 `config/profile.actions.json`，其中 `feishu_bot` 默认启用；本地的 `config/profile.json` 不参与云端运行；
- 确认 `FEISHU_WEBHOOK` 已填写且非空；
- 确认当前操作会发送消息：`check` 只检查配置，`preview` 和 `analyze` 不发送，`publish`、`all`、`resend_bot` 才会投递。

手动验证：

1. 运行 `check`，确认配置通过；
2. 运行 `preview`，确认能生成日报；
3. 运行 `all`，确认真实投递；
4. 如果只需要重发上一份日报，运行 `resend_bot`（不调用模型）。

### `all` 只完成了一部分

- 分析已完成、只有投递失败：运行 `publish`，复用已生成批次，不调用模型；
- 分析未完成：再次运行 `all`，逐篇分析缓存会被复用；
- 不要用 `reissue` 恢复失败批次：它会重新分析并重发，产生额外费用和重复消息。

### `DAILY_ENABLED` 已设置，定时仍被跳过

工作流只认小写字符串 `true`，并且区分大小写。`True`、`TRUE`、`yes`、`1` 都不会启用定时。

### 关键词没有生效

`PAPER_KEYWORDS` 只按英文逗号 `,` 拆分。中文逗号 `，` 会成为关键词内容的一部分。改成英文逗号，例如 `reasoning, agent, evaluation`。

### 提示「启用 arXiv RSS 时 keywords 不能为空」或「至少启用一个论文来源」

- 设置 `ARXIV_ENABLED=true` 时，`PAPER_KEYWORDS` 必须非空；
- `HF_ENABLED=false` 且 `ARXIV_ENABLED=false` 会关闭全部来源，至少保留一个。

## 本地运行问题

### `python` 找不到，或版本低于 3.10

- macOS 使用 `python3`；
- Windows 安装 Python 时勾选 **Add python.exe to PATH**；
- 用 `python --version` / `python3 --version` 确认版本；
- 用虚拟环境时，确认 `python -m pip install -r requirements.txt` 安装在同一个环境。

### `.env` 格式错误

错误信息只显示行号，不显示内容。常见原因：

- 值里有 `#` 或空格，但没有加引号；
- 引号没有成对；
- 一行写了多个变量；
- 使用了 `$变量` 或命令替换（本项目不支持展开）。

正确写法：

```dotenv
LLM_BASE_URL=https://api.openai.com/v1
```

系统环境变量优先于 `.env`。如果改了 `.env` 不生效，检查系统里是否已有同名变量。

### 提示 `已有任务正在运行`

说明上一次运行还没结束，或锁文件残留：

- 等上一次运行结束；
- 确认没有 Python 进程后再重新运行；
- 不要在有进程运行时删除 `state/run.lock`。

### Windows 计划任务没有运行

- 默认任务只在**当前用户登录时**运行；注销后不运行；
- 检查 `Get-ScheduledTaskInfo -TaskName "daily-paper-radar"` 的上次结果和下次运行时间；
- 检查 `state/run.log`；
- 确认电脑没有休眠或断网；
- 需要注销后运行，按 [本地部署](local-deployment.md#注销后仍运行) 修改任务账户。

### macOS LaunchAgent 没有运行

- 检查 `launchctl print gui/$(id -u)/com.paperradar.daily`；
- 检查 `state/run.log`；
- macOS 隐私控制可能阻止访问项目目录，换到可访问目录或授予权限；
- 终端里的环境变量不会自动传给 LaunchAgent；使用 `.env` 时不需要额外注入。

### `--check` 通过，但正式运行失败

`--check` 只检查本地配置，不验证：

- 网络是否可达；
- 模型 Key 是否有效；
- CLI 是否已登录；
- 飞书机器人权限。

先运行 `--dry-run`，再正式运行。

## 重复推送与旧日报

可能原因：

- 消息已发送，但状态保存失败或运行被强制中断；
- 多个定时器同时运行（例如本地和云端都启用了）；
- 手动执行了 `resend_bot` 或 `reissue`；
- 恢复了旧状态或旧的 `radar-state`。

处理：

- 只保留一个定时来源：本地或云端；
- 不要在未完成批次中反复运行 `all`；
- 需要重发时明确使用 `resend_bot`（只发群）或 `reissue`（重新分析并重发）；
- 不要删除 `seen.json` 来「修复」重复问题。

## 报错信息怎么提供

提交 Issue 时提供：

- 运行环境：Windows / macOS / Linux / GitHub Actions，Python 版本；
- 失败阶段：抓取、模型、渲染还是投递；
- 脱敏后的日志片段；
- 是否使用 API 或 CLI 后端。

不要提供：

- `LLM_API_KEY`、`FEISHU_WEBHOOK`、`FEISHU_SECRET`、`FEISHU_APP_SECRET`；
- 完整 `.env` 或 `config/profile.json`；
- 含私人研究方向的完整日报或截图。

如果怀疑密钥已经泄露，先吊销/轮换，再处理日志和 Git 历史。
