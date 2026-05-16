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
粗聚类标题：As AI Grows More Complex, Model Builders Rely on NVIDIA
来源：NVIDIA AI Blog, OpenAI Blog
类别：企业应用, 产品与模型
候选事件包含的新闻：
1. [NVIDIA AI Blog｜企业应用] As AI Grows More Complex, Model Builders Rely on NVIDIA
   摘要：Unveiling what it describes as the most capable model series yet for professional knowledge work, OpenAI launched GPT-5.2 in December. The model was trained and deployed on NVIDIA infrastructure, including NVIDIA Hopper 
   链接：https://blogs.nvidia.com/blog/leading-models-nvidia/
2. [NVIDIA AI Blog｜企业应用] Applications Now Open for $60,000 NVIDIA Graduate Fellowship Awards
   摘要：Bringing together the world’s brightest minds and the latest accelerated computing technology leads to powerful breakthroughs that help tackle some of the biggest research problems. To foster such innovation, the NVIDIA 
   链接：https://blogs.nvidia.com/blog/applications-open-graduate-fellowship-awards-2025/
3. [OpenAI Blog｜产品与模型] Building a safe, effective sandbox to enable Codex on Windows
   摘要：Learn how OpenAI built a secure sandbox for Codex on Windows, enabling safe, efficient coding agents with controlled file access and network restrictions.
   链接：https://openai.com/index/building-codex-windows-sandbox
4. [OpenAI Blog｜产品与模型] How NVIDIA engineers and researchers build with Codex
   摘要：Teams use Codex with GPT-5.5 to ship production systems and turn research ideas into runnable experiments.
   链接：https://openai.com/index/nvidia
5. [OpenAI Blog｜产品与模型] AutoScout24 scales engineering with AI-powered workflows
   摘要：Learn how AutoScout24 Group uses Codex and ChatGPT to speed development cycles, improve code quality, and expand AI adoption.
   链接：https://openai.com/index/autoscout24
6. [NVIDIA AI Blog｜企业应用] NVIDIA Research Shapes Physical AI
   摘要：AI and graphics research breakthroughs in neural rendering, 3D generation and world simulation power robotics, autonomous vehicles and content creation.
   链接：https://blogs.nvidia.com/blog/physical-ai-research-siggraph-2025/
7. [OpenAI Blog｜产品与模型] How finance teams use Codex
   摘要：See how finance teams can use Codex to build MBRs, reporting packs, variance bridges, model checks, and planning scenarios from real work inputs.
   链接：https://openai.com/academy/how-finance-teams-use-codex

---

候选事件ID：event_2
粗聚类标题：Notion just turned its workspace into a hub for AI agents
来源：TechCrunch AI, VentureBeat AI, The Decoder
类别：应用与商业, 应用与产品
候选事件包含的新闻：
1. [TechCrunch AI｜应用与商业] Notion just turned its workspace into a hub for AI agents
   摘要：Notion’s new developer platform lets teams connect AI agents, external data sources, and custom code directly into their workspace as the company pushes deeper into agentic productivity software.
   链接：https://techcrunch.com/2026/05/13/notion-just-turned-its-workspace-into-a-hub-for-ai-agents/
2. [VentureBeat AI｜应用与商业] Nous Research's NousCoder-14B is an open-source coding model landing right in the Claude Code moment
   摘要：Nous Research , the open-source artificial intelligence startup backed by crypto venture firm Paradigm , released a new competitive programming model on Monday that it says matches or exceeds several larger proprietary s
   链接：https://venturebeat.com/technology/nous-researchs-nouscoder-14b-is-an-open-source-coding-model-landing-right-in
3. [VentureBeat AI｜应用与商业] Salesforce rolls out new Slackbot AI agent as it battles Microsoft and Google in workplace AI
   摘要：Salesforce on Tuesday launched an entirely rebuilt version of Slackbot , the company's workplace assistant, transforming it from a simple notification tool into what executives describe as a fully powered AI agent capabl
   链接：https://venturebeat.com/technology/salesforce-rolls-out-new-slackbot-ai-agent-as-it-battles-microsoft-and
4. [VentureBeat AI｜应用与商业] Anthropic launches Cowork, a Claude Desktop agent that works in your files — no coding required
   摘要：Anthropic released Cowork on Monday, a new AI agent capability that extends the power of its wildly successful Claude Code tool to non-technical users — and according to company insiders, the team built the entire featur
   链接：https://venturebeat.com/technology/anthropic-launches-cowork-a-claude-desktop-agent-that-works-in-your-files-no
5. [The Decoder｜应用与产品] New Claude Mythos becomes the first AI model to clear all cyberattack simulations from Britain's AI safety agency
   摘要：The UK's AI Security Institute has revised its estimate of how fast AI cyber capabilities are doubling—twice. First from eight months down to 4.7, and now Anthropic's Claude Mythos Preview and OpenAI's GPT-5.5 have blown
   链接：https://the-decoder.com/new-claude-mythos-becomes-the-first-ai-model-to-clear-all-cyberattack-simulations-from-britains-ai-safety-agency/
6. [The Decoder｜应用与产品] Claude subscriptions get separate budgets for programmatic use, billed at full API prices
   摘要：As of June 15, Anthropic is splitting programmatic Claude usage out of the existing subscription quota. Instead, subscribers get a dedicated monthly credit ranging from $20 to $200 depending on their plan. Going forward,
   链接：https://the-decoder.com/claude-subscriptions-get-separate-budgets-for-programmatic-use-billed-at-full-api-prices/
7. [VentureBeat AI｜应用与商业] Claude Code costs up to $200 a month. Goose does the same thing for free.
   摘要：The artificial intelligence coding revolution comes with a catch: it's expensive. Claude Code , Anthropic's terminal-based AI agent that can write, debug, and deploy code autonomously, has captured the imagination of sof
   链接：https://venturebeat.com/infrastructure/claude-code-costs-up-to-usd200-a-month-goose-does-the-same-thing-for-free

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
粗聚类标题：Two weeks left: Startup Battlefield 200 applications close May 27
来源：TechCrunch AI
类别：应用与商业
候选事件包含的新闻：
1. [TechCrunch AI｜应用与商业] Two weeks left: Startup Battlefield 200 applications close May 27
   摘要：Your shot at VC access, global visibility, TechCrunch coverage, and $100K equity-free funding is running out. Deadline to apply is May 27. Apply now.
   链接：https://techcrunch.com/2026/05/14/two-weeks-left-startup-battlefield-200-applications-close-may-27/

---

候选事件ID：event_6
粗聚类标题：Ten Chinese firms including ByteDance reportedly get US clearance for AI chips they're not allowed to accept
来源：The Decoder
类别：应用与产品
候选事件包含的新闻：
1. [The Decoder｜应用与产品] Ten Chinese firms including ByteDance reportedly get US clearance for AI chips they're not allowed to accept
   摘要：The US has cleared roughly ten Chinese companies—including Alibaba, Tencent, and ByteDance—to buy up to 75,000 Nvidia H200 chips each. But not a single chip has shipped. According to Commerce Secretary Lutnick, Beijing i
   链接：https://the-decoder.com/ten-chinese-firms-including-bytedance-reportedly-get-us-clearance-for-ai-chips-theyre-not-allowed-to-accept/

---

候选事件ID：event_7
粗聚类标题：Microsoft's Edge Copilot can now read all your open tabs at once and write for you on LinkedIn
来源：The Decoder
类别：应用与产品
候选事件包含的新闻：
1. [The Decoder｜应用与产品] Microsoft's Edge Copilot can now read all your open tabs at once and write for you on LinkedIn
   摘要：Microsoft is upgrading Edge's Copilot AI chatbot so it can read all open tabs at once, compare products, and summarize articles. New additions include long-term memory, a tool that turns tabs into AI podcasts, and a quiz
   链接：https://the-decoder.com/microsofts-edge-copilot-can-now-read-all-your-open-tabs-at-once-and-write-for-you-on-linkedin/

---

候选事件ID：event_8
粗聚类标题：What Parameter Golf taught us about AI-assisted research
来源：OpenAI Blog, Microsoft AI Blog
类别：产品与模型, 企业应用
候选事件包含的新闻：
1. [OpenAI Blog｜产品与模型] What Parameter Golf taught us about AI-assisted research
   摘要：Parameter Golf brought together 1,000+ participants and 2,000+ submissions to explore AI-assisted machine learning research, coding agents, quantization, and novel model design under strict constraints.
   链接：https://openai.com/index/what-parameter-golf-taught-us
2. [Microsoft AI Blog｜企业应用] AI-equipped drones study dolphins on the edge of extinction
   摘要：The post AI-equipped drones study dolphins on the edge of extinction appeared first on The AI Blog .
   链接：https://news.microsoft.com/apac/features/ai-drones-dolphins-maui63/

---

候选事件ID：event_9
粗聚类标题：A conversation with Kevin Scott: What’s next in AI
来源：Microsoft AI Blog
类别：企业应用
候选事件包含的新闻：
1. [Microsoft AI Blog｜企业应用] A conversation with Kevin Scott: What’s next in AI
   摘要：The post A conversation with Kevin Scott: What’s next in AI appeared first on The AI Blog .
   链接：https://blogs.microsoft.com/ai/a-conversation-with-kevin-scott-whats-next-in-ai/

---

候选事件ID：event_10
粗聚类标题：How data and AI will transform contact centres for financial services
来源：Microsoft AI Blog
类别：企业应用
候选事件包含的新闻：
1. [Microsoft AI Blog｜企业应用] How data and AI will transform contact centres for financial services
   摘要：The post How data and AI will transform contact centres for financial services appeared first on The AI Blog .
   链接：https://cloudblogs.microsoft.com/industry-blog/en-gb/financial-services/2022/07/25/how-data-and-ai-will-transform-contact-centres-for-financial-services/

---

候选事件ID：event_11
粗聚类标题：Online math tutoring service uses AI to help boost students’ skills and confidence
来源：Microsoft AI Blog
类别：企业应用
候选事件包含的新闻：
1. [Microsoft AI Blog｜企业应用] Online math tutoring service uses AI to help boost students’ skills and confidence
   摘要：The post Online math tutoring service uses AI to help boost students’ skills and confidence appeared first on The AI Blog .
   链接：https://blogs.microsoft.com/ai/eedi-online-math-quiz/

---

候选事件ID：event_12
粗聚类标题：NVIDIA Rubin Platform, Open Models, Autonomous Driving: NVIDIA Presents Blueprint for the Future at CES
来源：NVIDIA AI Blog
类别：企业应用
候选事件包含的新闻：
1. [NVIDIA AI Blog｜企业应用] NVIDIA Rubin Platform, Open Models, Autonomous Driving: NVIDIA Presents Blueprint for the Future at CES
   摘要：NVIDIA founder and CEO Jensen Huang took the stage at the Fontainebleau Las Vegas to open CES 2026, declaring that AI is scaling into every domain and every device. “Computing has been fundamentally reshaped as a result 
   链接：https://blogs.nvidia.com/blog/2026-ces-special-presentation/

---

候选事件ID：event_13
粗聚类标题：Reaching Across the Isles: UK-LLM Brings AI to UK Languages With NVIDIA Nemotron
来源：NVIDIA AI Blog
类别：企业应用
候选事件包含的新闻：
1. [NVIDIA AI Blog｜企业应用] Reaching Across the Isles: UK-LLM Brings AI to UK Languages With NVIDIA Nemotron
   摘要：Celtic languages — including Cornish, Irish, Scottish Gaelic and Welsh — are the U.K.’s oldest living languages. To empower their speakers, the UK-LLM sovereign AI initiative is building an AI model based on NVIDIA Nemot
   链接：https://blogs.nvidia.com/blog/uk-llm-nemotron/

---

候选事件ID：event_14
粗聚类标题：It’s the Humidity: How International Researchers in Poland, Deep Learning and NVIDIA GPUs Could Change the Forecast
来源：NVIDIA AI Blog
类别：企业应用
候选事件包含的新闻：
1. [NVIDIA AI Blog｜企业应用] It’s the Humidity: How International Researchers in Poland, Deep Learning and NVIDIA GPUs Could Change the Forecast
   摘要：For more than a century, meteorologists have chased storms with chalkboards, equations, and now, supercomputers. But for all the progress, they still stumble over one deceptively simple ingredient: water vapor. Humidity 
   链接：https://blogs.nvidia.com/blog/humidity/

---

候选事件ID：event_15
粗聚类标题：Who decides what AI tells you? Campbell Brown, once Meta’s news chief, has thoughts
来源：TechCrunch AI
类别：应用与商业
候选事件包含的新闻：
1. [TechCrunch AI｜应用与商业] Who decides what AI tells you? Campbell Brown, once Meta’s news chief, has thoughts
   摘要："The conversation is sort of happening in Silicon Valley around one thing, and a totally different conversation is happening among consumers."
   链接：https://techcrunch.com/2026/05/13/who-decides-what-ai-tells-you-campbell-brown-once-metas-news-chief-has-thoughts/

---

候选事件ID：event_16
粗聚类标题：Alibaba's Qwen-Image-2.0 doubles compression and cuts generation steps from 40 to 4
来源：The Decoder
类别：应用与产品
候选事件包含的新闻：
1. [The Decoder｜应用与产品] Alibaba's Qwen-Image-2.0 doubles compression and cuts generation steps from 40 to 4
   摘要：Alibaba's technical report on Qwen-Image-2.0 breaks down how the image model compresses images twice as aggressively as most competitors, stabilizes training with a reworked transformer, and uses a dedicated module that 
   链接：https://the-decoder.com/alibabas-qwen-image-2-0-doubles-compression-and-cuts-generation-steps-from-40-to-4/

---

候选事件ID：event_17
粗聚类标题：ChatGPT's web traffic share dropped from 78% to 54% in one year as Gemini quietly tripled its reach
来源：The Decoder
类别：应用与产品
候选事件包含的新闻：
1. [The Decoder｜应用与产品] ChatGPT's web traffic share dropped from 78% to 54% in one year as Gemini quietly tripled its reach
   摘要：ChatGPT's website traffic share dropped from 77.6% to 53.7% in just twelve months, according to Similarweb. Google Gemini is the biggest winner, jumping from 7.3% to 26.7%. The numbers only cover web traffic, though, not
   链接：https://the-decoder.com/chatgpts-web-traffic-share-dropped-from-78-to-54-in-one-year-as-gemini-quietly-tripled-its-reach/

---

候选事件ID：event_18
粗聚类标题：Our response to the TanStack npm supply chain attack
来源：OpenAI Blog
类别：产品与模型
候选事件包含的新闻：
1. [OpenAI Blog｜产品与模型] Our response to the TanStack npm supply chain attack
   摘要：OpenAI details its response to the TanStack “Mini Shai-Hulud” supply chain attack, outlines protections taken to secure systems and signing certificates, and explains why macOS users must update OpenAI apps by June 12, 2
   链接：https://openai.com/index/our-response-to-the-tanstack-npm-supply-chain-attack

---

候选事件ID：event_20
粗聚类标题：Cisco cuts nearly 4,000 jobs to spend more on AI, reports ‘record quarterly revenue’
来源：TechCrunch AI
类别：应用与商业
候选事件包含的新闻：
1. [TechCrunch AI｜应用与商业] Cisco cuts nearly 4,000 jobs to spend more on AI, reports ‘record quarterly revenue’
   摘要：This is Cisco's latest layoff in recent years, while the company's chief executive touts record revenue and growth.
   链接：https://techcrunch.com/2026/05/14/cisco-cuts-nearly-4000-jobs-to-spend-more-on-ai-reports-record-quarterly-revenue/

---

候选事件ID：event_21
粗聚类标题：Wirestock raises $23M to supply creative multi-modal data to AI labs
来源：TechCrunch AI
类别：应用与商业
候选事件包含的新闻：
1. [TechCrunch AI｜应用与商业] Wirestock raises $23M to supply creative multi-modal data to AI labs
   摘要：Wirestock has over 700,000 creators on its platform, which supplies photos, videos and 3D content to AI labs.
   链接：https://techcrunch.com/2026/05/14/wirestock-raises-23m-to-supply-multi-modal-data-to-ai-labs/

---

候选事件ID：event_22
粗聚类标题：Clio’s $500M milestone arrives just as Anthropic ups the ante
来源：TechCrunch AI
类别：应用与商业
候选事件包含的新闻：
1. [TechCrunch AI｜应用与商业] Clio’s $500M milestone arrives just as Anthropic ups the ante
   摘要：Legal tech startups, including Clio, which just hit $500 million in ARR, are seeing massive customer adoption.
   链接：https://techcrunch.com/2026/05/13/clios-500m-milestone-arrives-just-as-anthropic-ups-the-ante/

---

候选事件ID：event_19
粗聚类标题：Railway secures $100 million to challenge AWS with AI-native cloud infrastructure
来源：VentureBeat AI, MIT Technology Review AI
类别：应用与商业, 趋势与影响
候选事件包含的新闻：
1. [VentureBeat AI｜应用与商业] Railway secures $100 million to challenge AWS with AI-native cloud infrastructure
   摘要：Railway , a San Francisco-based cloud platform that has quietly amassed two million developers without spending a dollar on marketing, announced Thursday that it raised $100 million in a Series B funding round, as surgin
   链接：https://venturebeat.com/infrastructure/railway-secures-usd100-million-to-challenge-aws-with-ai-native-cloud
2. [VentureBeat AI｜应用与商业] Listen Labs raises $69M after viral billboard hiring stunt to scale AI customer interviews
   摘要：Alfred Wahlforss was running out of options. His startup, Listen Labs , needed to hire over 100 engineers, but competing against Mark Zuckerberg's $100 million offers seemed impossible. So he spent $5,000 — a fifth of hi
   链接：https://venturebeat.com/technology/listen-labs-raises-usd69m-after-viral-billboard-hiring-stunt-to-scale-ai
3. [MIT Technology Review AI｜趋势与影响] AI chatbots are giving out people’s real phone numbers
   摘要：A Redditor recently wrote that he was “desperate for help”: for about a month, he said, his phone had been inundated by calls from “strangers” who were “looking for a lawyer, a product designer, a locksmith.” Callers wer
   链接：https://www.technologyreview.com/2026/05/13/1137203/ai-chatbots-are-giving-out-peoples-real-phone-numbers/

---

候选事件ID：event_23
粗聚类标题：AlphaEvolve: How our Gemini-powered coding agent is scaling impact across fields
来源：Google DeepMind Blog
类别：产品与研究
候选事件包含的新闻：
1. [Google DeepMind Blog｜产品与研究] AlphaEvolve: How our Gemini-powered coding agent is scaling impact across fields
   摘要：Explore how AlphaEvolve's Gemini-powered algorithms are driving impact across business, infrastructure, and science.
   链接：https://deepmind.google/blog/alphaevolve-impact/

---

候选事件ID：event_24
粗聚类标题：Establishing AI and data sovereignty in the age of autonomous systems
来源：MIT Technology Review AI
类别：趋势与影响
候选事件包含的新闻：
1. [MIT Technology Review AI｜趋势与影响] Establishing AI and data sovereignty in the age of autonomous systems
   摘要：When generative AI first moved from research labs into real-world business applications, enterprises made a tacit bargain: “Capability now, control later.” Feed your proprietary data into third-party AI models, and you w
   链接：https://www.technologyreview.com/2026/05/14/1137168/establishing-ai-and-data-sovereignty-in-the-age-of-autonomous-systems/

---

候选事件ID：event_25
粗聚类标题：Data readiness for agentic AI in financial services
来源：MIT Technology Review AI
类别：趋势与影响
候选事件包含的新闻：
1. [MIT Technology Review AI｜趋势与影响] Data readiness for agentic AI in financial services
   摘要：Financial services companies have unique needs when it comes to business AI. They operate in one of the most highly regulated sectors while responding to external events that are updated by the second. As a result, the s
   链接：https://www.technologyreview.com/2026/05/14/1137034/data-readiness-for-agentic-ai-in-financial-services/
