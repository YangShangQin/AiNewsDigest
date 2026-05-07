---
name: ai-news-digest
description: 生成 AI 日报或周报，聚合 AICoding、AI行业、AI工具三类信息并按重要程度、关注度、讨论度排序。用于用户需要“生成 AI 日报/周报”“汇总最近 24 小时 AI coding 新闻”“整理上周 AI 行业动态”时。
---

# AI News Digest

## Overview

优先把当前 skill 作为“两阶段流程”执行，而不是只运行脚本直接拿最终日报：
1. 运行 `scripts/report.py` 收集候选新闻，输出结构化 JSON。
2. 由 AI agent 基于候选 JSON 完成最终编辑：准确中文翻译标题、处理摘要、必要时微调栏目归属和上榜顺序。
3. 再调用 `scripts/report.py render` 把 agent 编辑后的 JSON 渲染成最终 Markdown 报告。

脚本负责抓取指定来源、统一分类、去重合并事件、计算排序分数、提取可用摘要、以及最终 Markdown 渲染；AI agent 负责最终中文标题/摘要、边界条目的 editorial judgement，以及成稿质检。
默认行为：除非用户明确说明“只在对话里返回”或明确指定其他输出路径，最终日报/周报必须同时生成到本地文件。
默认输出目录：`~/reports`。
默认文件名：
- 日报：`~/reports/ai-daily-YYYY-MM-DD.md`
- 周报：`~/reports/ai-weekly-YYYY-MM-DD.md`
若用户明确指定输出路径，则优先使用用户指定路径。
新闻来源统一维护在 `config/sources.json`，不要在 `scripts/report.py` 里直接增删来源列表。脚本通过 `parser` 字段映射到已有解析器；只有遇到全新页面结构时，才需要在脚本中新增 parser。
日报/周报同时包含一个 `search_recall` 召回层，它把 `ai-news-collector` 的 A-F 多维搜索策略配置化：Newsletter/周报聚合、社区热度/病毒传播、产品发布与模型更新、融资与商业、研究突破、监管与政策。该层只负责扩大候选集，候选新闻仍进入统一分类、去重合并和评分排序。

输出固定包含：
- `AICoding Top 10`
- `AI行业 Top 10`
- `AI工具 Top 10`
- `模型讨论度排行（daily.dev Arena）`（仅周报）

## Inputs

脚本参数：
- `daily`：收集日报候选；不带 `--output-json` 时仍可直接输出调试版 Markdown
- `weekly`：收集周报候选；不带 `--output-json` 时仍可直接输出调试版 Markdown
- `render`：将 agent 编辑后的 JSON 渲染成最终 Markdown
- `inspect`：读取候选 JSON 并输出低 token 摘要视图，供 agent 快速检查候选质量
- `--date YYYY-MM-DD`：锚定日期
- `--from ISO8601 --to ISO8601`：显式时间窗
- `--timezone Asia/Shanghai`：输出时区，默认上海
- `--max-items 10`：每个板块最多条数
- `--candidate-pool-size 15`：候选池大小，仅 collect 阶段使用，通常应大于 `--max-items`
- `--output <path>`：将 Markdown 写到指定路径
- `--output-json <path>`：将候选池写到 JSON 文件，供 agent 做最终编辑
- `--input-json <path>`：`render` 模式读取 agent 编辑后的 JSON
- `--compact-json`：收集阶段输出轻量候选 JSON，保留 agent 编辑必需字段，减少中间文件体积和上下文占用
- `--source-workers 4`：并发抓取新闻来源，默认 4
- `--recall-workers 6`：并发执行 `collector-search-recall` 查询，默认 6
- `--summary-fetch-limit 10`：每个板块只对前 N 条远程补抓文章摘要，默认等于 `--max-items`
- `--inspect-summary-len 120`：`inspect` 模式摘要截断长度，默认 120
- `--sources-config <path>`：指定来源配置文件，默认使用当前 skill 的 `config/sources.json`

测试/调试保留参数：
- `--fixture-dir <dir>`：用本地 fixture 替代在线抓取

## Runtime Dependencies

执行前先检查本机是否有可用 Python 环境：
```bash
python3 --version
```
如果 `python3` 不存在或不可执行，停止执行并向用户提示“缺少 Python 3 环境，无法运行 ai-news-digest”。

`scripts/report.py` 启动时会自动检查 `requests` 和 `beautifulsoup4`（导入模块为 `bs4`）。如果缺失，会使用当前 Python 环境执行：
```bash
python3 -m pip install -r <SKILL_DIR>/requirements.txt
```
如果自动安装失败，向用户提示 pip 错误，并让用户手动执行上述安装命令。

## Source Configuration

来源配置文件：`config/sources.json`。

每个来源固定字段：
- `id`：内部来源 ID，影响排序信号映射，已存在来源不要随意改名
- `name`：报告头部展示的来源名称
- `modes`：`daily` 或 `weekly`
- `kind`：`news` 或 `arena`
- `parser`：解析器名称，例如 `ai_bot`、`aibase`、`rss_feed`
- `url`：抓取入口 URL
- `fixture`：测试 fixture 文件名，可为空
- `enabled`：是否启用
- `description`：来源说明
- `params`：parser 专用参数，例如 RSS 过滤条件、HN 查询词、`search_recall` 维度查询、daily.dev Arena 浏览器兜底开关

新增来源规则：
- 如果新来源能复用现有 parser，只修改 `config/sources.json`。
- 如果新来源是 RSS，可优先使用 `rss_feed` parser，并通过 `params.title_prefix` 或 `params.link_contains` 做过滤。
- 如果只是调整多维搜索召回，不改脚本，优先维护 `collector-search-recall.params.dimensions` 下的查询模板；模板支持 `{month_year}`、`{month_name}`、`{year}`、`{month}`、`{date}`。
- 如果新来源页面结构不同，先在 `scripts/report.py` 新增 parser，再在 `config/sources.json` 增加来源项。
- 临时停用来源时只改 `enabled: false`，不要删除配置项。

## Time Rules

- 日报默认取执行时区下的前一个自然日。
- 若用户表达为“过去 24 小时”，应显式传入 `--from/--to`。
- 周报默认取执行时刻往前 `7*24h`。
- 若 `weekly` 配合 `--date`，视为“截至该日期结束时的最近 7 天”。

## Workflow

1. 收集候选：
```bash
python3 <SKILL_DIR>/scripts/report.py daily --output-json /tmp/ai-daily-candidates.json --compact-json
```
或：
```bash
python3 <SKILL_DIR>/scripts/report.py weekly --output-json /tmp/ai-weekly-candidates.json --compact-json
```
收集后先用低 token 检查视图查看候选，不要默认执行 `python3 -m json.tool` 或 `cat` 打印完整 JSON：
```bash
python3 <SKILL_DIR>/scripts/report.py inspect --input-json /tmp/ai-daily-candidates.json
```
2. 脚本会根据模式选择来源：
- 日报和周报来源都从 `config/sources.json` 读取。
- 日报默认包含 `news.smol.ai`、`news.ycombinator.com`、`Hacker News Search`（`hn.algolia.com`）、`app.daily.dev/agents`、`news.aibase.com/zh/news`、`maomu.com/news`、`github.com/trending`、`collector-search-recall`。
- 周报默认包含 `thursdai.news/feed`、`latent.space/feed`（仅保留 AINews 条目）、`collector-search-recall`、`app.daily.dev/agents/arena`。
3. 脚本对抓取结果做：
- 统一时间解析
- 单主类分类
- 标题/URL 去重合并
- 事件打分与排序
 - 准备候选摘要：优先保留来源里已有的明显摘要；若没有，则尝试抓取正文 `meta description` 或首段内容
4. AI agent 读取候选 JSON，并完成：
- 准确中文翻译标题
- 准确中文翻译或压缩摘要
- 删除低质量候选、必要时微调栏目归属和顺序
- 确认没有模板化空话
5. 再渲染最终 Markdown，并默认落到本地文件：
```bash
python3 <SKILL_DIR>/scripts/report.py render --input-json /tmp/ai-daily-final.json --output ~/reports/ai-daily-2026-04-10.md
```
若用户没有指定路径，不要只在对话中返回 Markdown；必须额外生成本地文件到 `~/reports`。

若部分来源失败，候选 JSON 与最终报告仍会生成，但报告头部固定只展示成功来源。

## Fallbacks

- 默认走 `requests + BeautifulSoup`。
- 对 daily.dev 等动态页，优先读取页面内的 hydration 数据。
- 若关键选择器缺失，会尝试 `agent-browser + Chromium 内核浏览器` 兜底读取完整 HTML。浏览器路径优先读取环境变量 `CHROME_PATH`、`CHROMIUM_PATH`、`BROWSER_BIN`，其次尝试系统 `PATH`。
- 若浏览器依赖不存在或兜底失败，仅跳过该来源，不中断整份报告。

## Run

默认日报候选：
```bash
python3 <SKILL_DIR>/scripts/report.py daily --output-json /tmp/ai-daily-candidates.json --compact-json
```

指定日报日期：
```bash
python3 <SKILL_DIR>/scripts/report.py daily --date 2026-04-08 --output-json /tmp/ai-daily-candidates.json --compact-json
```

最近 24 小时：
```bash
python3 <SKILL_DIR>/scripts/report.py daily --from 2026-04-08T12:00:00+08:00 --to 2026-04-09T12:00:00+08:00 --output-json /tmp/ai-daily-candidates.json --compact-json
```

默认周报候选：
```bash
python3 <SKILL_DIR>/scripts/report.py weekly --output-json /tmp/ai-weekly-candidates.json --compact-json
```

候选检查：
```bash
python3 <SKILL_DIR>/scripts/report.py inspect --input-json /tmp/ai-daily-candidates.json
```

渲染最终文件：
```bash
python3 <SKILL_DIR>/scripts/report.py render --input-json /tmp/ai-daily-final.json --output ~/reports/ai-daily-2026-04-10.md
```

## Output

最终报告必须以 Markdown 格式返回，并默认同时写入本地文件。若用户未指定输出路径，默认写入 `~/reports`。头部固定字段：
- `日期：yyyy-MM-dd`（跨日期周报使用 `yyyy-MM-dd ~ yyyy-MM-dd`）
- `新闻来源`

每条新闻格式必须固定，不允许自由增删字段：
```markdown
1. [中文标题](原始链接)
   - 摘要：不超过 200 字的中文摘要（可省略）
   - 来源：来源名称
```
子字段缩进必须按序号宽度对齐：`1.` 到 `9.` 使用 3 个空格，`10.` 使用 4 个空格，避免 Markdown 预览把最后一条新闻的摘要和来源解析到列表外。

每条新闻只允许包含：
- 排名与可点击的中文标题链接
- `摘要`（可选；有就忠实表述，无就省略）
- `来源`

每条新闻禁止输出：
- `日期`
- `分类`
- `排名理由`
- `链接` 或 `原始链接` 独立字段
- 模板化空话，例如“值得关注后续进展、影响范围、采用情况和实际落地效果”

Arena 排行仅在周报出现，固定包含：
- 排名
- 模型/工具名
- 讨论热度分
- 7 天讨论量摘要
- 代表性讨论链接

## References

- 排名、分类、来源规则：`references/source-rules.md`
- 实现入口：`scripts/report.py`
