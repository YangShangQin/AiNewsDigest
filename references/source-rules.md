# AI News Digest Source Rules

## 来源范围

来源列表以 `config/sources.json` 为准。下面是默认配置中的启用来源；后续新增、停用、替换来源时，优先维护配置文件，不要直接修改抓取流程。

### 日报
- `news.smol.ai/issues`
- `news.ycombinator.com`
- `Hacker News Search`（`hn.algolia.com`）
- `app.daily.dev/agents`
- `news.aibase.com/zh/news`
- `maomu.com/news`
- `github.com/trending`
- `news.google.com/rss/search`（`collector-search-recall`：按 Newsletter、社区热度、产品发布、融资、研究、监管 6 个维度做搜索召回）

### 周报
- `sub.thursdai.news/feed`
- `www.latent.space/feed`（仅保留标题以 `[AINews]` 开头或链接包含 `/p/ainews-` 的条目）
- `news.google.com/rss/search`（`collector-search-recall` 多维搜索召回）
- `app.daily.dev/agents/arena`（仅用于模型讨论度排行）

## 来源配置规则

- `id` 是内部来源 ID，会影响排序信号和来源可靠度映射；已存在来源不要随意改名。
- `name` 用于报告头部展示。
- `modes` 控制日报或周报。
- `kind` 控制普通新闻 `news` 或模型讨论度排行 `arena`。
- `parser` 必须对应 `scripts/report.py` 中的 parser 映射。
- `url` 和 `fixture` 分别用于线上抓取和测试 fixture。
- `params` 用于 parser 专用配置，例如 HN 查询词、RSS 过滤条件、`search_recall` 维度查询、daily.dev Arena 浏览器兜底。
- 新来源能复用现有 parser 时，只改 `config/sources.json`；页面结构完全不同才新增 parser。
- 多维搜索召回查询优先维护 `collector-search-recall.params.dimensions`；模板变量支持 `{month_year}`、`{month_name}`、`{year}`、`{month}`、`{date}`。

## 分类规则

采用单主类，不重复上榜。优先级：
`AICoding > AI工具 > AI行业`

### AICoding
命中以下任一方向优先归类：
- 编码模型、代码代理、IDE、CLI、MCP、Agent 平台、浏览器智能体、记忆库/长期记忆、代码审查、测试自动化、开发工作流
- 关键词示例：`codex`、`claude code`、`cursor`、`windsurf`、`copilot`、`aider`、`opencode`、`mcp`、`worktree`、`devtools`、`浏览器智能体`、`智能体平台`、`记忆库`

### AI工具
- 具体产品、模型能力、应用工具、开源软件、工作空间、浏览器助手、办公/视频/图像/语音工具
- 关键词示例：`model`、`multimodal`、`assistant`、`workspace`、`browser`、`video`、`image`、`audio`、`voice`、`plugin`、`tool`、`模型`、`多模态`

### AI行业
- 融资、估值、政策、监管、公司战略、产业趋势、研究报告、宏观动态
- 关键词示例：`funding`、`融资`、`valuation`、`收购`、`政策`、`regulation`、`market`、`report`、`战略`、`财报`

## 去重规则

1. 先按规范化 URL 去重：
- 去除片段 `#...`
- 去除常见追踪参数：`utm_*`、`ref`、`source`
- 统一相对链接为绝对链接
2. 再按标题归一化去重：
- 小写
- 去除标点与多余空格
- 归一化中英文数字与常见前缀
3. 若标题相似度高且关键 token 重合，也视为同一事件
4. 合并后保留：
- 最可靠来源的标题
- 最长摘要
- 最早的已知发布时间
- 所有来源链接与来源名

## Agent / Script 职责拆分

- 脚本负责：抓取、解析、时间统一、去重、打分、候选排序、摘要提取、Markdown 渲染
- AI agent 负责：最终中文标题翻译、中文摘要翻译或压缩、边界分类判断、低质量候选剔除、最终成稿质检

## 摘要规则

- 优先使用来源里已有的明显摘要
- 若来源没有明显摘要，脚本尝试抓取文章页的 `og:description`、`meta description` 或正文首段
- 摘要上限 200 字，不要求最少字数
- 若仍无法获得有效摘要，则最终报告中省略 `摘要` 字段
- 禁止补充模板化空话，例如“值得关注后续进展、影响范围、采用情况和实际落地效果”

## 评分规则

### 总公式

`总分 = 0.45*重要程度 + 0.35*关注度 + 0.20*讨论度`

### 重要程度

`重要程度 = 0.40*事件级别 + 0.25*来源可靠度 + 0.20*跨源覆盖 + 0.15*时效性`

### 关注度

`关注度 = 0.45*站内热度 + 0.35*跨源覆盖 + 0.20*页面位置/榜单位置`

### 讨论度

`讨论度 = 0.70*社区讨论信号 + 0.30*跨社区回响`

## 站内热度映射

- Hacker News：`points`、`comments`
- daily.dev Highlights：高亮顺位
- daily.dev Arena：近 7 天讨论量、`dIndex`、精选讨论互动
- GitHub Trending：`stars today`、榜单位置
- collector-search-recall：维度权重、搜索结果位置；社区热度维度额外计入讨论信号
- AIBase：列表顺位、可见浏览量
- 猫目：列表顺位、相对时间
- 编辑型资讯页：列表顺位与跨源覆盖

## 时间字段

- 能取到明确发布时间时，输出该字段
- 仅能取相对时间时，以抓取时刻回推绝对时间
- GitHub Trending 这类榜单页没有原始发布时间时，输出 `observed_at`
- `AI-Bot` 无单条绝对时间时，默认使用抓取时间作为观测时间
