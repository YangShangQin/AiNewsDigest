# AI News Digest

GitHub-ready package for the `ai-news-digest` Codex skill.

## Structure

```text
ai-news-digest/
├── SKILL.md
├── README.md
├── requirements.txt
├── .gitignore
├── agents/
├── config/
├── references/
├── scripts/
├── tests/
├── reports/
│   ├── ai-daily-YYYY-MM-DD.md
│   └── ai-weekly-YYYY-MM-DD.md
└── vendor/  (local fallback, ignored by git)
```

## Usage

Check Python first:

```bash
python3 --version
```

If `python3` is unavailable, install Python 3 before running this skill. `scripts/report.py` automatically checks `requests` and `beautifulsoup4` on startup and installs missing packages with:

```bash
python3 -m pip install -r requirements.txt
```

You can still create a local virtual environment manually if you want dependency isolation:

```bash
python3 -m venv .venv
# Activate the virtual environment for your shell, then:
python3 -m pip install -r requirements.txt
```

Preferred workflow:

1. Collect candidates:

```bash
python3 scripts/report.py daily \
  --date 2026-04-10 \
  --candidate-pool-size 15 \
  --compact-json \
  --output-json /tmp/ai-daily-candidates.json
```

2. Inspect the candidate set:

```bash
python3 scripts/report.py inspect \
  --input-json /tmp/ai-daily-candidates.json
```

3. Let the AI agent translate titles/summaries and curate the final JSON.

4. Render the final Markdown:

```bash
python3 scripts/report.py render \
  --input-json /tmp/ai-daily-final.json \
  --output ~/reports/ai-daily-2026-04-10.md
```

When using this skill through Codex, the default behavior is to save the final report locally.
If the user does not specify an output path, save to:

- `~/reports/ai-daily-YYYY-MM-DD.md`
- `~/reports/ai-weekly-YYYY-MM-DD.md`

Only skip local file generation when the user explicitly asks to return the report in chat only.

If you omit `--output-json`, `daily` / `weekly` still print a debug-oriented Markdown report directly, but the preferred skill flow is `collect -> AI editorial -> render`.

Generate a weekly candidate set:

```bash
python3 scripts/report.py weekly \
  --date 2026-04-10 \
  --candidate-pool-size 15 \
  --compact-json \
  --output-json /tmp/ai-weekly-candidates.json
```

Useful CLI options:

- `daily`, `weekly`: collect candidates or print debug Markdown when `--output-json` is omitted.
- `inspect`: print a compact candidate review view from `--input-json`.
- `render`: render final Markdown from edited `--input-json`.
- `--from ISO8601 --to ISO8601`: use an explicit time window.
- `--max-items`: final item count per section, default `10`.
- `--candidate-pool-size`: collected candidate count per section, default `--max-items`.
- `--compact-json`: write smaller candidate JSON for agent editing.
- `--source-workers`: concurrent source fetch workers, default `4`.
- `--recall-workers`: concurrent search recall queries, default `6`.
- `--summary-fetch-limit`: remote article summary fetch limit per section, default `--max-items`.
- `--inspect-summary-len`: summary length in `inspect`, default `120`.
- `--sources-config`: override the source configuration file.
- `--fixture-dir`: use local fixtures for tests or debugging.

Run tests:

```bash
python3 -m unittest discover -s tests
```

## Source Configuration

News sources are configured in:

[config/sources.json](config/sources.json)

Each source entry contains:

- `id`: internal source ID, used by scoring and reliability mapping.
- `name`: source name shown in the report header.
- `modes`: `daily` or `weekly`.
- `kind`: `news` or `arena`.
- `parser`: parser key implemented in `scripts/report.py`.
- `url`: fetch URL.
- `fixture`: optional fixture file used by tests.
- `enabled`: set to `false` to disable a source without deleting it.
- `description`: human-readable source notes.
- `params`: parser-specific settings, such as RSS filters, grouped HN queries, or extra Discourse list endpoints.

The default daily and weekly configuration includes `collector-search-recall`, a configurable recall layer adapted from `ai-news-collector`. It expands six search dimensions: newsletters, community virality, product/model launches, funding/business, research breakthroughs, and policy/regulation. Query templates live in `config/sources.json` and support `{month_year}`, `{month_name}`, `{year}`, `{month}`, and `{date}`.

Daily sources include smol.ai, Hacker News front page, Hacker News Search, Linux.do, daily.dev Agents, AIBase, Maomu, GitHub Trending, and collector search recall. Hacker News Search uses the popularity-ranked `/api/v1/search` endpoint with grouped queries and filters low-engagement stories where `points + 2*comments < 5`. Linux.do uses Discourse `top/hot/latest` list endpoints and local AI keyword filtering instead of `search.json`.

Weekly sources include ThursdAI, Latent Space AINews entries, collector search recall, and daily.dev Arena model discussion rankings.

If a new source can reuse an existing parser, only edit `sources.json`. If it uses a new page structure, add a parser in `report.py`, then reference it from `sources.json`.

## Browser Fallback

For daily.dev Arena, the script can optionally use `agent-browser` plus a Chromium-based browser when the configured parser fails and `browser_fallback` is enabled. Browser discovery order:

- `CHROME_PATH`
- `CHROMIUM_PATH`
- `BROWSER_BIN`
- executables on `PATH`

## Report Format

Reports are Markdown. Daily and weekly reports use three fixed news sections: `AICoding Top 10`, `AI行业 Top 10`, and `AI工具 Top 10`. Weekly reports also include `模型讨论度排行（daily.dev Arena）`.

Each final news item uses a fixed format:

```markdown
1. [中文标题](原始链接)
   - 摘要：不超过 200 字中文摘要（可省略）
   - 来源：来源名称
```

Weekly Arena rankings are rendered as a table with rank, model/tool name, heat score, 7-day discussion volume, average sentiment, and a representative discussion link.
