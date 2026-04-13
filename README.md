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
│   └── ai-daily-YYYY-MM-DD.md
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
  --output-json /tmp/ai-daily-candidates.json
```

2. Let the AI agent translate titles/summaries and curate the final JSON.

3. Render the final Markdown:

```bash
python3 scripts/report.py render \
  --input-json /tmp/ai-daily-final.json \
  --output reports/ai-daily-2026-04-10.md
```

If you omit `--output-json`, `daily` / `weekly` still print a debug-oriented Markdown report directly, but the preferred skill flow is `collect -> AI editorial -> render`.

Generate a weekly candidate set:

```bash
python3 scripts/report.py weekly \
  --date 2026-04-10 \
  --candidate-pool-size 15 \
  --output-json /tmp/ai-weekly-candidates.json
```

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
- `params`: parser-specific settings, such as RSS filters or HN queries.

The default daily and weekly configuration includes `collector-search-recall`, a configurable recall layer adapted from `ai-news-collector`. It expands six search dimensions: newsletters, community virality, product/model launches, funding/business, research breakthroughs, and policy/regulation. Query templates live in `config/sources.json` and support `{month_year}`, `{month_name}`, `{year}`, `{month}`, and `{date}`.

If a new source can reuse an existing parser, only edit `sources.json`. If it uses a new page structure, add a parser in `report.py`, then reference it from `sources.json`.

## Browser Fallback

For dynamic pages, the script can optionally use `agent-browser` plus a Chromium-based browser. Browser discovery order:

- `CHROME_PATH`
- `CHROMIUM_PATH`
- `BROWSER_BIN`
- executables on `PATH`

## Report Format

Reports are Markdown. Daily reports use three fixed sections: `AICoding Top 10`, `AI行业 Top 10`, and `AI工具 Top 10`.

Each final news item uses a fixed format:

```markdown
1. [中文标题](原始链接)
   - 摘要：不超过 200 字中文摘要（可省略）
   - 来源：来源名称
```
