import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "report.py"
FIXTURE_DIR = ROOT / "tests" / "fixtures"


spec = importlib.util.spec_from_file_location("ai_news_digest_report", MODULE_PATH)
report = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = report
spec.loader.exec_module(report)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeTextResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self, payload):
        self.payload = payload

    def get(self, url, params=None, timeout=None):
        if "hn.algolia.com" not in url:
            raise AssertionError(f"unexpected network call: {url}")
        return FakeResponse(self.payload)


class FakeSearchSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params or {}, "timeout": timeout})
        if isinstance(self.payload, str):
            return FakeTextResponse(self.payload)
        return FakeResponse(self.payload)


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 4, 9, 10, 0, tzinfo=report.ZoneInfo("Asia/Shanghai"))
        self.daily_window = report.compute_window(
            "daily",
            "Asia/Shanghai",
            "2026-04-08",
            None,
            None,
            now=self.now,
        )
        self.weekly_window = report.compute_window(
            "weekly",
            "Asia/Shanghai",
            None,
            None,
            None,
            now=self.now,
        )

    def fake_algolia_payload(self):
        return {
            "hits": [
                {
                    "objectID": "1",
                    "title": "Claude Code tray indicator",
                    "url": "https://example.com/claude-code-tray",
                    "created_at_i": int(datetime(2026, 4, 8, 11, 0, tzinfo=timezone.utc).timestamp()),
                    "points": 88,
                    "num_comments": 21,
                    "story_text": "A tiny utility for Claude Code prompts.",
                },
                {
                    "objectID": "2",
                    "title": "Git commands I run before reading code",
                    "url": "https://example.com/git-commands",
                    "created_at_i": int(datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc).timestamp()),
                    "points": 500,
                    "num_comments": 100,
                    "story_text": "Plain git workflow for repositories.",
                },
            ]
        }

    def test_compute_window_daily_uses_previous_natural_day(self):
        window = report.compute_window("daily", "Asia/Shanghai", None, None, None, now=self.now)
        self.assertEqual(window.start.isoformat(), "2026-04-08T00:00:00+08:00")
        self.assertEqual(window.end.isoformat(), "2026-04-09T00:00:00+08:00")

    def test_choose_smol_issue_urls_avoids_off_by_one(self):
        urls = report.choose_smol_issue_urls(FakeSession(self.fake_algolia_payload()), self.daily_window, FIXTURE_DIR)
        self.assertEqual(urls, ["https://news.smol.ai/issues/26-04-08-sample-issue"])

    def test_parse_smol_issue_strips_numeric_prefix(self):
        items = report.parse_smol_issue(
            FakeSession(self.fake_algolia_payload()),
            "https://news.smol.ai/issues/26-04-08-sample-issue",
            self.daily_window,
            FIXTURE_DIR,
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].title, "Claude Code improves background agents")

    def test_parse_hn_front_filters_non_ai_code_posts(self):
        items = report.parse_hn_front(FakeSession(self.fake_algolia_payload()), self.daily_window, FIXTURE_DIR)
        self.assertEqual(len(items), 1)
        self.assertIn("Cursor", items[0].title)

    def test_parse_hn_algolia_filters_irrelevant_hits(self):
        items = report.parse_hn_algolia(FakeSession(self.fake_algolia_payload()), self.daily_window)
        self.assertEqual(len(items), 1)
        self.assertIn("Claude Code", items[0].title)

    def test_source_config_is_external_and_described(self):
        configs = report.load_source_configs()
        self.assertTrue(any(config.id == "ai-bot" and config.description for config in configs))
        self.assertTrue(any(config.id == "daily-dev-arena" and config.kind == "arena" for config in configs))

    def test_collector_search_recall_source_is_configured(self):
        configs = report.load_source_configs()
        source = next(config for config in configs if config.id == "collector-search-recall")
        self.assertEqual(source.parser, "search_recall")
        self.assertEqual(source.params["provider"], "google_news_rss")
        self.assertIn("daily", source.modes)
        self.assertIn("weekly", source.modes)
        dimensions = source.params["dimensions"]
        self.assertEqual({dimension["key"] for dimension in dimensions}, {
            "newsletter",
            "community",
            "product",
            "business",
            "research",
            "policy",
        })
        self.assertGreaterEqual(sum(len(dimension["queries"]) for dimension in dimensions), 8)

    def test_source_config_can_disable_source_without_code_change(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "sources.json"
            config_path.write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "id": "ai-bot",
                                "name": "ai-bot.cn",
                                "modes": ["daily"],
                                "kind": "news",
                                "parser": "ai_bot",
                                "url": "https://ai-bot.cn/daily-ai-news/",
                                "fixture": "ai_bot.html",
                                "enabled": False,
                                "description": "disabled in test",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            configs = report.load_source_configs(config_path)
        items, arena_entries, statuses = report.gather_daily_sources(
            FakeSession(self.fake_algolia_payload()),
            self.daily_window,
            FIXTURE_DIR,
            configs,
        )
        self.assertEqual(items, [])
        self.assertEqual(arena_entries, [])
        self.assertEqual(statuses, [])
        empty_items, _, empty_statuses = report.gather_daily_sources(
            FakeSession(self.fake_algolia_payload()),
            self.daily_window,
            FIXTURE_DIR,
            [],
        )
        self.assertEqual(empty_items, [])
        self.assertEqual(empty_statuses, [])

    def test_skill_docs_do_not_embed_user_specific_paths(self):
        skill_text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        script_text = (ROOT / "scripts" / "report.py").read_text(encoding="utf-8")
        self.assertNotIn("/Users/ysq", skill_text)
        self.assertNotIn("/tmp/ai-news-digest-chrome", skill_text)
        self.assertNotIn("/Applications/", script_text)
        self.assertNotIn("/tmp/ai-news-digest-chrome", script_text)
        self.assertNotIn('"9222"', script_text)

    def test_classify_text_matches_business_rules(self):
        self.assertEqual(
            report.classify_text("Meta 推出原生多模态大模型 Muse Spark", ""),
            "AI工具",
        )
        self.assertEqual(
            report.classify_text("腾讯推出国内首个浏览器智能体 QBotClaw", ""),
            "AICoding",
        )
        self.assertEqual(
            report.classify_text("阿里云百炼上线“记忆库”功能", ""),
            "AICoding",
        )
        self.assertEqual(
            report.classify_text("某公司完成新一轮融资", ""),
            "AI行业",
        )

    def test_render_event_prefers_editorial_fields(self):
        observed = datetime(2026, 4, 10, 9, 0, tzinfo=report.ZoneInfo("Asia/Shanghai"))
        item = report.RawItem(
            source_name="daily-dev-highlights",
            source_type="daily",
            title="OpenAI launches $100/month tier targeting developers hitting Codex and Claude Code limits",
            summary="OpenAI launches $100/month tier targeting developers hitting Codex and Claude Code limits",
            url="https://example.com/openai-tier",
            published_at=observed,
            observed_at=observed,
            position=1,
        )
        event = report.Event(
            title=item.title,
            summary=item.summary,
            canonical_url=item.url,
            published_at=item.published_at,
            observed_at=item.observed_at,
            items=[item],
            category="AICoding",
        )
        event.display_title = "OpenAI 推出 100 美元开发者套餐"
        event.display_summary = "面向高频使用 Codex 和 Claude Code 的开发者，提供更高额度与更稳定的编码支持。"
        rendered = report.render_event(event, 1, report.ZoneInfo("Asia/Shanghai"))
        self.assertIn("[OpenAI 推出 100 美元开发者套餐]", rendered)
        self.assertIn("](https://example.com/openai-tier)", rendered)
        summary_line = next(line for line in rendered.splitlines() if "摘要：" in line)
        summary = summary_line.split("摘要：", 1)[1]
        self.assertLessEqual(len(summary), 200)
        self.assertNotIn("targeting", rendered)
        self.assertNotIn("归类为", rendered)
        self.assertIn("   - 来源：daily-dev-highlights", rendered)
        self.assertNotIn("日期：", rendered)
        self.assertNotIn("分类：", rendered)
        self.assertNotIn("排名理由：", rendered)
        self.assertNotIn("链接：", rendered)
        rendered_tenth = report.render_event(event, 10, report.ZoneInfo("Asia/Shanghai"))
        self.assertIn("\n    - 摘要：", rendered_tenth)
        self.assertIn("\n    - 来源：daily-dev-highlights", rendered_tenth)
        self.assertNotIn("\n   - 摘要：", rendered_tenth)

    def test_parse_daily_dev_sources(self):
        items = report.parse_daily_dev_highlights(FakeSession(self.fake_algolia_payload()), self.daily_window, FIXTURE_DIR)
        self.assertEqual(len(items), 1)
        arena_items, arena_entries = report.parse_daily_dev_arena(
            FakeSession(self.fake_algolia_payload()), self.daily_window, FIXTURE_DIR
        )
        self.assertEqual(arena_items, [])
        self.assertEqual(len(arena_entries), 2)
        self.assertGreater(arena_entries[0].score, arena_entries[1].score)

    def test_parse_editorial_sources(self):
        ai_bot_items = report.parse_ai_bot(FakeSession(self.fake_algolia_payload()), self.daily_window, FIXTURE_DIR)
        self.assertEqual(len(ai_bot_items), 1)
        self.assertIn("observed_at_only", ai_bot_items[0].notes)

        aibase_items = report.parse_aibase(FakeSession(self.fake_algolia_payload()), self.daily_window, FIXTURE_DIR)
        self.assertEqual(len(aibase_items), 1)
        self.assertGreater(aibase_items[0].metrics["views"], 15000)

        maomu_items = report.parse_maomu(FakeSession(self.fake_algolia_payload()), self.daily_window, FIXTURE_DIR)
        self.assertEqual(len(maomu_items), 1)
        self.assertIsNotNone(maomu_items[0].published_at)

    def test_parse_github_trending_filters_non_ai_repo(self):
        items = report.parse_github_trending(FakeSession(self.fake_algolia_payload()), self.daily_window, FIXTURE_DIR)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "openai / codex-agent")

    def test_parse_search_recall_expands_dimensions_and_dedupes(self):
        config = report.SourceConfig(
            id="collector-search-recall",
            name="collector multi-dimensional search",
            modes=("daily",),
            kind="news",
            parser="search_recall",
            url="https://example.test/gdelt",
            params={
                "provider": "gdelt_doc",
                "max_records_per_query": 2,
                "dimensions": [
                    {
                        "key": "product",
                        "label": "产品发布与模型更新",
                        "weight": 1.25,
                        "queries": ["AI model release {month_year}"],
                    },
                    {
                        "key": "community",
                        "label": "社区热度/病毒传播",
                        "weight": 1.3,
                        "queries": ["AI trending {month_name}"],
                    },
                ],
            },
        )
        session = FakeSearchSession(
            {
                "articles": [
                    {
                        "title": "Meta releases AI model Muse Spark",
                        "url": "https://example.com/muse-spark",
                        "seendate": "20260408040000",
                        "domain": "example.com",
                    },
                    {
                        "title": "Duplicate Muse Spark story",
                        "url": "https://example.com/muse-spark?utm_source=test",
                        "seendate": "20260408050000",
                        "domain": "example.com",
                    },
                ]
            }
        )
        items = report.parse_search_recall_source(config, session, self.daily_window, None)
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(session.calls[0]["params"]["query"], "AI model release April 2026")
        self.assertEqual(session.calls[0]["params"]["startdatetime"], "20260407160000")
        self.assertEqual(session.calls[0]["params"]["enddatetime"], "20260408160000")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_name, "collector-search-recall")
        self.assertEqual(items[0].published_at.isoformat(), "2026-04-08T12:00:00+08:00")
        self.assertIn("search_dimension:product", items[0].notes)
        self.assertEqual(items[0].metrics["dimension_weight"], 1.25)

    def test_parse_search_recall_supports_google_news_rss_provider(self):
        config = report.SourceConfig(
            id="collector-search-recall",
            name="collector multi-dimensional search",
            modes=("daily",),
            kind="news",
            parser="search_recall",
            url="https://news.google.com/rss/search",
            params={
                "provider": "google_news_rss",
                "hl": "en-US",
                "gl": "US",
                "ceid": "US:en",
                "max_records_per_query": 2,
                "dimensions": [
                    {
                        "key": "product",
                        "label": "产品发布与模型更新",
                        "weight": 1.25,
                        "queries": ["AI product launch {month_year}"],
                    }
                ],
            },
        )
        xml_text = """<?xml version="1.0" encoding="UTF-8"?>
<rss><channel><item>
<title>OpenAI launches AI product for developers - Example News</title>
<link>https://news.google.com/rss/articles/example</link>
<pubDate>Wed, 08 Apr 2026 04:00:00 GMT</pubDate>
<description>OpenAI launches an AI product for developers.</description>
<source url="https://example.com">Example News</source>
</item></channel></rss>"""
        session = FakeSearchSession(xml_text)
        items = report.parse_search_recall_source(config, session, self.daily_window, None)
        self.assertEqual(session.calls[0]["params"]["q"], "AI product launch April 2026")
        self.assertEqual(session.calls[0]["params"]["hl"], "en-US")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].url, "https://news.google.com/rss/articles/example")
        self.assertEqual(items[0].summary, "OpenAI launches an AI product for developers.")

    def test_parse_weekly_feeds(self):
        thursdai_items = report.parse_thursdai(FakeSession(self.fake_algolia_payload()), self.weekly_window, FIXTURE_DIR)
        self.assertEqual(len(thursdai_items), 1)
        latent_items = report.parse_latent_ainews(FakeSession(self.fake_algolia_payload()), self.weekly_window, FIXTURE_DIR)
        self.assertEqual(len(latent_items), 1)
        self.assertTrue(latent_items[0].title.startswith("[AINews]"))

    def test_merge_items_merges_same_url(self):
        observed = datetime(2026, 4, 9, 9, 0, tzinfo=report.ZoneInfo("Asia/Shanghai"))
        left = report.RawItem(
            source_name="smol-ai",
            source_type="daily",
            title="Claude Code adds worktree support",
            summary="summary one",
            url="https://example.com/post?utm_source=test",
            published_at=observed,
            observed_at=observed,
            position=1,
        )
        right = report.RawItem(
            source_name="hn-algolia",
            source_type="daily",
            title="Claude Code adds worktree support",
            summary="summary two is longer",
            url="https://example.com/post",
            published_at=observed,
            observed_at=observed,
            position=2,
        )
        events = report.merge_items([left, right])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].summary, "summary two is longer")
        self.assertEqual(set(events[0].source_names), {"smol-ai", "hn-algolia"})

    def test_filter_items_by_window_keeps_observed_only_items(self):
        item = report.RawItem(
            source_name="github-trending",
            source_type="daily",
            title="openai / codex-agent",
            summary="AI coding repo",
            url="https://github.com/openai/codex-agent",
            published_at=None,
            observed_at=datetime(2026, 4, 9, 12, 0, tzinfo=report.ZoneInfo("Asia/Shanghai")),
            position=1,
            notes=["observed_at_only"],
        )
        filtered = report.filter_items_by_window([item], self.daily_window)
        self.assertEqual(len(filtered), 1)

    def test_choose_event_summary_fetches_article_excerpt_when_source_lacks_summary(self):
        observed = datetime(2026, 4, 9, 9, 0, tzinfo=report.ZoneInfo("Asia/Shanghai"))
        item = report.RawItem(
            source_name="daily-dev-highlights",
            source_type="daily",
            title="Claude Code adds worktree support",
            summary="",
            url="https://example.com/post",
            published_at=observed,
            observed_at=observed,
            position=1,
        )
        event = report.Event(
            title=item.title,
            summary="",
            canonical_url=item.url,
            published_at=item.published_at,
            observed_at=item.observed_at,
            items=[item],
            category="AICoding",
        )
        original_fetch_article_summary = report.fetch_article_summary
        try:
            report.fetch_article_summary = lambda session, url, title="": "Article first paragraph summary."
            summary = report.choose_event_summary(event, FakeSession(self.fake_algolia_payload()))
        finally:
            report.fetch_article_summary = original_fetch_article_summary
        self.assertEqual(summary, "Article first paragraph summary.")

    def test_render_payload_report_omits_summary_line_when_missing(self):
        payload = {
            "metadata": {
                "mode": "daily",
                "report_title": "AI 日报",
                "report_date": "2026-04-08",
                "news_sources": ["aibase"],
            },
            "sections": [
                {
                    "id": "AICoding",
                    "title": "AICoding Top 10",
                    "items": [
                        {
                            "title": "OpenAI 推出开发者套餐",
                            "summary": "",
                            "url": "https://example.com/post",
                            "source_names": ["aibase"],
                        }
                    ],
                },
                {"id": "AI行业", "title": "AI行业 Top 10", "items": []},
                {"id": "AI工具", "title": "AI工具 Top 10", "items": []},
            ],
            "arena": [],
        }
        rendered = report.render_payload_report(payload)
        self.assertIn("[OpenAI 推出开发者套餐](https://example.com/post)", rendered)
        self.assertNotIn("摘要：", rendered)
        self.assertIn("来源：aibase", rendered)

    def test_main_collect_json_outputs_candidate_payload(self):
        fake_session = FakeSession(self.fake_algolia_payload())
        original_ensure_session = report.ensure_session
        original_argv = sys.argv
        try:
            report.ensure_session = lambda: fake_session
            with tempfile.TemporaryDirectory() as tmp_dir:
                output_path = Path(tmp_dir) / "candidates.json"
                sys.argv = [
                    "report.py",
                    "daily",
                    "--date",
                    "2026-04-08",
                    "--fixture-dir",
                    str(FIXTURE_DIR),
                    "--output-json",
                    str(output_path),
                    "--candidate-pool-size",
                    "12",
                ]
                code = report.main()
                payload = json.loads(output_path.read_text(encoding="utf-8"))
        finally:
            report.ensure_session = original_ensure_session
            sys.argv = original_argv
        self.assertEqual(code, 0)
        self.assertEqual(payload["metadata"]["mode"], "daily")
        self.assertEqual(payload["metadata"]["max_items"], 10)
        self.assertEqual(payload["metadata"]["candidate_pool_size"], 12)
        self.assertTrue(payload["sections"][0]["items"])

    def test_main_render_from_json_renders_weekly_arena(self):
        original_argv = sys.argv
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                input_path = Path(tmp_dir) / "final.json"
                payload = {
                    "metadata": {
                        "mode": "weekly",
                        "report_title": "AI 周报",
                        "report_date": "2026-04-02 ~ 2026-04-08",
                        "news_sources": ["thursdai"],
                    },
                    "sections": [
                        {
                            "id": "AICoding",
                            "title": "AICoding Top 10",
                            "items": [
                                {
                                    "title": "Claude Code 发布新版本",
                                    "summary": "支持更多终端工作流。",
                                    "url": "https://example.com/claude",
                                    "source_names": ["thursdai"],
                                }
                            ],
                        },
                        {"id": "AI行业", "title": "AI行业 Top 10", "items": []},
                        {"id": "AI工具", "title": "AI工具 Top 10", "items": []},
                    ],
                    "arena": [
                        {
                            "rank": 1,
                            "name": "Claude Code",
                            "score": 81.2,
                            "volume": 120,
                            "avg_sentiment": 0.42,
                            "highlight_url": "https://example.com/discussion",
                        }
                    ],
                }
                input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                sys.argv = [
                    "report.py",
                    "render",
                    "--input-json",
                    str(input_path),
                ]
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    code = report.main()
                output = buffer.getvalue()
        finally:
            sys.argv = original_argv
        self.assertEqual(code, 0)
        self.assertIn("# AI 周报", output)
        self.assertIn("## 模型讨论度排行（daily.dev Arena）", output)
        self.assertIn("Claude Code", output)

    def test_gather_daily_sources_does_not_fetch_arena(self):
        items, arena_entries, statuses = report.gather_daily_sources(
            FakeSession(self.fake_algolia_payload()),
            self.daily_window,
            FIXTURE_DIR,
        )
        self.assertFalse(any(status.name == "app.daily.dev/arena" for status in statuses))
        self.assertEqual(arena_entries, [])
        self.assertFalse(any(item.source_name == "daily-dev-arena" for item in items))

    def test_gather_weekly_sources_fetches_arena(self):
        items, arena_entries, statuses = report.gather_weekly_sources(
            FakeSession(self.fake_algolia_payload()),
            self.weekly_window,
            FIXTURE_DIR,
        )
        self.assertTrue(items)
        self.assertEqual(len(arena_entries), 2)
        self.assertTrue(any(status.name == "app.daily.dev/arena" and status.ok for status in statuses))

    def test_main_daily_with_fixtures_renders_sections(self):
        fake_session = FakeSession(self.fake_algolia_payload())
        original_ensure_session = report.ensure_session
        original_argv = sys.argv
        try:
            report.ensure_session = lambda: fake_session
            sys.argv = [
                "report.py",
                "daily",
                "--date",
                "2026-04-08",
                "--fixture-dir",
                str(FIXTURE_DIR),
            ]
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = report.main()
        finally:
            report.ensure_session = original_ensure_session
            sys.argv = original_argv
        output = buffer.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("# AI 日报", output)
        self.assertIn("- 日期：2026-04-08", output)
        self.assertIn("- 新闻来源：", output)
        self.assertNotIn("- 生成时间：", output)
        self.assertNotIn("- 失败来源：", output)
        self.assertNotIn("- 时间窗：", output)
        self.assertNotIn("- 成功来源：", output)
        self.assertIn("## AICoding Top 10", output)
        self.assertNotIn("模型讨论度排行", output)
        self.assertIn("## AI行业 Top", output)
        self.assertIn("## AI工具 Top", output)
        self.assertNotIn("   - 日期：", output)
        self.assertNotIn("   - 分类：", output)
        self.assertNotIn("   - 排名理由：", output)
        self.assertNotIn("   - 链接：", output)

    def test_main_weekly_with_fixtures_renders_sections(self):
        original_ensure_session = report.ensure_session
        original_argv = sys.argv
        try:
            report.ensure_session = lambda: FakeSession(self.fake_algolia_payload())
            sys.argv = [
                "report.py",
                "weekly",
                "--fixture-dir",
                str(FIXTURE_DIR),
            ]
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = report.main()
        finally:
            report.ensure_session = original_ensure_session
            sys.argv = original_argv
        output = buffer.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("# AI 周报", output)
        self.assertIn("## 模型讨论度排行（daily.dev Arena）", output)


if __name__ == "__main__":
    unittest.main()
