"""本地 AI 热点日报 agent 包。

__init__.py 的作用：
1. 告诉 Python：ai_report_agent 这个文件夹是一个可以 import 的包。
2. 让外部代码可以写 `import ai_report_agent`。

这个文件目前只放说明，不写业务逻辑。
真正的功能在 agent.py、config.py、sources.py、database.py、embeddings.py、feedback.py 等模块中。
Version 7 增加了 feedback_loop.py，用于保存真实事件反馈并影响下次评分。
"""
