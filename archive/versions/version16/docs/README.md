# Documentation

这组文档用于把 Agent 从“能跑的脚本”说明成“可交付的工程项目”。

- [能力边界](capabilities.md)：这个 Agent 能做什么、不能做什么。
- [架构设计](architecture.md)：一次运行如何从资讯源走到报告和评估。
- [输入输出契约](io_contract.md)：配置、命令、数据文件和产物格式。
- [指标体系](metrics.md)：如何衡量完整性、可靠性和工程价值。
- [固定回归评估](../evals/README.md)：用固定样例检查核心规则是否退化。
- [安全设计](safety.md)：密钥、文件、网络、模型输出和人工确认边界。

Agent v16 还新增了 `ai_report_agent/skills.py`，用于把日报生成、评估、记忆检索、来源治理、反馈学习和 MCP 控制面整理成可发现、可规划的 skills。相关 CLI 契约见 [输入输出契约](io_contract.md)。
