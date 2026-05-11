你是一个新闻编辑台的事件归并助手。下面是 embedding 粗聚类得到的候选事件。

请你判断哪些候选事件其实在讲同一个真实新闻事件，并把它们合并。
同时为每个合并后的事件重新生成一个中文事件标题，不要直接复制任何一条新闻标题。

判断标准：
1. 同一个公司/产品/政策/事故在同一时间段的同一进展，应合并为一个事件。
2. 官方发布、媒体跟进、案例报道、影响分析，只要核心事实相同，应合并。
3. 只是同一领域但主体或核心进展不同，不要合并。
4. 单条新闻也要保留为事件，但标题要概括“发生了什么”，不要照抄新闻标题。
5. 只基于给定材料，不要编造事实。

请只输出 JSON，不要输出 Markdown。格式：
{
  "events": [
    {
      "event_ids": ["event_1", "event_3"],
      "title": "概括后的中文事件标题",
      "summary": "1-2 句说明这个事件是什么，以及为什么这些新闻属于同一事件",
      "merge_reason": "简短说明合并依据；单事件可写：单独成事件"
    }
  ]
}

候选事件材料：
候选事件ID：event_1
粗聚类标题：Running Codex safely at OpenAI
来源：OpenAI Blog
类别：产品与模型
候选事件包含的新闻：
1. [OpenAI Blog｜产品与模型] Running Codex safely at OpenAI
   摘要：How OpenAI runs Codex securely with sandboxing, approvals, network policies, and agent-native telemetry to support safe and compliant coding agent adoption.
   链接：https://openai.com/index/running-codex-safely

---

候选事件ID：event_2
粗聚类标题：Parloa builds service agents customers want to talk to
来源：OpenAI Blog
类别：产品与模型
候选事件包含的新闻：
1. [OpenAI Blog｜产品与模型] Parloa builds service agents customers want to talk to
   摘要：Parloa leverages OpenAI models to power scalable, voice-driven AI customer service agents, enabling enterprises to design, simulate, and deploy reliable, real-time interactions.
   链接：https://openai.com/index/parloa

---

候选事件ID：event_3
粗聚类标题：From Hot Wheels to handling content: How brands are using Microsoft AI to be more productive and imaginative
来源：Microsoft AI Blog
类别：企业应用
候选事件包含的新闻：
1. [Microsoft AI Blog｜企业应用] From Hot Wheels to handling content: How brands are using Microsoft AI to be more productive and imaginative
   摘要：The post From Hot Wheels to handling content: How brands are using Microsoft AI to be more productive and imaginative appeared first on The AI Blog .
   链接：https://blogs.microsoft.com/ai/from-hot-wheels-to-handling-content-how-brands-are-using-microsoft-ai-to-be-more-productive-and-imaginative/

---

候选事件ID：event_4
粗聚类标题：Microsoft open sources its ‘farm of the future’ toolkit
来源：Microsoft AI Blog
类别：企业应用
候选事件包含的新闻：
1. [Microsoft AI Blog｜企业应用] Microsoft open sources its ‘farm of the future’ toolkit
   摘要：The post Microsoft open sources its ‘farm of the future’ toolkit appeared first on The AI Blog .
   链接：https://blogs.microsoft.com/ai/microsoft-open-sources-its-farm-of-the-future-toolkit/

---

候选事件ID：event_5
粗聚类标题：A conversation with Kevin Scott: What’s next in AI
来源：Microsoft AI Blog
类别：企业应用
候选事件包含的新闻：
1. [Microsoft AI Blog｜企业应用] A conversation with Kevin Scott: What’s next in AI
   摘要：The post A conversation with Kevin Scott: What’s next in AI appeared first on The AI Blog .
   链接：https://blogs.microsoft.com/ai/a-conversation-with-kevin-scott-whats-next-in-ai/

---

候选事件ID：event_6
粗聚类标题：How data and AI will transform contact centres for financial services
来源：Microsoft AI Blog
类别：企业应用
候选事件包含的新闻：
1. [Microsoft AI Blog｜企业应用] How data and AI will transform contact centres for financial services
   摘要：The post How data and AI will transform contact centres for financial services appeared first on The AI Blog .
   链接：https://cloudblogs.microsoft.com/industry-blog/en-gb/financial-services/2022/07/25/how-data-and-ai-will-transform-contact-centres-for-financial-services/

---

候选事件ID：event_7
粗聚类标题：AI-equipped drones study dolphins on the edge of extinction
来源：Microsoft AI Blog
类别：企业应用
候选事件包含的新闻：
1. [Microsoft AI Blog｜企业应用] AI-equipped drones study dolphins on the edge of extinction
   摘要：The post AI-equipped drones study dolphins on the edge of extinction appeared first on The AI Blog .
   链接：https://news.microsoft.com/apac/features/ai-drones-dolphins-maui63/

---

候选事件ID：event_8
粗聚类标题：Online math tutoring service uses AI to help boost students’ skills and confidence
来源：Microsoft AI Blog
类别：企业应用
候选事件包含的新闻：
1. [Microsoft AI Blog｜企业应用] Online math tutoring service uses AI to help boost students’ skills and confidence
   摘要：The post Online math tutoring service uses AI to help boost students’ skills and confidence appeared first on The AI Blog .
   链接：https://blogs.microsoft.com/ai/eedi-online-math-quiz/

---

候选事件ID：event_9
粗聚类标题：As AI Grows More Complex, Model Builders Rely on NVIDIA
来源：NVIDIA AI Blog
类别：企业应用
候选事件包含的新闻：
1. [NVIDIA AI Blog｜企业应用] As AI Grows More Complex, Model Builders Rely on NVIDIA
   摘要：Unveiling what it describes as the most capable model series yet for professional knowledge work, OpenAI launched GPT-5.2 in December. The model was trained and deployed on NVIDIA infrastructure, including NVIDIA Hopper 
   链接：https://blogs.nvidia.com/blog/leading-models-nvidia/

---

候选事件ID：event_10
粗聚类标题：AI agents that hack computers and replicate themselves, and they're getting better fast
来源：The Decoder
类别：应用与产品
候选事件包含的新闻：
1. [The Decoder｜应用与产品] AI agents that hack computers and replicate themselves, and they're getting better fast
   摘要：Palisade Research shows that AI agents can hack remote computers, copy themselves onto them, and form replication chains. In one year, the success rate jumped from 6 to 81 percent. The researchers expect remaining barrie
   链接：https://the-decoder.com/ai-agents-that-hack-computers-and-replicate-themselves-and-theyre-getting-better-fast/

---

候选事件ID：event_11
粗聚类标题：Introducing Trusted Contact in ChatGPT
来源：OpenAI Blog
类别：产品与模型
候选事件包含的新闻：
1. [OpenAI Blog｜产品与模型] Introducing Trusted Contact in ChatGPT
   摘要：Introducing Trusted Contact in ChatGPT, an optional safety feature that notifies someone you trust if serious self-harm concerns are detected.
   链接：https://openai.com/index/introducing-trusted-contact-in-chatgpt

---

候选事件ID：event_12
粗聚类标题：Applications Now Open for $60,000 NVIDIA Graduate Fellowship Awards
来源：NVIDIA AI Blog
类别：企业应用
候选事件包含的新闻：
1. [NVIDIA AI Blog｜企业应用] Applications Now Open for $60,000 NVIDIA Graduate Fellowship Awards
   摘要：Bringing together the world’s brightest minds and the latest accelerated computing technology leads to powerful breakthroughs that help tackle some of the biggest research problems. To foster such innovation, the NVIDIA 
   链接：https://blogs.nvidia.com/blog/applications-open-graduate-fellowship-awards-2025/

---

候选事件ID：event_13
粗聚类标题：The “people’s airline” and the enterprise AI gold rush
来源：TechCrunch AI
类别：应用与商业
候选事件包含的新闻：
1. [TechCrunch AI｜应用与商业] The “people’s airline” and the enterprise AI gold rush
   摘要：Everyone wants a piece of the enterprise AI pie, and this week, we saw a string of companies making their moves. From Anthropic and OpenAI announcing new joint ventures targeting enterprise AI deployment to SAP dropping 
   链接：https://techcrunch.com/podcast/the-peoples-airline-and-the-enterprise-ai-gold-rush/

---

候选事件ID：event_14
粗聚类标题：Scaling Trusted Access for Cyber with GPT-5.5 and GPT-5.5-Cyber
来源：OpenAI Blog
类别：产品与模型
候选事件包含的新闻：
1. [OpenAI Blog｜产品与模型] Scaling Trusted Access for Cyber with GPT-5.5 and GPT-5.5-Cyber
   摘要：OpenAI expands Trusted Access for Cyber with GPT-5.5 and GPT-5.5-Cyber, helping verified defenders accelerate vulnerability research and protect critical infrastructure.
   链接：https://openai.com/index/gpt-5-5-with-trusted-access-for-cyber

---

候选事件ID：event_15
粗聚类标题：Advancing voice intelligence with new models in the API
来源：OpenAI Blog
类别：产品与模型
候选事件包含的新闻：
1. [OpenAI Blog｜产品与模型] Advancing voice intelligence with new models in the API
   摘要：Explore new realtime voice models in the OpenAI API that can reason, translate, and transcribe speech, enabling more natural and intelligent voice experiences.
   链接：https://openai.com/index/advancing-voice-intelligence-with-new-models-in-the-api

---

候选事件ID：event_16
粗聚类标题：Testing ads in ChatGPT
来源：OpenAI Blog
类别：产品与模型
候选事件包含的新闻：
1. [OpenAI Blog｜产品与模型] Testing ads in ChatGPT
   摘要：OpenAI begins testing ads in ChatGPT to support free access, with clear labeling, answer independence, strong privacy protections, and user control.
   链接：https://openai.com/index/testing-ads-in-chatgpt

---

候选事件ID：event_17
粗聚类标题：Anthropic and OpenAI sit down with religious leaders to seek ethical advice
来源：The Decoder
类别：应用与产品
候选事件包含的新闻：
1. [The Decoder｜应用与产品] Anthropic and OpenAI sit down with religious leaders to seek ethical advice
   摘要：Anthropic and OpenAI are turning to religious leaders for help with AI ethics. At the first "Faith-AI Covenant" roundtable in New York, representatives from both companies met with faith leaders from various religions. C
   链接：https://the-decoder.com/anthropic-and-openai-sit-down-with-religious-leaders-to-seek-ethical-advice/

---

候选事件ID：event_18
粗聚类标题：ByteDance plans over $30 billion for AI expansion, bets big on Chinese chips
来源：The Decoder
类别：应用与产品
候选事件包含的新闻：
1. [The Decoder｜应用与产品] ByteDance plans over $30 billion for AI expansion, bets big on Chinese chips
   摘要：ByteDance is raising its planned AI spending for 2026 to over 200 billion yuan (roughly $30 billion), at least a 25 percent jump from earlier plans. The TikTok parent is increasingly turning to Chinese chips. Still, the 
   链接：https://the-decoder.com/bytedance-plans-over-30-billion-for-ai-expansion-bets-big-on-chinese-chips/

---

候选事件ID：event_19
粗聚类标题：METR says it can barely measure Claude Mythos, Palo Alto Networks warns of autonomous AI attackers
来源：The Decoder
类别：应用与产品
候选事件包含的新闻：
1. [The Decoder｜应用与产品] METR says it can barely measure Claude Mythos, Palo Alto Networks warns of autonomous AI attackers
   摘要：METR can barely measure Claude Mythos Preview with its current test suite. Only five out of 228 tasks cover the relevant capability range. Meanwhile, Palo Alto Networks reports that frontier models autonomously chain vul
   链接：https://the-decoder.com/metr-says-it-can-barely-measure-claude-mythos-palo-alto-networks-warns-of-autonomous-ai-attackers/

---

候选事件ID：event_20
粗聚类标题：GPT-5.5 costs 49 to 92 percent more than its predecessor, depending on the input length
来源：The Decoder
类别：应用与产品
候选事件包含的新闻：
1. [The Decoder｜应用与产品] GPT-5.5 costs 49 to 92 percent more than its predecessor, depending on the input length
   摘要：OpenAI doubled GPT-5.5's list price compared to GPT-5.4, claiming shorter responses would offset the increase. An OpenRouter analysis of real usage data tells a different story: actual costs rose 49 to 92 percent dependi
   链接：https://the-decoder.com/gpt-5-5-costs-49-to-92-percent-more-than-its-predecessor-depending-on-the-input-length/

---

候选事件ID：event_21
粗聚类标题：Researchers may have found a way to stop AI models from intentionally playing dumb during safety evaluations
来源：The Decoder
类别：应用与产品
候选事件包含的新闻：
1. [The Decoder｜应用与产品] Researchers may have found a way to stop AI models from intentionally playing dumb during safety evaluations
   摘要：A study by researchers from the MATS program, Redwood Research, the University of Oxford, and Anthropic examines a safety problem that grows more pressing as AI systems become more capable: "sandbagging," where a model d
   链接：https://the-decoder.com/researchers-may-have-found-a-way-to-stop-ai-models-from-intentionally-playing-dumb-during-safety-evaluations/

---

候选事件ID：event_22
粗聚类标题：NVIDIA Rubin Platform, Open Models, Autonomous Driving: NVIDIA Presents Blueprint for the Future at CES
来源：NVIDIA AI Blog
类别：企业应用
候选事件包含的新闻：
1. [NVIDIA AI Blog｜企业应用] NVIDIA Rubin Platform, Open Models, Autonomous Driving: NVIDIA Presents Blueprint for the Future at CES
   摘要：NVIDIA founder and CEO Jensen Huang took the stage at the Fontainebleau Las Vegas to open CES 2026, declaring that AI is scaling into every domain and every device. “Computing has been fundamentally reshaped as a result 
   链接：https://blogs.nvidia.com/blog/2026-ces-special-presentation/

---

候选事件ID：event_23
粗聚类标题：Reaching Across the Isles: UK-LLM Brings AI to UK Languages With NVIDIA Nemotron
来源：NVIDIA AI Blog
类别：企业应用
候选事件包含的新闻：
1. [NVIDIA AI Blog｜企业应用] Reaching Across the Isles: UK-LLM Brings AI to UK Languages With NVIDIA Nemotron
   摘要：Celtic languages — including Cornish, Irish, Scottish Gaelic and Welsh — are the U.K.’s oldest living languages. To empower their speakers, the UK-LLM sovereign AI initiative is building an AI model based on NVIDIA Nemot
   链接：https://blogs.nvidia.com/blog/uk-llm-nemotron/

---

候选事件ID：event_24
粗聚类标题：It’s the Humidity: How International Researchers in Poland, Deep Learning and NVIDIA GPUs Could Change the Forecast
来源：NVIDIA AI Blog
类别：企业应用
候选事件包含的新闻：
1. [NVIDIA AI Blog｜企业应用] It’s the Humidity: How International Researchers in Poland, Deep Learning and NVIDIA GPUs Could Change the Forecast
   摘要：For more than a century, meteorologists have chased storms with chalkboards, equations, and now, supercomputers. But for all the progress, they still stumble over one deceptively simple ingredient: water vapor. Humidity 
   链接：https://blogs.nvidia.com/blog/humidity/

---

候选事件ID：event_25
粗聚类标题：NVIDIA Research Shapes Physical AI
来源：NVIDIA AI Blog
类别：企业应用
候选事件包含的新闻：
1. [NVIDIA AI Blog｜企业应用] NVIDIA Research Shapes Physical AI
   摘要：AI and graphics research breakthroughs in neural rendering, 3D generation and world simulation power robotics, autonomous vehicles and content creation.
   链接：https://blogs.nvidia.com/blog/physical-ai-research-siggraph-2025/

---

候选事件ID：event_26
粗聚类标题：So you’ve heard these AI terms and nodded along; let’s fix that
来源：TechCrunch AI
类别：应用与商业
候选事件包含的新闻：
1. [TechCrunch AI｜应用与商业] So you’ve heard these AI terms and nodded along; let’s fix that
   摘要：The rise of AI has brought an avalanche of new terms and slang. Here is a glossary with definitions of some of the most important words and phrases you might encounter.
   链接：https://techcrunch.com/2026/05/09/artificial-intelligence-definition-glossary-hallucinations-guide-to-common-ai-terms/

---

候选事件ID：event_27
粗聚类标题：Nvidia has already committed $40B to equity AI deals this year
来源：TechCrunch AI
类别：应用与商业
候选事件包含的新闻：
1. [TechCrunch AI｜应用与商业] Nvidia has already committed $40B to equity AI deals this year
   摘要：Nvidia continues to be a big investor in the AI ecosystem.
   链接：https://techcrunch.com/2026/05/09/nvidia-has-already-committed-40b-to-equity-ai-deals-this-year/

---

候选事件ID：event_28
粗聚类标题：Laid-off Oracle workers tried to negotiate better severance. Oracle said no.
来源：TechCrunch AI
类别：应用与商业
候选事件包含的新闻：
1. [TechCrunch AI｜应用与商业] Laid-off Oracle workers tried to negotiate better severance. Oracle said no.
   摘要：Some found out they didn't qualify for WARN Act protections like two-months notice because the company had classified them as remote workers.
   链接：https://techcrunch.com/2026/05/08/laid-off-oracle-workers-tried-to-negotiate-better-severance-oracle-said-no/

---

候选事件ID：event_29
粗聚类标题：Intel’s comeback story is even wilder than it seems
来源：TechCrunch AI
类别：应用与商业
候选事件包含的新闻：
1. [TechCrunch AI｜应用与商业] Intel’s comeback story is even wilder than it seems
   摘要：Intel's stock has risen a stunning 490% over the past year, a bet by Wall Street that may be running well ahead of the company's actual turnaround.
   链接：https://techcrunch.com/2026/05/08/intels-comeback-story-is-even-wilder-than-it-seems/

---

候选事件ID：event_30
粗聚类标题：Cloudflare says AI made 1,100 jobs obsolete, even as revenue hit a record high
来源：TechCrunch AI
类别：应用与商业
候选事件包含的新闻：
1. [TechCrunch AI｜应用与商业] Cloudflare says AI made 1,100 jobs obsolete, even as revenue hit a record high
   摘要：Cloudflare announced its first large-scale layoff. CEO Matthew Prince says because of AI efficiency gains, the company doesn't need as many support roles.
   链接：https://techcrunch.com/2026/05/08/cloudflare-says-ai-made-1100-jobs-obsolete-even-as-revenue-hit-a-record-high/
