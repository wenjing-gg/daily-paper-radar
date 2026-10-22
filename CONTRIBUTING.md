# 参与贡献

欢迎修复问题、改进文档和增加有明确使用场景的功能。提交前先查已有 Issue，较大改动先说明问题、预期行为和兼容性影响。Issue 与 PR 可用中文或英文。文档入口见 [docs/README.md](docs/README.md)。

## 项目结构

| 路径 | 内容 |
| --- | --- |
| `SKILL.md` | 单 skill 安装入口；整个仓库就是 skill 目录，客户端交互流程也写在这里 |
| `scripts/` | 抓取、分析、渲染、投递与云端状态 |
| `config/` | 配置模板、QS 名单与团队白名单 |
| `tests/` | 离线回归测试，不需要真实密钥 |
| `docs/` | 部署、调度、排错与来源筛选 |
| `.github/workflows/` | 定时、手动分析、测试与发布工作流 |

## 开发与验证

1. Fork 后创建主题分支，安装 Python 3.10+。初始化个人配置，但不要提交生成文件。
2. 运行 `python -m unittest discover -s tests -v` 与 `python -m compileall -q scripts tests`。Windows 设置 `PYTHONUTF8=1`，或使用项目 PowerShell 入口。
3. 修改工作流后运行 `actionlint`；修改发布文件后运行 `python scripts/build_release.py` 并检查 ZIP 文件清单。
4. 测试使用模拟网络与运行时生成的数据，不使用真实密钥，不向实际群发消息。

## 提交与拉取请求

- 一项改动解决一个明确问题，说明修改前后行为、验证结果和兼容性影响。
- 用户可感知变化更新 CHANGELOG；README 的英文与中文入口保持一致。
- 不提交 `.env`、个人 profile、state、日志、编辑器历史、聊天截图里的凭据。
- 每次提交和推送前，对实际暂存索引导出的文件运行标准 Gitleaks 规则，使用 `--redact`；不能只扫描已知密钥或绕过告警。
- 发现真实凭据已提交时立即撤销/轮换并联系维护者处理历史，不强推改写他人分支。
- 无需签署额外 CLA；贡献内容遵循本仓库 MIT 许可证，保留第三方版权与许可证要求。

维护者以测试、行为正确性、可维护性和配置兼容性审核，不承诺固定响应期限。

## 发布与版本

### 版本策略

采用 `主版本.次版本.修订版本`：修复为修订版，新功能为次版本，不兼容配置变更为主版本；0.x 阶段仍需仔细阅读迁移说明。预发布可用 `0.2.0-rc.1`。版本号以根目录 `VERSION` 为准，标签使用 `v` 前缀，CHANGELOG 按版本列出变化。

- `main` 是开发分支，使用者优先使用正式 Release。
- CI 覆盖 Windows / macOS / Ubuntu 与 Python 3.10 / 3.12；支持 Python 3.10+。
- 基础脚本依赖标准库；PDF 机构识别依赖 `requirements.txt` 中的 pypdf；CLI 模式依赖相应客户端。
- Dependabot 每周检查依赖，不自动合并升级。

### 发布步骤

1. 修改 `VERSION` 与 CHANGELOG，确认中英文 README、配置与迁移说明一致。
2. 运行 `python -m unittest discover -s tests -v` 和 `actionlint .github/workflows/*.yml`。
3. 运行 `python scripts/build_release.py`，检查 `dist/daily-paper-radar-<版本>.zip` 与 `.zip.sha256`：包含双语 README、许可证和模板，不含个人配置、凭据、状态和日志。
4. 提交并推送 `main`。在 Actions 运行 **准备版本发布**，工作流会重新测试、构建 ZIP 并创建**草稿 Release**。
5. 检查草稿的目标提交、版本说明、ZIP 内容和 SHA-256，再由维护者在 GitHub 发布。发布前把 CHANGELOG 的「待发布」改为实际日期。
6. 正式版本发布后不移动标签、不替换同名资产；修复问题发布新修订版。

发布前对实际暂存内容运行 Gitleaks（`--redact`）。真实凭据曾泄露时，先吊销轮换，再处理历史。

### 升级与回滚

升级前备份 `.env`、`config/profile.json` 和 `state/`；云端下载最新 `radar-state` 作为恢复依据。只更新公开代码，对比 `config/_template.json` 后手工合并配置，初始化脚本不会覆盖已有文件。先预览验证，再恢复定时执行。

回滚时切换到此前正式标签并检查配置兼容性；不要清空 `seen.json` 或恢复陈旧投递回执，否则可能重复推送。发布涉及状态格式变化时，必须提供迁移和回滚步骤。

### 维护者发布前检查

- [ ] CI 全部通过，`VERSION`、CHANGELOG、README 与标签一致。
- [ ] 工作区与完整历史通过 Gitleaks 扫描。
- [ ] 发布包只含公开文件，不含 `.env`、`profile`、`state/`、`dist/`、日志和编辑器历史。
- [ ] Actions 历史 artifact 中没有私人研究内容；公开仓库的 artifact 对所有人可见。
- [ ] 分支保护和标签保护已启用，发布后不移动标签。
- [ ] 用第二个账号从 Release ZIP 按快速开始完整跑一遍。

### 扫描命令

先安装 Gitleaks，然后运行以下命令。使用默认标准规则，输出脱敏；不增加白名单或跳过告警。

```bash
python3 scripts/scan_public.py
python3 scripts/scan_public.py --staged
gitleaks git --redact --no-banner
```

第一条扫描公开发布文件，第二条扫描实际暂存的文件内容，第三条扫描本地 Git 历史。没有暂存文件不代表整个仓库已通过扫描。提交与推送前重新运行，不复用旧扫描结果。真实模型与飞书送达仍需单独验收，模拟接口测试不能替代真实运行。
