# 固定回归评估

`regression_cases.json` 存放固定、确定性的样例，用来检查 Agent 核心行为是否退化。

这些样例不会参与真实日报生成。它们是修改代码或 prompt 之后的回归安全网：

- 去重应该移除明显重复的新闻；
- 评分应该优先选择应用、产品、工作流相关内容；
- 本地 critic 规则应该发现硬性的元数据问题；
- 修订校验应该拒绝不完整的模型回复；
- critic 明确输出 `FAIL` 时应该触发修订。

运行方式：

```powershell
python catch_ai.py --eval-regression
```

命令会把 Markdown 和 JSON 报告写入 `data/eval/`。
