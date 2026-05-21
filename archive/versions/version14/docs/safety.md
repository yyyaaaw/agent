# 安全设计

本项目是本地 Agent，不处理生产写操作，但仍需要明确安全边界。

## 密钥安全

- `.env` 不进入版本控制。
- 仓库只保留 `.env.example`。
- `DEEPSEEK_API_KEY` 只从环境变量或 `.env` 读取。
- 文档和日志不应该记录完整 API Key。

## 文件写入边界

默认写入位置：

- `reports/`
- `data/raw/`
- `data/runs/`
- `data/traces/`
- `data/debug/`
- `data/eval/`
- `data/agent.sqlite3`
- `data/source_health.json`

Agent 不应主动写入项目外目录，除非用户显式修改配置路径。

## 网络边界

当前网络访问包括：

- 读取 `sources.json` 中配置的 RSS 或网页来源。
- 调用 DeepSeek Chat Completions API。
- 访问来源主页以自动发现 RSS/Atom feed。

第三方来源可能失败、重定向或返回异常内容，所以采集层会记录错误，并把来源健康状态写入 `data/source_health.json`。

## 模型输出安全

模型生成结果不是事实来源本身。项目通过以下机制降低风险：

- prompt 明确要求只基于给定材料。
- critic 检查无来源支撑事实。
- 本地硬规则检查日期、年份、未来日期和相对时间错误。
- 修订结果必须通过完整性校验，避免短输出覆盖完整报告。
- debug prompt 保存在本地，便于复盘模型到底看到了什么。

## 数据隐私

当前项目默认处理公开资讯源数据和用户本地偏好配置。

需要注意：

- `profile.json` 和 `feedback.json` 可能包含个人偏好。
- `data/debug/` 可能包含完整 prompt。
- `reports/` 可能包含模型生成的长期观察结论。
- 如果要公开仓库，应确认 `data/`、`reports/` 和 `.env` 都未被提交。

## 人工确认边界

以下情况建议人工复核：

- critic 返回 FAIL。
- 报告涉及法律、金融、医疗、安全事件等高风险结论。
- 来源错误数量明显升高。
- 事件压缩率异常高，可能发生过度合并。
- 自动修订被拒绝，说明模型输出结构不稳定。

## 版本归档安全

历史版本放在 `archive/versions/`。`.gitignore` 会忽略历史版本中的 `.env` 和 `data/`，避免把旧密钥或旧运行数据带入仓库。

