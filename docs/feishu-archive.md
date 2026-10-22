# 把每日日报追加到飞书文档

配置后，同一次分析生成两份展示：**飞书群收到保留完整摘要的精简卡片，归档文档追加完整日报**。旧内容不覆盖，每天以日期标题分节，论文作为二级标题，可从文档目录跳转。文档写入不需要再次调用 LLM。

群机器人的 Webhook 只能用于消息推送，不能用它编辑文档。归档需要一个飞书企业自建应用，以及该应用对目标文档的编辑权限。

## 1. 创建归档文档

1. 在飞书进入 **云文档 → 新建 → 文档**，创建新版文档。
2. 命名为你喜欢的归档名称，例如“论文日报归档”。正文可以留空，或者先写一段用途说明。
3. 复制文档链接，支持 **`/docx/`** 新版文档，也支持 **`/wiki/`** 知识库中的新版文档。旧 `/docs/` 文档和表格不支持。
4. 将文档分享给讨论组成员阅读，便于以后在群里置顶文档链接。

## 2. 创建自建应用，取得 App ID / App Secret

1. 用文档所在组织的账户登录 [飞书开发者后台](https://open.feishu.cn/app)。
2. 选择 **创建企业自建应用**，填写名称，例如“论文日报归档助手”。如果当前账户不能创建，需要联系组织管理员。
3. 进入应用的 **凭证与基础信息**，找到 **App ID** 和 **App Secret**。这两个是归档应用凭据，不是群机器人的 Webhook 或签名密钥。
4. 在 **权限管理** 搜索云文档相关权限，申请新版文档读写权限 **`docx:document`**（控制台显示的“创建及编辑新版文档”等名称可能随版本调整）。以 [创建文档块接口](https://open.feishu.cn/document/server-docs/docs/docx-v1/document-block-children/create) 的权限要求为准，不需要通讯录等无关权限。
5. 在 **版本管理与发布** 创建版本并发布，按组织要求完成审批，使权限生效。可用范围要包含你用于归档的账户。

脚本会自动使用 App ID / App Secret 获取短期 `tenant_access_token`，不用手动复制或定期更换访问令牌。[飞书应用访问令牌说明](https://open.feishu.cn/document/server-docs/authentication-management/access-token/tenant_access_token_internal)。

使用知识库 `/wiki/` 链接时，还需申请获取知识空间节点的权限（如 `wiki:wiki:readonly`），并授予应用访问该知识库节点的权限。脚本会先解析节点对应的新版文档，再追加正文。[获取知识空间节点接口](https://open.feishu.cn/document/server-docs/docs/wiki-v2/space/get_node)。

## 3. 给应用编辑这篇文档的权限

打开归档文档右上角 **… → 添加文档应用**，搜索刚发布的应用并添加，授予编辑权限。若界面使用“应用/协作者”入口，按该入口添加应用。普通的“任何人可阅读”分享链接不等于应用有编辑权限。

找不到应用时，先检查：应用与文档是否在同一组织、应用是否已发布、可用范围及组织文档安全策略是否允许。如果组织限制该操作，需要管理员协助；不要通过开放文档给所有人来替代应用授权。

## 4. 在 GitHub 填三项配置

放在仓库级 Secrets 即可，不需要先创建环境；需要按环境隔离凭据时，也可以用现有的 `daily-paper-radar` 环境：

| 名称 | 放在哪里 | 填什么 |
| --- | --- | --- |
| `FEISHU_APP_ID` | Settings → Secrets and variables → Actions → Secrets（仓库级），或 Settings → Environments → daily-paper-radar → Environment secrets | 自建应用的 App ID |
| `FEISHU_APP_SECRET` | 同上 | 自建应用的 App Secret |
| `FEISHU_DOC_ID` | 同上作为 Secret，或放仓库 Actions **Variables** | 完整 `/docx/` 或 `/wiki/` 文档链接，或新版文档 ID；Secret 优先，知识库请填完整链接 |

使用环境级 Secrets 时，环境名必须是 `daily-paper-radar`；同名时环境级优先。

**先填两个应用 Secrets，完成文档授权，最后再填 `FEISHU_DOC_ID`。** 文档配置不为空就启用归档；Secret 和 Variable 两处都清空才会关闭归档，不影响原有群推送。密钥不要发到聊天中，也不要写进仓库文件。

本地运行时，可把这三项放到自己的 `.env`，并在 profile 的 sinks 数组追加：

```json
{
  "type": "feishu_doc",
  "enabled": true,
  "body": "full",
  "document_id_env": "FEISHU_DOC_ID",
  "app_id_env": "FEISHU_APP_ID",
  "app_secret_env": "FEISHU_APP_SECRET"
}
```

这是环境变量引用，不是在 JSON 中填写真实凭据。云端会自动生成此配置，无需修改 profile。

## 5. 验证与长期使用

打开 **Actions → 每日论文推送 → Run workflow**。操作选 `preview` 只生成预览，不验证文档写入权限。已有待发批次时选择 `publish`：任务会发群消息，并把同批完整日报追加到文档末尾；需要先生成时在允许的模型调用时段选择 `analyze`，或选 `all` 立即生成并发送。以后文档跟随定时推送一起更新，具体时间见 [调度配置](scheduling.md)。

如果当天的日报已经成功发送，新运行可能没有新论文；启用归档不会自动补存过去的日报，也不要通过删除去重记录来强制补发。已有预览可先手动复制到文档，后续新批次自动归档。

归档按段写入，成功段会记录回执；重试使用相同客户端幂等标识。群发送成功但文档失败时，后续重试会跳过已成功的群消息，继续文档。不要删除 `radar-state` 或在未完成批次中更换文档。网络响应丢失、状态丢失等极端情形仍可能重复，不能承诺永久严格一次写入。

一篇文档不能无限增长。积累较多后可按季度或年度新建文档，授权应用后更新 `FEISHU_DOC_ID`；旧文档继续保留供检索。具体文档大小、块数及 API 配额限制以飞书当前规则为准，接近上限时应分卷归档。
