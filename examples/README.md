# 日报样例

这些样例根据 [Attention Is All You Need 的公开摘要](https://arxiv.org/abs/1706.03762) 整理，用于展示排版和中英文切换，**不是当天抓取结果、模型评测或真实飞书送达记录**。示例日期仅用于固定排版。

- [中文日报](digest-full.zh.md)
- [英文日报](digest-full.en.md)
- [中文飞书正文](digest-concise.zh.md)
- [英文飞书正文](digest-concise.en.md)

不需要模型密钥即可在本地重新生成预览：

```bash
python3 scripts/render_demo.py
python3 scripts/render_demo.py --language en
```

Windows 使用 `python`。结果位于 `state/demo/`，含完整日报、群聊正文和飞书卡片 JSON；不会联网、调用模型或发送消息。实际推送效果见 [项目首页](../README.zh-CN.md#日报长什么样)。

`summary_cn` 是为兼容旧数据保留的字段名；英文模式也使用此字段保存英文摘要，不要根据字段名判断实际语言。
