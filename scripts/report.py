#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import importlib.util
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from zoneinfo import ZoneInfo

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_SOURCES_CONFIG = SKILL_DIR / "config" / "sources.json"
VENDOR_DIR = SKILL_DIR / "vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

REQUIRED_PYTHON_PACKAGES = {
    "requests": "requests>=2.31,<3",
    "bs4": "beautifulsoup4>=4.14,<5",
}


def ensure_python_dependencies() -> None:
    missing = [
        package_spec
        for module_name, package_spec in REQUIRED_PYTHON_PACKAGES.items()
        if importlib.util.find_spec(module_name) is None
    ]
    if not missing:
        return

    print(
        "缺少 Python 依赖，正在使用当前 Python 环境安装: " + ", ".join(missing),
        file=sys.stderr,
    )
    requirements_path = SKILL_DIR / "requirements.txt"
    install_commands = [[sys.executable, "-m", "pip", "install", "-r", str(requirements_path)]]
    if sys.prefix == sys.base_prefix:
        install_commands.append([sys.executable, "-m", "pip", "install", "--user", "-r", str(requirements_path)])

    last_error: subprocess.CalledProcessError | None = None
    for command in install_commands:
        try:
            subprocess.run(command, check=True)
            importlib.invalidate_caches()
            still_missing = [
                package_spec
                for module_name, package_spec in REQUIRED_PYTHON_PACKAGES.items()
                if importlib.util.find_spec(module_name) is None
            ]
            if not still_missing:
                return
            missing = still_missing
        except subprocess.CalledProcessError as exc:
            last_error = exc

    message = (
        "无法自动安装 Python 依赖: "
        + ", ".join(missing)
        + "。请确认当前 Python 环境可用，并手动执行: "
        + f"{sys.executable} -m pip install -r {SKILL_DIR / 'requirements.txt'}"
    )
    if last_error is not None:
        message += f"。pip 退出码: {last_error.returncode}"
    raise RuntimeError(message)


try:
    ensure_python_dependencies()
except RuntimeError as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(1) from exc

import requests
from bs4 import BeautifulSoup  # type: ignore

DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_MAX_ITEMS = 10
DEFAULT_SUMMARY_LIMIT = 200
REQUEST_TIMEOUT = 20
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)
ALGOLIA_API = "https://hn.algolia.com/api/v1/search_by_date"
HN_QUERIES = [
    "Claude Code",
    "Codex",
    "Cursor",
    "AI coding",
    "LLM",
    "OpenAI",
    "Anthropic",
    "Gemini",
    "DeepSeek",
    "Qwen",
    "Gemma",
    "MCP",
]
TRACKING_PARAMS = {"ref", "source", "spm", "fbclid", "gclid"}
ARTICLE_SUMMARY_CACHE: dict[str, str | None] = {}

AI_CORE_KEYWORDS = {
    "ai",
    "aider",
    "agent",
    "agentic",
    "anthropic",
    "artificial intelligence",
    "chatgpt",
    "claude",
    "cline",
    "codex",
    "copilot",
    "cursor",
    "deepseek",
    "gemini",
    "gemma",
    "gpt",
    "llm",
    "machine learning",
    "mcp",
    "mistral",
    "model",
    "models",
    "multimodal",
    "openai",
    "qwen",
    "reasoning",
    "voice model",
    "人工智能",
    "智能体",
    "大模型",
    "多模态",
    "模型",
}

AICODING_KEYWORDS = {
    "agent",
    "agentic",
    "agent platform",
    "agent-native",
    "aicoding",
    "ai coding",
    "aider",
    "antigravity",
    "browser agent",
    "claude code",
    "cline",
    "code",
    "code review",
    "coder",
    "coding",
    "codex",
    "copilot",
    "cursor",
    "developer tools",
    "devtools",
    "editor",
    "harness",
    "ide",
    "kilocode",
    "memory",
    "mcp",
    "multi-agent",
    "opencode",
    "programming",
    "repo",
    "repository",
    "sandbox",
    "vscode",
    "windsurf",
    "worktree",
    "代码",
    "代码审查",
    "编码",
    "编码模型",
    "编程",
    "命令行",
    "多agent",
    "多智能体",
    "工作流",
    "开发",
    "开发工作流",
    "开发工具",
    "开发者工具",
    "平台能力",
    "智能体平台",
    "浏览器智能体",
    "测试自动化",
    "记忆库",
    "跨会话记忆",
    "长期记忆",
}

AI_TOOL_KEYWORDS = {
    "agent",
    "app",
    "assistant",
    "audio",
    "browser",
    "cli",
    "image",
    "model",
    "music",
    "office",
    "plugin",
    "product",
    "tool",
    "video",
    "voice",
    "workspace",
    "产品",
    "应用",
    "助手",
    "办公",
    "图像",
    "图片",
    "声音",
    "多模态",
    "工作台",
    "平台",
    "工具",
    "客户端",
    "插件",
    "模型",
    "浏览器",
    "生成",
    "语音",
    "视频",
    "转录",
    "音乐",
}

AI_INDUSTRY_KEYWORDS = {
    "acquisition",
    "arr",
    "company",
    "funding",
    "government",
    "industry",
    "ipo",
    "market",
    "policy",
    "pricing",
    "raise",
    "regulation",
    "report",
    "valuation",
    "独角兽",
    "估值",
    "公司",
    "战略",
    "并购",
    "政策",
    "监管",
    "研究",
    "融资",
    "行业",
    "趋势",
    "财报",
}

MAJOR_EVENT_KEYWORDS = {
    "announce": 22,
    "benchmark": 18,
    "codex": 20,
    "claude code": 20,
    "funding": 15,
    "gemini": 16,
    "gpt": 18,
    "launch": 20,
    "mcp": 18,
    "open-source": 20,
    "open source": 20,
    "pricing": 12,
    "raise": 14,
    "release": 20,
    "security": 16,
    "series": 14,
    "融资": 14,
    "开源": 20,
    "发布": 18,
    "安全": 16,
    "收购": 15,
}

SOURCE_RELIABILITY = {
    "smol-ai": 92,
    "latent-ainews": 90,
    "thursdai": 88,
    "hacker-news-front": 84,
    "hn-algolia": 82,
    "daily-dev-highlights": 78,
    "daily-dev-arena": 80,
    "ai-bot": 70,
    "aibase": 72,
    "maomu": 66,
    "github-trending": 84,
    "collector-search-recall": 58,
}

SEARCH_RECALL_DIMENSION_KEYWORDS = {
    "newsletter": {
        "newsletter",
        "roundup",
        "brief",
        "daily",
        "weekly",
        "digest",
        "新闻",
        "日报",
        "周报",
        "简报",
    },
    "community": {
        "viral",
        "trending",
        "github",
        "hacker news",
        "reddit",
        "open source",
        "popular",
        "buzzing",
        "开源",
        "爆火",
        "热门",
        "热议",
    },
    "product": {
        "announce",
        "announcement",
        "launch",
        "release",
        "model",
        "product",
        "tool",
        "assistant",
        "agent",
        "发布",
        "推出",
        "模型",
        "产品",
        "工具",
        "智能体",
    },
    "business": {
        "acquisition",
        "funding",
        "ipo",
        "investment",
        "raise",
        "startup",
        "valuation",
        "融资",
        "投资",
        "收购",
        "并购",
        "估值",
        "创业",
    },
    "research": {
        "benchmark",
        "breakthrough",
        "machine learning",
        "paper",
        "research",
        "state of the art",
        "study",
        "sota",
        "基准",
        "论文",
        "突破",
        "研究",
        "机器学习",
    },
    "policy": {
        "act",
        "governance",
        "law",
        "policy",
        "regulation",
        "safety",
        "法案",
        "治理",
        "监管",
        "政策",
        "安全",
    },
}


@dataclass
class ReportWindow:
    mode: str
    start: datetime
    end: datetime
    timezone: ZoneInfo
    requested_date: date | None = None


@dataclass
class RawItem:
    source_name: str
    source_type: str
    title: str
    summary: str
    url: str
    published_at: datetime | None
    observed_at: datetime
    position: int
    metrics: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def effective_time(self) -> datetime:
        return self.published_at or self.observed_at


@dataclass
class ArenaEntry:
    name: str
    entity: str
    score: float
    volume: int
    avg_sentiment: float
    highlight_url: str | None
    highlight_text: str


@dataclass
class Event:
    title: str
    summary: str
    canonical_url: str
    published_at: datetime | None
    observed_at: datetime
    items: list[RawItem]
    category: str
    score_total: float = 0.0
    score_importance: float = 0.0
    score_attention: float = 0.0
    score_discussion: float = 0.0
    rank_reason: str = ""
    prepared_summary: str = ""
    display_title: str | None = None
    display_summary: str | None = None

    @property
    def source_names(self) -> list[str]:
        names = []
        for item in self.items:
            if item.source_name not in names:
                names.append(item.source_name)
        return names

    @property
    def primary_time(self) -> datetime:
        return self.published_at or self.observed_at


@dataclass
class SourceStatus:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class SourceConfig:
    id: str
    name: str
    modes: tuple[str, ...]
    kind: str
    parser: str
    url: str
    fixture: str | None = None
    enabled: bool = True
    description: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    def supports(self, mode: str, kind: str) -> bool:
        return self.enabled and mode in self.modes and self.kind == kind


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate AI daily/weekly news digest.")
    parser.add_argument("mode", choices=["daily", "weekly", "render"])
    parser.add_argument("--date", dest="date_text")
    parser.add_argument("--from", dest="from_text")
    parser.add_argument("--to", dest="to_text")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS)
    parser.add_argument("--candidate-pool-size", type=int)
    parser.add_argument("--output")
    parser.add_argument("--output-json")
    parser.add_argument("--input-json")
    parser.add_argument("--fixture-dir", dest="fixture_dir")
    parser.add_argument(
        "--sources-config",
        dest="sources_config",
        help="Path to source configuration JSON. Defaults to config/sources.json in this skill.",
    )
    return parser.parse_args()


def ensure_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def load_source_configs(config_path: Path | None = None) -> list[SourceConfig]:
    path = config_path or DEFAULT_SOURCES_CONFIG
    data = json.loads(path.read_text(encoding="utf-8"))
    configs: list[SourceConfig] = []
    for raw in data.get("sources", []):
        modes = raw.get("modes") or ([raw["mode"]] if "mode" in raw else [])
        configs.append(
            SourceConfig(
                id=str(raw["id"]),
                name=str(raw.get("name") or raw["id"]),
                modes=tuple(str(mode) for mode in modes),
                kind=str(raw.get("kind") or "news"),
                parser=str(raw["parser"]),
                url=str(raw["url"]),
                fixture=str(raw["fixture"]) if raw.get("fixture") else None,
                enabled=bool(raw.get("enabled", True)),
                description=str(raw.get("description") or ""),
                params=dict(raw.get("params") or {}),
            )
        )
    return configs


def parse_iso_datetime(value: str, tz: ZoneInfo) -> datetime:
    text = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def compute_window(
    mode: str,
    tz_name: str,
    date_text: str | None,
    from_text: str | None,
    to_text: str | None,
    now: datetime | None = None,
) -> ReportWindow:
    tz = ZoneInfo(tz_name)
    now = (now or datetime.now(tz)).astimezone(tz)
    requested_date = date.fromisoformat(date_text) if date_text else None
    if from_text or to_text:
        if not (from_text and to_text):
            raise ValueError("--from 和 --to 必须同时提供")
        start = parse_iso_datetime(from_text, tz)
        end = parse_iso_datetime(to_text, tz)
        if end <= start:
            raise ValueError("时间窗结束时间必须晚于开始时间")
        return ReportWindow(mode=mode, start=start, end=end, timezone=tz, requested_date=requested_date)

    if mode == "daily":
        target = requested_date or (now.date() - timedelta(days=1))
        start = datetime.combine(target, time.min, tzinfo=tz)
        end = start + timedelta(days=1)
        return ReportWindow(mode=mode, start=start, end=end, timezone=tz, requested_date=target)

    if requested_date:
        end = datetime.combine(requested_date, time.max, tzinfo=tz) + timedelta(microseconds=1)
    else:
        end = now
    start = end - timedelta(days=7)
    return ReportWindow(mode=mode, start=start, end=end, timezone=tz, requested_date=requested_date)


def within_window(dt: datetime, window: ReportWindow) -> bool:
    point = dt.astimezone(window.timezone)
    return window.start <= point < window.end


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def contains_keyword(text: str, keyword: str) -> bool:
    if re.search(r"[\u4e00-\u9fff]", keyword):
        return keyword in text
    pattern = r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])"
    return re.search(pattern, text) is not None


def keyword_hits(text: str, keywords: Iterable[str]) -> int:
    return sum(1 for keyword in keywords if contains_keyword(text, keyword))


def collapse_summary(value: str, limit: int = DEFAULT_SUMMARY_LIMIT) -> str:
    text = clean_text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def has_cjk(value: str) -> bool:
    return re.search(r"[\u4e00-\u9fff]", value or "") is not None


def strip_html_fragments(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value or "")


def has_obvious_summary(value: str, title: str = "") -> bool:
    text = clean_text(strip_html_fragments(value))
    if not text:
        return False
    normalized_text = normalize_title(text)
    normalized_title = normalize_title(title)
    if normalized_text and normalized_text == normalized_title:
        return False
    if normalized_text and normalized_title and normalized_text.startswith(normalized_title):
        suffix = normalized_text[len(normalized_title) :].strip()
        if not suffix:
            return False
    lowered = text.lower()
    if re.fullmatch(
        r"(?:\d+\s+points?\s+by\s+\S+\s+\d+\s+\w+\s+ago\s+\d+\s+comments?|\d+\s*(?:分钟|小时|天)前.*)",
        lowered,
    ):
        return False
    if re.fullmatch(r"(?:github trending 开源项目|来源域名[:：].*)", lowered):
        return False
    if len(text) < 8 and not has_cjk(text):
        return False
    return True


KNOWN_TITLE_TRANSLATIONS = {
    "openai launches $100/month tier targeting developers hitting codex and claude code limits": "OpenAI 推出每月 100 美元开发者套餐，面向触达 Codex 与 Claude Code 限额的用户",
    "show hn: coderegon trail – a retro game to help you explore open-source repos": "Show HN：Coderegon Trail，用复古游戏帮助探索开源仓库",
    "show hn: coderegon trail - a retro game to help you explore open-source repos": "Show HN：Coderegon Trail，用复古游戏帮助探索开源仓库",
    "show hn: memoriki – llm wiki+mempalace for persistent personal knowledge bases": "Show HN：Memoriki，面向持久个人知识库的 LLM Wiki 与记忆宫殿模板",
    "show hn: memoriki - llm wiki+mempalace for persistent personal knowledge bases": "Show HN：Memoriki，面向持久个人知识库的 LLM Wiki 与记忆宫殿模板",
    "redox os bans all ai-generated code contributions and will close submissions immediately": "Redox OS 禁止所有 AI 生成代码贡献，并将直接关闭相关提交",
    "zed launches public agent stats dashboard tracking 2m sessions across ai coding agents": "Zed 发布 Agent Stats 公共仪表盘，追踪 200 万次 AI 编码智能体会话",
    "moving from wordpress to jekyll (and static site generators in general)": "使用 Claude Code 将站点从 WordPress 迁移到 Jekyll",
    "replit partners with revenuecat to add subscription monetization to vibe-coded apps": "Replit 与 RevenueCat 合作，为 vibe coding 应用加入订阅变现",
    "show hn: see what your employees are prompting llms (without network proxies)": "Show HN：查看员工向 LLM 提交的提示词，无需网络代理",
    "claude, what a marketing sham": "Claude 付费与营销体验吐槽",
    "reverse engineering gemini's synthid detection": "逆向分析 Gemini 的 SynthID 检测机制",
    "instant 1.0, a backend for ai-coded apps": "Instant 1.0：面向 AI 编码应用的后端",
    "anthropic releases monitor tool letting claude schedule its own wake-up events autonomously": "Anthropic 发布 Monitor 工具，让 Claude 可自主安排唤醒事件",
    "research-driven agents: when an agent reads before it codes": "研究驱动智能体：先阅读再编码",
    "unfolder for mac – a 3d model unfolding tool for creating papercraft": "Unfolder for Mac：用于纸模制作的 3D 模型展开工具",
    "unfolder for mac - a 3d model unfolding tool for creating papercraft": "Unfolder for Mac：用于纸模制作的 3D 模型展开工具",
}


def normalized_lookup_key(value: str) -> str:
    return re.sub(r"\s+", " ", clean_text(strip_html_fragments(value)).lower()).strip()


def english_word_count(value: str) -> int:
    return len(re.findall(r"[A-Za-z]{3,}", value or ""))


def phrase_to_chinese(value: str) -> str:
    text = clean_text(strip_html_fragments(value))
    known = KNOWN_TITLE_TRANSLATIONS.get(normalized_lookup_key(text))
    if known:
        return known
    replacements = [
        ("Show HN:", "Show HN："),
        ("Reverse engineering", "逆向分析"),
        ("Research-Driven Agents", "研究驱动 Agent"),
        ("When an agent reads before it codes", "当 Agent 先阅读再编码"),
        ("launches", "推出"),
        ("launch", "推出"),
        ("releases", "发布"),
        ("release", "发布"),
        ("bans all", "全面禁止"),
        ("AI-generated code contributions", "AI 生成代码贡献"),
        ("public Agent Stats dashboard", "Agent Stats 公共仪表盘"),
        ("tracking", "追踪"),
        ("AI coding agents", "AI 编码智能体"),
        ("AI-coded apps", "AI 编码应用"),
        ("open-source repos", "开源仓库"),
        ("open-source", "开源"),
        ("persistent personal knowledge bases", "持久化个人知识库"),
        ("LLM Wiki+MemPalace", "LLM Wiki 与记忆宫殿"),
        ("wake-up events", "唤醒事件"),
        ("autonomously", "自主运行"),
        ("subscription monetization", "订阅变现"),
        ("developers", "开发者"),
        ("hitting", "触达"),
        ("limits", "额度限制"),
        ("backend", "后端"),
        ("tool", "工具"),
        ("Agent", "智能体"),
        ("agents", "智能体"),
        ("model", "模型"),
        ("models", "模型"),
        ("code", "代码"),
        ("coding", "编码"),
        ("apps", "应用"),
        ("app", "应用"),
        ("dashboard", "仪表盘"),
        ("tier", "套餐"),
        ("partners with", "与"),
        ("to add", "合作加入"),
        ("without network proxies", "无需网络代理"),
    ]
    for source, target in replacements:
        if re.fullmatch(r"[A-Za-z0-9 ]+", source):
            pattern = r"(?<![A-Za-z0-9])" + re.escape(source) + r"(?![A-Za-z0-9])"
            text = re.sub(pattern, target, text, flags=re.I)
        else:
            text = re.sub(re.escape(source), target, text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace(" - ", "：").replace(" – ", "：").replace(" — ", "：")
    return text


def chinese_title(title: str, category: str) -> str:
    text = clean_text(title)
    repo_match = re.fullmatch(r"([A-Za-z0-9_.-]+)\s*/\s*([A-Za-z0-9_.-]+)", text)
    if repo_match:
        return f"开源库：{repo_match.group(1)}/{repo_match.group(2)}"
    return text


def chinese_summary(title: str, summary: str, category: str, limit: int = DEFAULT_SUMMARY_LIMIT) -> str:
    source = clean_text(strip_html_fragments(summary))
    if not has_obvious_summary(source, title):
        return ""
    return bounded_summary(source, title, category, limit)


def bounded_summary(value: str, title: str, category: str, limit: int = DEFAULT_SUMMARY_LIMIT, minimum: int = 0) -> str:
    text = collapse_summary(clean_text(value), limit)
    if len(text) < minimum:
        return ""
    return text


def normalize_title(value: str) -> str:
    text = clean_text(value).lower()
    text = re.sub(r"^#\d+\s*", "", text)
    text = re.sub(r"^[0-9]+\.\s*", "", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme:
        return url
    query_pairs = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in TRACKING_PARAMS:
            continue
        query_pairs.append((key, value))
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/") or "/",
            "",
            urlencode(query_pairs),
            "",
        )
    )


def jaccard_similarity(left: str, right: str) -> float:
    left_tokens = {token for token in left.split() if len(token) > 1}
    right_tokens = {token for token in right.split() if len(token) > 1}
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def parse_relative_time(text: str, now: datetime, tz: ZoneInfo) -> datetime | None:
    value = clean_text(text).lower()
    if not value:
        return None
    if "刚刚" in value or value == "just now":
        return now
    patterns = [
        (r"(\d+)\s*分钟前", "minutes"),
        (r"(\d+)\s*分钟", "minutes"),
        (r"(\d+)\s*小时前", "hours"),
        (r"(\d+)\s*小时", "hours"),
        (r"(\d+)\s*天前", "days"),
        (r"(\d+)\s*days?\s*ago", "days"),
        (r"(\d+)\s*hours?\s*ago", "hours"),
        (r"(\d+)\s*minutes?\s*ago", "minutes"),
    ]
    for pattern, unit in patterns:
        match = re.search(pattern, value)
        if not match:
            continue
        amount = int(match.group(1))
        delta = timedelta(**{unit: amount})
        return (now - delta).astimezone(tz)
    return None


def parse_http_datetime(value: str, tz: ZoneInfo) -> datetime | None:
    if not value:
        return None
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(tz)
        except ValueError:
            continue
    return None


class SafeFormatDict(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def search_template_context(window: ReportWindow) -> dict[str, str]:
    anchor = window.start.astimezone(window.timezone)
    if window.mode == "weekly":
        anchor = (window.end - timedelta(seconds=1)).astimezone(window.timezone)
    return {
        "date": anchor.date().isoformat(),
        "year": str(anchor.year),
        "month": f"{anchor.month:02d}",
        "month_name": anchor.strftime("%B"),
        "month_year": f"{anchor.strftime('%B')} {anchor.year}",
    }


def expand_search_query(template: str, window: ReportWindow) -> str:
    return clean_text(template.format_map(SafeFormatDict(search_template_context(window))))


def compact_utc_datetime(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")


def parse_compact_datetime(value: str, tz: ZoneInfo) -> datetime | None:
    text = clean_text(value)
    if not text:
        return None
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).astimezone(tz)
        except ValueError:
            continue
    try:
        return parse_iso_datetime(text, tz)
    except ValueError:
        return None


def fetch_text(
    session: requests.Session,
    url: str,
    fixture_dir: Path | None,
    fixture_name: str | None = None,
) -> str:
    if fixture_dir and fixture_name:
        return (fixture_dir / fixture_name).read_text(encoding="utf-8")
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text


def get_soup(html_text: str) -> BeautifulSoup:
    return BeautifulSoup(html_text, "html.parser")


def extract_article_summary_from_html(html_text: str, title: str = "") -> str:
    soup = get_soup(html_text)
    meta_candidates = [
        soup.find("meta", attrs={"property": "og:description"}),
        soup.find("meta", attrs={"name": "description"}),
        soup.find("meta", attrs={"name": "twitter:description"}),
    ]
    for meta in meta_candidates:
        content = clean_text(meta.get("content") if meta else "")
        if has_obvious_summary(content, title):
            return collapse_summary(content, DEFAULT_SUMMARY_LIMIT)

    paragraph_candidates: list[str] = []
    containers = [
        soup.find("article"),
        soup.find("main"),
        soup.body,
    ]
    for container in containers:
        if container is None:
            continue
        for paragraph in container.find_all("p"):
            text = clean_text(paragraph.get_text(" ", strip=True))
            if not has_obvious_summary(text, title):
                continue
            paragraph_candidates.append(text)
            if len(paragraph_candidates) >= 3:
                break
        if paragraph_candidates:
            break
    if paragraph_candidates:
        return collapse_summary(" ".join(paragraph_candidates), DEFAULT_SUMMARY_LIMIT)
    return ""


def fetch_article_summary(session: requests.Session, url: str, title: str = "") -> str:
    normalized = normalize_url(url)
    if normalized in ARTICLE_SUMMARY_CACHE:
        return ARTICLE_SUMMARY_CACHE[normalized] or ""
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except Exception:
        ARTICLE_SUMMARY_CACHE[normalized] = None
        return ""
    summary = extract_article_summary_from_html(response.text, title)
    ARTICLE_SUMMARY_CACHE[normalized] = summary or None
    return summary


def classify_text(title: str, summary: str) -> str:
    text = f"{title} {summary}".lower()
    core_hits = keyword_hits(text, AI_CORE_KEYWORDS)
    coding_hits = keyword_hits(text, AICODING_KEYWORDS)
    tool_hits = keyword_hits(text, AI_TOOL_KEYWORDS)
    industry_hits = keyword_hits(text, AI_INDUSTRY_KEYWORDS)
    coding_score = float(coding_hits)
    tool_score = float(tool_hits)
    industry_score = float(industry_hits)

    if contains_keyword(text, "浏览器智能体") or (
        contains_keyword(text, "浏览器") and (contains_keyword(text, "智能体") or contains_keyword(text, "agent"))
    ):
        coding_score += 3.0
    if any(
        contains_keyword(text, keyword)
        for keyword in {
            "agent platform",
            "agent-native",
            "智能体平台",
            "多智能体",
            "多agent",
            "multi-agent",
            "命令行",
            "cli",
            "mcp",
            "ide",
            "编码模型",
            "code review",
            "代码审查",
            "测试自动化",
            "开发工作流",
            "开发者工具",
            "开发工具",
            "记忆库",
            "跨会话记忆",
            "长期记忆",
        }
    ):
        coding_score += 2.0

    if any(
        contains_keyword(text, keyword)
        for keyword in {
            "模型",
            "大模型",
            "多模态",
            "产品",
            "应用",
            "助手",
            "平台",
            "工具",
            "图像",
            "视频",
            "语音",
            "音乐",
            "浏览器",
            "工作台",
            "客户端",
            "插件",
            "生成",
            "转录",
        }
    ):
        tool_score += 1.0

    if any(
        contains_keyword(text, keyword)
        for keyword in {
            "融资",
            "估值",
            "并购",
            "收购",
            "政策",
            "监管",
            "行业",
            "趋势",
            "公司",
            "财报",
            "战略",
            "funding",
            "valuation",
            "acquisition",
            "ipo",
            "policy",
            "regulation",
            "market",
            "report",
            "arr",
        }
    ):
        industry_score += 2.0

    if industry_score >= 2 and coding_score == 0 and tool_score == 0:
        return "AI行业"
    if coding_score >= max(2.0, tool_score + 1.0):
        return "AICoding"
    if coding_score >= 2 and coding_score >= industry_score:
        return "AICoding"
    if tool_score >= max(1.0, industry_score) and (core_hits > 0 or tool_score >= 2):
        return "AI工具"
    if industry_score > 0:
        return "AI行业"
    if coding_score > 0:
        return "AICoding"
    if tool_score > 0 and core_hits > 0:
        return "AI工具"
    if core_hits > 0:
        return "AI工具"
    if industry_hits:
        return "AI行业"
    return "AI行业"


def is_ai_relevant(title: str, summary: str = "", url: str = "") -> bool:
    text = clean_text(f"{title} {summary} {url}").lower()
    return keyword_hits(text, AI_CORE_KEYWORDS) > 0


def is_search_recall_relevant(title: str, summary: str, url: str, dimension_key: str) -> bool:
    text = clean_text(f"{title} {summary} {url}").lower()
    if keyword_hits(text, AI_CORE_KEYWORDS) == 0:
        return False
    dimension_keywords = SEARCH_RECALL_DIMENSION_KEYWORDS.get(dimension_key, set())
    if not dimension_keywords:
        return True
    return keyword_hits(text, dimension_keywords) > 0


def window_reference_time(window: ReportWindow) -> datetime:
    actual_now = datetime.now(window.timezone)
    cutoff = window.end - timedelta(seconds=1)
    return min(actual_now, cutoff)


def event_level_score(title: str, summary: str, category: str) -> float:
    text = f"{title} {summary}".lower()
    score = 30.0
    for keyword, boost in MAJOR_EVENT_KEYWORDS.items():
        if keyword in text:
            score += boost
    if category == "AICoding":
        score += 10
    elif category == "AI工具":
        score += 6
    return min(score, 100.0)


def source_reliability(source_names: Iterable[str]) -> float:
    values = [SOURCE_RELIABILITY.get(name, 60) for name in source_names]
    return sum(values) / max(1, len(values))


def historical_penalty(title: str, url: str, window: ReportWindow) -> float:
    years = [int(match) for match in re.findall(r"(20\d{2})", f"{title} {url}")]
    stale_years = [year for year in years if year < window.start.year - 1]
    if not stale_years:
        return 0.0
    latest_stale = max(stale_years)
    gap = max(1, window.start.year - latest_stale)
    return min(24.0, gap * 4.0)


def timeliness_score(event_time: datetime, window: ReportWindow) -> float:
    delta_hours = max(0.0, (window.end - event_time).total_seconds() / 3600.0)
    if window.mode == "daily":
        return max(30.0, 100.0 - delta_hours * 2.5)
    return max(20.0, 100.0 - delta_hours / 3.0)


def coverage_score(source_count: int) -> float:
    return min(100.0, 35.0 * source_count)


def site_heat(item: RawItem) -> float:
    metrics = item.metrics
    if item.source_name.startswith("hacker-news") or item.source_name == "hn-algolia":
        points = metrics.get("points", 0.0)
        comments = metrics.get("comments", 0.0)
        return min(100.0, points * 0.35 + comments * 1.2)
    if item.source_name == "github-trending":
        return min(100.0, metrics.get("stars_today", 0.0) / 80.0)
    if item.source_name == "daily-dev-arena":
        return min(100.0, metrics.get("arena_score", 0.0))
    if item.source_name == "aibase":
        return min(100.0, metrics.get("views", 0.0) / 250.0 + (110 - item.position * 8))
    if item.source_name == "maomu":
        return max(10.0, 95.0 - item.position * 7.0)
    if item.source_name == "daily-dev-highlights":
        return max(10.0, 100.0 - item.position * 8.0)
    if item.source_name == "collector-search-recall":
        dimension_weight = item.metrics.get("dimension_weight", 1.0)
        result_position = max(1.0, item.metrics.get("result_position", float(item.position)))
        return min(100.0, max(15.0, 42.0 + dimension_weight * 10.0 - result_position * 5.0))
    if item.source_name == "smol-ai":
        return max(15.0, 95.0 - item.position * 6.0)
    if item.source_name in {"ai-bot", "thursdai", "latent-ainews"}:
        return max(10.0, 88.0 - item.position * 5.0)
    return max(10.0, 80.0 - item.position * 5.0)


def discussion_signal(items: list[RawItem]) -> float:
    score = 0.0
    for item in items:
        if item.source_name.startswith("hacker-news") or item.source_name == "hn-algolia":
            score += item.metrics.get("comments", 0.0) * 1.5
        elif item.source_name == "daily-dev-arena":
            score += item.metrics.get("arena_discussion", 0.0)
        elif item.source_name == "daily-dev-highlights":
            score += 20.0 / max(1, item.position)
        elif item.source_name == "github-trending":
            score += min(30.0, item.metrics.get("stars_today", 0.0) / 120.0)
        elif item.source_name == "collector-search-recall" and item.metrics.get("community_dimension"):
            score += 16.0 / max(1.0, item.metrics.get("result_position", 1.0))
    return min(100.0, score)


def cross_community_score(source_names: list[str]) -> float:
    community_sources = {
        "hacker-news-front",
        "hn-algolia",
        "daily-dev-highlights",
        "daily-dev-arena",
        "github-trending",
    }
    overlap = len([name for name in source_names if name in community_sources])
    return min(100.0, overlap * 32.0 + max(0, len(source_names) - overlap) * 10.0)


def compute_event_scores(event: Event, window: ReportWindow) -> None:
    penalty = historical_penalty(event.title, event.canonical_url, window)
    importance = (
        0.40 * event_level_score(event.title, event.summary, event.category)
        + 0.25 * source_reliability(event.source_names)
        + 0.20 * coverage_score(len(event.source_names))
        + 0.15 * timeliness_score(event.primary_time, window)
    )
    attention = (
        0.45 * min(100.0, max(site_heat(item) for item in event.items))
        + 0.35 * coverage_score(len(event.source_names))
        + 0.20 * max(5.0, 100.0 - min(item.position for item in event.items) * 6.0)
    )
    discussion = (
        0.70 * discussion_signal(event.items)
        + 0.30 * cross_community_score(event.source_names)
    )
    importance = max(0.0, importance - penalty)
    attention = max(0.0, attention - penalty * 0.8)
    total = 0.45 * importance + 0.35 * attention + 0.20 * discussion
    event.score_importance = round(importance, 2)
    event.score_attention = round(attention, 2)
    event.score_discussion = round(discussion, 2)
    event.score_total = round(total, 2)
    event.rank_reason = (
        f"重要程度 {event.score_importance:.1f}，关注度 {event.score_attention:.1f}，"
        f"讨论度 {event.score_discussion:.1f}；来源 {', '.join(event.source_names)}"
    )


def merge_items(raw_items: list[RawItem]) -> list[Event]:
    events: list[Event] = []
    for item in raw_items:
        normalized_url = normalize_url(item.url)
        normalized_title = normalize_title(item.title)
        matched: Event | None = None
        for event in events:
            if normalize_url(event.canonical_url) == normalized_url:
                matched = event
                break
            event_title = normalize_title(event.title)
            if normalized_title == event_title:
                matched = event
                break
            similarity = jaccard_similarity(normalized_title, event_title)
            same_day = event.primary_time.date() == item.effective_time().date()
            if similarity >= 0.78 and same_day:
                matched = event
                break
        if matched is None:
            events.append(
                Event(
                    title=item.title,
                    summary=item.summary,
                    canonical_url=item.url,
                    published_at=item.published_at,
                    observed_at=item.observed_at,
                    items=[item],
                    category=classify_text(item.title, item.summary),
                )
            )
            continue
        matched.items.append(item)
        if not matched.summary or len(item.summary) > len(matched.summary):
            matched.summary = item.summary
        if matched.published_at is None or (item.published_at and item.published_at < matched.published_at):
            matched.published_at = item.published_at
        if SOURCE_RELIABILITY.get(item.source_name, 0) > max(
            SOURCE_RELIABILITY.get(existing.source_name, 0) for existing in matched.items[:-1]
        ):
            matched.title = item.title
            matched.canonical_url = item.url
        matched.category = classify_text(matched.title, matched.summary)
    return events


def group_events(events: list[Event], window: ReportWindow, max_items: int) -> dict[str, list[Event]]:
    grouped = {"AICoding": [], "AI行业": [], "AI工具": []}
    for event in events:
        compute_event_scores(event, window)
        grouped[event.category].append(event)
    for key in grouped:
        grouped[key].sort(key=lambda item: (item.score_total, item.primary_time.timestamp()), reverse=True)
        grouped[key] = grouped[key][:max_items]
    return grouped


def choose_event_summary(event: Event, session: requests.Session | None = None) -> str:
    candidates: list[tuple[float, str]] = []
    seen: set[str] = set()
    for item in event.items:
        text = clean_text(item.summary)
        if not has_obvious_summary(text, event.title):
            continue
        normalized = normalize_title(text)
        if normalized in seen:
            continue
        seen.add(normalized)
        score = SOURCE_RELIABILITY.get(item.source_name, 60) + min(len(text), 200) / 10.0
        candidates.append((score, text))
    event_summary = clean_text(event.summary)
    if has_obvious_summary(event_summary, event.title):
        candidates.append((65.0 + min(len(event_summary), 200) / 10.0, event_summary))
    if candidates:
        candidates.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
        return collapse_summary(candidates[0][1], DEFAULT_SUMMARY_LIMIT)
    if session is None:
        return ""
    return fetch_article_summary(session, event.canonical_url, event.title)


def prepare_grouped_events(grouped: dict[str, list[Event]], session: requests.Session | None = None) -> None:
    for events in grouped.values():
        for event in events:
            event.prepared_summary = choose_event_summary(event, session)


def serialize_event_candidate(event: Event, rank: int) -> dict[str, Any]:
    return {
        "candidate_id": f"{event.category}-{rank}",
        "rank": rank,
        "original_title": event.title,
        "original_summary": clean_text(event.summary),
        "prepared_summary": clean_text(event.prepared_summary),
        "title": event.display_title,
        "summary": event.display_summary,
        "url": event.canonical_url,
        "source_names": event.source_names,
        "published_at": event.published_at.isoformat() if event.published_at else None,
        "observed_at": event.observed_at.isoformat(),
        "category": event.category,
        "scores": {
            "total": event.score_total,
            "importance": event.score_importance,
            "attention": event.score_attention,
            "discussion": event.score_discussion,
        },
    }


def build_candidate_payload(
    window: ReportWindow,
    grouped: dict[str, list[Event]],
    arena: list[ArenaEntry],
    statuses: list[SourceStatus],
    max_items: int,
    candidate_pool_size: int,
) -> dict[str, Any]:
    success_names = [status.name for status in statuses if status.ok]
    failed_sources = [
        {"name": status.name, "detail": status.detail}
        for status in statuses
        if not status.ok
    ]
    sections = []
    for section_id in ("AICoding", "AI行业", "AI工具"):
        sections.append(
            {
                "id": section_id,
                "title": f"{section_id} Top {max_items}",
                "max_items": max_items,
                "items": [
                    serialize_event_candidate(event, rank)
                    for rank, event in enumerate(grouped[section_id], start=1)
                ],
            }
        )
    arena_payload = [
        {
            "rank": index,
            "name": entry.name,
            "entity": entry.entity,
            "score": round(entry.score, 1),
            "volume": entry.volume,
            "avg_sentiment": round(entry.avg_sentiment, 2),
            "highlight_url": entry.highlight_url,
            "highlight_text": entry.highlight_text,
        }
        for index, entry in enumerate(arena, start=1)
    ]
    return {
        "metadata": {
            "mode": window.mode,
            "report_title": "AI 日报" if window.mode == "daily" else "AI 周报",
            "report_date": render_report_date(window),
            "timezone": str(window.timezone),
            "max_items": max_items,
            "candidate_pool_size": candidate_pool_size,
            "news_sources": success_names,
            "failed_sources": failed_sources,
        },
        "sections": sections,
        "arena": arena_payload,
    }


def render_datetime(dt: datetime | None, tz: ZoneInfo) -> str:
    if dt is None:
        return "未知"
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S %Z")


def render_report_date(window: ReportWindow) -> str:
    start_date = window.start.astimezone(window.timezone).date()
    end_date = (window.end.astimezone(window.timezone) - timedelta(seconds=1)).date()
    if start_date == end_date:
        return start_date.isoformat()
    return f"{start_date.isoformat()} ~ {end_date.isoformat()}"


def markdown_link_text(value: str) -> str:
    return value.replace("[", "\\[").replace("]", "\\]")


def render_event(event: Event, rank: int, tz: ZoneInfo) -> str:
    title = clean_text(event.display_title or chinese_title(event.title, event.category))
    summary = clean_text(event.display_summary or chinese_summary(event.title, event.prepared_summary or event.summary, event.category, DEFAULT_SUMMARY_LIMIT))
    title_link = f"[{markdown_link_text(title)}]({event.canonical_url})"
    source_label = ", ".join(event.source_names) if event.source_names else "未知"
    child_indent = " " * len(f"{rank}. ")
    lines = [f"{rank}. {title_link}"]
    if summary:
        lines.append(f"{child_indent}- 摘要：{summary}")
    lines.append(f"{child_indent}- 来源：{source_label}")
    return "\n".join(lines)


def render_arena(entries: list[ArenaEntry]) -> str:
    if not entries:
        return "## 模型讨论度排行（daily.dev Arena）\n\n- 无可用数据"
    lines = [
        "## 模型讨论度排行（daily.dev Arena）",
        "",
        "| 排名 | 模型/工具 | 热度分 | 7天讨论量 | 平均情绪 | 代表性讨论 |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for idx, entry in enumerate(entries, start=1):
        link = entry.highlight_url or ""
        label = f"[链接]({link})" if link else "-"
        lines.append(
            f"| {idx} | {entry.name} | {entry.score:.1f} | {entry.volume} | {entry.avg_sentiment:.2f} | {label} |"
        )
    return "\n".join(lines)


def render_payload_item(item: dict[str, Any], rank: int) -> str:
    title = clean_text(str(item.get("title") or item.get("display_title") or item.get("original_title") or ""))
    url = clean_text(str(item.get("url") or ""))
    summary = clean_text(str(item.get("summary") or item.get("display_summary") or ""))
    source_names = item.get("source_names") or []
    source_label = ", ".join(str(name) for name in source_names) if source_names else "未知"
    child_indent = " " * len(f"{rank}. ")
    lines = [f"{rank}. [{markdown_link_text(title)}]({url})"]
    if summary:
        lines.append(f"{child_indent}- 摘要：{collapse_summary(summary, DEFAULT_SUMMARY_LIMIT)}")
    lines.append(f"{child_indent}- 来源：{source_label}")
    return "\n".join(lines)


def render_arena_payload(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return "## 模型讨论度排行（daily.dev Arena）\n\n- 无可用数据"
    lines = [
        "## 模型讨论度排行（daily.dev Arena）",
        "",
        "| 排名 | 模型/工具 | 热度分 | 7天讨论量 | 平均情绪 | 代表性讨论 |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for entry in entries:
        link = clean_text(str(entry.get("highlight_url") or ""))
        label = f"[链接]({link})" if link else "-"
        lines.append(
            f"| {int(entry.get('rank') or 0)} | {clean_text(str(entry.get('name') or ''))} | "
            f"{float(entry.get('score') or 0.0):.1f} | {int(entry.get('volume') or 0)} | "
            f"{float(entry.get('avg_sentiment') or 0.0):.2f} | {label} |"
        )
    return "\n".join(lines)


def render_payload_report(payload: dict[str, Any]) -> str:
    metadata = payload.get("metadata") or {}
    report_title = clean_text(str(metadata.get("report_title") or "AI 日报"))
    report_date = clean_text(str(metadata.get("report_date") or ""))
    news_sources = metadata.get("news_sources") or []
    lines = [
        f"# {report_title}",
        "",
        f"- 日期：{report_date}",
        f"- 新闻来源：{', '.join(str(name) for name in news_sources) if news_sources else '无'}",
        "",
    ]
    for section in payload.get("sections") or []:
        section_title = clean_text(str(section.get("title") or ""))
        lines.append(f"## {section_title}")
        lines.append("")
        items = section.get("items") or []
        if items:
            for rank, item in enumerate(items, start=1):
                lines.append(render_payload_item(item, rank))
                lines.append("")
        else:
            lines.append("- 无符合条件的条目")
            lines.append("")
    if metadata.get("mode") == "weekly":
        lines.append(render_arena_payload(payload.get("arena") or []))
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_report(
    window: ReportWindow,
    grouped: dict[str, list[Event]],
    arena: list[ArenaEntry],
    statuses: list[SourceStatus],
) -> str:
    success_names = [status.name for status in statuses if status.ok]
    title = "AI 日报" if window.mode == "daily" else "AI 周报"
    lines = [
        f"# {title}",
        "",
        f"- 日期：{render_report_date(window)}",
        f"- 新闻来源：{', '.join(success_names) if success_names else '无'}",
        "",
    ]
    for section in ("AICoding", "AI行业", "AI工具"):
        lines.append(f"## {section} Top 10")
        lines.append("")
        if grouped[section]:
            for idx, event in enumerate(grouped[section], start=1):
                lines.append(render_event(event, idx, window.timezone))
                lines.append("")
        else:
            lines.append("- 无符合条件的条目")
            lines.append("")
    if window.mode == "weekly":
        lines.append(render_arena(arena))
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def maybe_fetch_with_browser(url: str) -> str | None:
    agent_browser = shutil.which("agent-browser")
    chrome_path = discover_chrome_path()
    if not agent_browser or not chrome_path:
        return None
    port = str(discover_debug_port())
    profile_dir = Path(tempfile.mkdtemp(prefix="ai-news-digest-chrome-"))
    chrome = subprocess.Popen(
        [
            chrome_path,
            f"--remote-debugging-port={port}",
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            f"--user-data-dir={profile_dir}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        subprocess.run([agent_browser, "connect", port], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run([agent_browser, "open", url], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        result = subprocess.run(
            [agent_browser, "eval", "document.documentElement.outerHTML"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except Exception:
        return None
    finally:
        try:
            subprocess.run([agent_browser, "close"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        finally:
            try:
                chrome.terminate()
                chrome.wait(timeout=5)
            except Exception:
                chrome.kill()
            shutil.rmtree(profile_dir, ignore_errors=True)


def discover_chrome_path() -> str | None:
    candidates: list[str | None] = [
        os.environ.get("CHROME_PATH"),
        os.environ.get("CHROMIUM_PATH"),
        os.environ.get("BROWSER_BIN"),
    ]
    candidates.extend(
        shutil.which(name)
        for name in (
            "google-chrome",
            "google-chrome-stable",
            "chromium",
            "chromium-browser",
            "chrome",
            "msedge",
            "microsoft-edge",
            "brave-browser",
        )
    )
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def discover_debug_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def choose_smol_issue_urls(
    session: requests.Session,
    window: ReportWindow,
    fixture_dir: Path | None,
    index_url: str = "https://news.smol.ai/issues",
    fixture_name: str | None = "smol_issues.html",
) -> list[str]:
    html_text = fetch_text(session, index_url, fixture_dir, fixture_name)
    soup = get_soup(html_text)
    urls = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        match = re.match(r"/issues/(\d{2})-(\d{2})-(\d{2})-", href)
        if not match:
            continue
        year, month, day = match.groups()
        issue_date = date(2000 + int(year), int(month), int(day))
        issue_start = datetime.combine(issue_date, time.min, tzinfo=window.timezone)
        issue_end = issue_start + timedelta(days=1)
        if issue_end > window.start and issue_start < window.end:
            urls.append(urljoin(index_url, href))
    return list(dict.fromkeys(urls))


def parse_smol_issue(
    session: requests.Session,
    issue_url: str,
    window: ReportWindow,
    fixture_dir: Path | None,
    source_name: str = "smol-ai",
    fixture_name: str | None = "smol_issue.html",
) -> list[RawItem]:
    html_text = fetch_text(session, issue_url, fixture_dir, fixture_name if fixture_dir else None)
    soup = get_soup(html_text)
    issue_date_match = re.search(r"/issues/(\d{2})-(\d{2})-(\d{2})-", issue_url)
    issue_date = None
    if issue_date_match:
        year, month, day = issue_date_match.groups()
        issue_date = datetime(2000 + int(year), int(month), int(day), 12, 0, tzinfo=window.timezone)
    items: list[RawItem] = []
    seen = set()
    toc_entries = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        text = clean_text(anchor.get_text(" ", strip=True))
        if not href.startswith("#") or not re.match(r"^\d+\.", text):
            continue
        if href in seen:
            continue
        seen.add(href)
        toc_entries.append((href[1:], text))
    for index, (section_id, title) in enumerate(toc_entries, start=1):
        section = soup.find(id=section_id)
        if not section:
            continue
        title = re.sub(r"^\d+\.\s*", "", title)
        summary = ""
        node = section
        while node:
            node = node.find_next_sibling()
            if node is None or node.name in {"h1", "h2", "h3"}:
                break
            if node.name == "p":
                summary = clean_text(node.get_text(" ", strip=True))
                if summary:
                    break
        items.append(
            RawItem(
                source_name=source_name,
                source_type="daily",
                title=title,
                summary=summary,
                url=f"{issue_url}#{section_id}",
                published_at=issue_date,
                observed_at=datetime.now(window.timezone),
                position=index,
            )
        )
    return items


def parse_hn_front(
    session: requests.Session,
    window: ReportWindow,
    fixture_dir: Path | None,
    url: str = "https://news.ycombinator.com/",
    fixture_name: str | None = "hn_front.html",
    source_name: str = "hacker-news-front",
) -> list[RawItem]:
    html_text = fetch_text(session, url, fixture_dir, fixture_name)
    soup = get_soup(html_text)
    now = window_reference_time(window)
    items: list[RawItem] = []
    for index, row in enumerate(soup.select("tr.athing"), start=1):
        title_anchor = row.select_one(".titleline a")
        if not title_anchor:
            continue
        title = clean_text(title_anchor.get_text(" ", strip=True))
        link = title_anchor.get("href") or ""
        full_link = urljoin(url, link)
        sub = row.find_next_sibling("tr")
        subtext = clean_text(sub.get_text(" ", strip=True) if sub else "")
        if not is_ai_relevant(title, subtext, full_link):
            continue
        points_match = re.search(r"(\d+)\s+points?", subtext)
        comments_match = re.search(r"(\d+)\s+comments?", subtext)
        published_at = parse_relative_time(subtext, now, window.timezone)
        if published_at and not within_window(published_at, window):
            continue
        items.append(
                RawItem(
                    source_name=source_name,
                    source_type="daily",
                    title=title,
                    summary="",
                    url=full_link,
                    published_at=published_at,
                    observed_at=now,
                position=index,
                metrics={
                    "points": float(points_match.group(1)) if points_match else 0.0,
                    "comments": float(comments_match.group(1)) if comments_match else 0.0,
                },
            )
        )
    return items


def parse_hn_algolia(
    session: requests.Session,
    window: ReportWindow,
    api_url: str = ALGOLIA_API,
    source_name: str = "hn-algolia",
    queries: Iterable[str] = HN_QUERIES,
) -> list[RawItem]:
    start_ts = int(window.start.timestamp())
    end_ts = int(window.end.timestamp())
    items: list[RawItem] = []
    seen_ids = set()
    for query in queries:
        response = session.get(
            api_url,
            params={
                "query": query,
                "tags": "story",
                "hitsPerPage": 20,
                "numericFilters": f"created_at_i>{start_ts},created_at_i<{end_ts}",
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        for hit in data.get("hits", []):
            object_id = hit.get("objectID")
            if not object_id or object_id in seen_ids:
                continue
            title = clean_text(hit.get("title") or "")
            if not title:
                continue
            summary = clean_text(hit.get("story_text") or hit.get("comment_text") or "")
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}"
            if not is_ai_relevant(title, summary, url):
                continue
            seen_ids.add(object_id)
            published_at = datetime.fromtimestamp(hit.get("created_at_i", start_ts), tz=timezone.utc).astimezone(window.timezone)
            items.append(
                RawItem(
                    source_name=source_name,
                    source_type="daily",
                    title=title,
                    summary=summary,
                    url=url,
                    published_at=published_at,
                    observed_at=datetime.now(window.timezone),
                    position=len(items) + 1,
                    metrics={
                        "points": float(hit.get("points") or 0.0),
                        "comments": float(hit.get("num_comments") or 0.0),
                    },
                )
            )
    return items


def load_next_data(html_text: str) -> dict[str, Any]:
    if "__NEXT_DATA__" not in html_text and html_text.startswith('"') and html_text.endswith('"'):
        try:
            html_text = json.loads(html_text)
        except json.JSONDecodeError:
            pass
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html_text, re.S)
    if not match:
        raise ValueError("页面中未找到 __NEXT_DATA__")
    return json.loads(match.group(1))


def parse_daily_dev_highlights(
    session: requests.Session,
    window: ReportWindow,
    fixture_dir: Path | None,
    url: str = "https://app.daily.dev/agents",
    fixture_name: str | None = "daily_agents.html",
    source_name: str = "daily-dev-highlights",
) -> list[RawItem]:
    html_text = fetch_text(session, url, fixture_dir, fixture_name)
    data = load_next_data(html_text)
    items: list[RawItem] = []
    queries = data.get("props", {}).get("pageProps", {}).get("dehydratedState", {}).get("queries", [])
    for query in queries:
        if query.get("queryKey") != ["post_highlights", "anonymous", "vibes"]:
            continue
        highlights = query.get("state", {}).get("data", {}).get("postHighlights", [])
        for index, highlight in enumerate(highlights, start=1):
            published_at = parse_iso_datetime(highlight["highlightedAt"], window.timezone)
            if not within_window(published_at, window):
                continue
            items.append(
                RawItem(
                    source_name=source_name,
                    source_type="daily",
                    title=clean_text(highlight.get("headline") or ""),
                    summary="",
                    url=highlight.get("post", {}).get("commentsPermalink") or url,
                    published_at=published_at,
                    observed_at=datetime.now(window.timezone),
                    position=index,
                )
            )
        break
    return items


def parse_daily_dev_arena(
    session: requests.Session,
    window: ReportWindow,
    fixture_dir: Path | None,
    url: str = "https://app.daily.dev/agents/arena",
    fixture_name: str | None = "daily_arena.html",
) -> tuple[list[RawItem], list[ArenaEntry]]:
    html_text = fetch_text(session, url, fixture_dir, fixture_name)
    return parse_daily_dev_arena_html(html_text, window)


def parse_daily_dev_arena_html(
    html_text: str,
    window: ReportWindow,
) -> tuple[list[RawItem], list[ArenaEntry]]:
    data = load_next_data(html_text)
    arena_payload: dict[str, Any] | None = None
    for query in data.get("props", {}).get("pageProps", {}).get("dehydratedState", {}).get("queries", []):
        if query.get("queryKey") == ["arena", "anonymous", "coding-agents"]:
            arena_payload = query.get("state", {}).get("data")
            break
    if not arena_payload:
        return [], []

    entities = {
        entity["entity"]: entity["name"]
        for entity in arena_payload["sentimentGroup"]["entities"]
    }
    series_nodes = {
        node["entity"]: node for node in arena_payload["sentimentTimeSeries"]["entities"]["nodes"]
    }
    highlight_items = arena_payload.get("sentimentHighlights", {}).get("items", [])

    highlights_by_entity: dict[str, dict[str, Any]] = {}
    for highlight in highlight_items:
        interaction_score = (
            float(highlight.get("metrics", {}).get("likeCount", 0))
            + 2 * float(highlight.get("metrics", {}).get("replyCount", 0))
            + 2 * float(highlight.get("metrics", {}).get("retweetCount", 0))
        )
        for sentiment in highlight.get("sentiments", []):
            entity_key = sentiment.get("entity")
            if not entity_key:
                continue
            candidate = {
                "url": highlight.get("url"),
                "text": clean_text(highlight.get("text") or ""),
                "score": interaction_score * float(sentiment.get("highlightScore", 0.0) or 0.0),
            }
            current = highlights_by_entity.get(entity_key)
            if current is None or candidate["score"] > current["score"]:
                highlights_by_entity[entity_key] = candidate

    arena_entries: list[ArenaEntry] = []
    for index, (entity_key, name) in enumerate(entities.items(), start=1):
        node = series_nodes.get(entity_key) or {}
        volume_values = node.get("volume", [])
        scores = node.get("scores", [])
        d_index = node.get("dIndex", [])
        total_volume = int(sum(volume_values))
        avg_sentiment = (sum(scores) / len(scores)) if scores else 0.0
        avg_d_index = (sum(d_index) / len(d_index)) if d_index else 0.0
        highlight = highlights_by_entity.get(entity_key, {})
        highlight_bonus = float(highlight.get("score", 0.0))
        score = min(
            100.0,
            14.0 * math.log10(total_volume + 1.0)
            + min(20.0, max(0.0, avg_d_index) * 10.0)
            + max(0.0, avg_sentiment) * 15.0
            + min(8.0, highlight_bonus / 200.0),
        )
        arena_entries.append(
            ArenaEntry(
                name=name,
                entity=entity_key,
                score=score,
                volume=total_volume,
                avg_sentiment=avg_sentiment,
                highlight_url=highlight.get("url"),
                highlight_text=highlight.get("text", ""),
            )
        )
    arena_entries.sort(key=lambda entry: entry.score, reverse=True)
    return [], arena_entries[:10]


def parse_ai_bot(
    session: requests.Session,
    window: ReportWindow,
    fixture_dir: Path | None,
    url: str = "https://ai-bot.cn/daily-ai-news/",
    fixture_name: str | None = "ai_bot.html",
    source_name: str = "ai-bot",
) -> list[RawItem]:
    html_text = fetch_text(session, url, fixture_dir, fixture_name)
    soup = get_soup(html_text)
    observed = datetime.now(window.timezone)
    meta = soup.find("meta", attrs={"property": "og:updated_time"}) or soup.find(
        "meta", attrs={"property": "article:modified_time"}
    )
    if meta and meta.get("content"):
        try:
            observed = parse_iso_datetime(meta["content"], window.timezone)
        except ValueError:
            observed = datetime.now(window.timezone)
    items: list[RawItem] = []
    for index, block in enumerate(soup.select("div.news-content"), start=1):
        heading = block.select_one("h2 a")
        summary_tag = block.select_one("p")
        if not heading:
            continue
        items.append(
            RawItem(
                source_name=source_name,
                source_type="daily",
                title=clean_text(heading.get_text(" ", strip=True)),
                summary=clean_text(summary_tag.get_text(" ", strip=True) if summary_tag else ""),
                url=heading.get("href") or url,
                published_at=None,
                observed_at=observed,
                position=index,
                notes=["rolling-daily-feed", "observed_at_only"],
            )
        )
    return items


def parse_aibase(
    session: requests.Session,
    window: ReportWindow,
    fixture_dir: Path | None,
    url: str = "https://news.aibase.com/zh/news",
    fixture_name: str | None = "aibase.html",
    source_name: str = "aibase",
) -> list[RawItem]:
    html_text = fetch_text(session, url, fixture_dir, fixture_name)
    soup = get_soup(html_text)
    observed = window_reference_time(window)
    items: list[RawItem] = []
    for index, anchor in enumerate(soup.find_all("a", href=lambda href: href and "/zh/news/" in href), start=1):
        title_tag = anchor.select_one(".font600")
        summary_tag = anchor.select_one(".tipColor.truncate2")
        if not title_tag:
            continue
        meta_text = clean_text(anchor.get_text(" ", strip=True))
        relative = parse_relative_time(meta_text, observed, window.timezone)
        views_match = re.search(r"(\d+(?:\.\d+)?)K", meta_text, re.I)
        items.append(
                RawItem(
                    source_name=source_name,
                    source_type="daily",
                    title=clean_text(title_tag.get_text(" ", strip=True)),
                    summary=clean_text(summary_tag.get_text(" ", strip=True) if summary_tag else ""),
                    url=urljoin(url, anchor.get("href") or ""),
                    published_at=relative,
                    observed_at=observed,
                position=index,
                metrics={"views": float(views_match.group(1)) * 1000 if views_match else 0.0},
            )
        )
    return items


def parse_maomu(
    session: requests.Session,
    window: ReportWindow,
    fixture_dir: Path | None,
    url: str = "https://www.maomu.com/news",
    fixture_name: str | None = "maomu.html",
    source_name: str = "maomu",
) -> list[RawItem]:
    html_text = fetch_text(session, url, fixture_dir, fixture_name)
    soup = get_soup(html_text)
    observed = window_reference_time(window)
    items: list[RawItem] = []
    for index, anchor in enumerate(soup.select("a.news-item"), start=1):
        text = clean_text(anchor.get_text(" ", strip=True))
        title = re.sub(r"^(刚刚|\d+\s*(?:分钟|小时|天)前)\s*", "", text)
        if not title:
            continue
        items.append(
                RawItem(
                    source_name=source_name,
                    source_type="daily",
                    title=title,
                    summary="",
                    url=anchor.get("href") or url,
                    published_at=parse_relative_time(text, observed, window.timezone),
                    observed_at=observed,
                position=index,
            )
        )
    return items


def parse_github_trending(
    session: requests.Session,
    window: ReportWindow,
    fixture_dir: Path | None,
    url: str = "https://github.com/trending",
    fixture_name: str | None = "github_trending.html",
    source_name: str = "github-trending",
) -> list[RawItem]:
    html_text = fetch_text(session, url, fixture_dir, fixture_name)
    soup = get_soup(html_text)
    observed = datetime.now(window.timezone)
    items: list[RawItem] = []
    for index, article in enumerate(soup.select("article.Box-row"), start=1):
        title_anchor = article.select_one("h2 a")
        if not title_anchor:
            continue
        desc = clean_text(article.select_one("p").get_text(" ", strip=True) if article.select_one("p") else "")
        title = clean_text(title_anchor.get_text(" ", strip=True))
        url = urljoin("https://github.com", title_anchor.get("href") or "")
        if not is_ai_relevant(title, desc, url):
            continue
        stars_text = article.find(string=lambda s: isinstance(s, str) and "stars today" in s.lower())
        stars_today = 0.0
        if stars_text:
            match = re.search(r"([\d,]+)", stars_text)
            if match:
                stars_today = float(match.group(1).replace(",", ""))
        items.append(
                RawItem(
                    source_name=source_name,
                    source_type="daily",
                    title=title,
                    summary=desc or "",
                    url=url,
                    published_at=None,
                    observed_at=observed,
                position=index,
                metrics={"stars_today": stars_today},
                notes=["observed_at_only"],
            )
        )
    return items


def parse_search_recall(
    session: requests.Session,
    window: ReportWindow,
    config: SourceConfig,
) -> list[RawItem]:
    provider = str(config.params.get("provider") or "gdelt_doc")
    if provider not in {"gdelt_doc", "google_news_rss"}:
        raise ValueError(f"unsupported search recall provider: {provider}")

    max_records = max(1, min(50, int(config.params.get("max_records_per_query") or 5)))
    max_total = max(1, int(config.params.get("max_total_items") or 80))
    dimensions = config.params.get("dimensions") or []
    if not isinstance(dimensions, list):
        raise ValueError("search recall dimensions must be a list")

    items: list[RawItem] = []
    seen_urls: set[str] = set()
    failures = 0
    attempts = 0
    observed = window_reference_time(window)
    for raw_dimension in dimensions:
        if not isinstance(raw_dimension, dict):
            continue
        dimension_key = str(raw_dimension.get("key") or "general")
        dimension_label = str(raw_dimension.get("label") or dimension_key)
        dimension_weight = float(raw_dimension.get("weight") or 1.0)
        queries = raw_dimension.get("queries") or []
        if not isinstance(queries, list):
            continue
        for template in queries:
            query = expand_search_query(str(template), window)
            if not query:
                continue
            attempts += 1
            try:
                articles = fetch_search_recall_articles(session, config, provider, query, max_records, window)
            except Exception:
                failures += 1
                continue

            for result_position, article in enumerate(articles, start=1):
                if len(items) >= max_total:
                    return items
                if not isinstance(article, dict):
                    continue
                title = clean_text(str(article.get("title") or ""))
                url = clean_text(str(article.get("url") or article.get("url_mobile") or ""))
                if not title or not url:
                    continue
                normalized = normalize_url(url)
                if normalized in seen_urls:
                    continue

                snippet = clean_text(str(article.get("snippet") or article.get("description") or ""))
                if not is_search_recall_relevant(title, snippet, url, dimension_key):
                    continue
                if not has_obvious_summary(snippet, title):
                    snippet = ""

                published_value = article.get("published_at")
                published_at = published_value.astimezone(window.timezone) if isinstance(published_value, datetime) else None
                if published_at is None:
                    published_at = parse_compact_datetime(str(article.get("seendate") or ""), window.timezone)
                if published_at and not within_window(published_at, window):
                    continue

                seen_urls.add(normalized)
                items.append(
                    RawItem(
                        source_name=config.id,
                        source_type=window.mode,
                        title=title,
                        summary=snippet,
                        url=url,
                        published_at=published_at,
                        observed_at=observed,
                        position=len(items) + 1,
                        metrics={
                            "dimension_weight": dimension_weight,
                            "result_position": float(result_position),
                            "community_dimension": 1.0 if dimension_key == "community" else 0.0,
                        },
                        notes=[
                            f"search_dimension:{dimension_key}",
                            f"search_query:{query}",
                        ],
                    )
                )

    if attempts > 0 and failures == attempts:
        raise RuntimeError("all search recall queries failed")
    return items


def fetch_search_recall_articles(
    session: requests.Session,
    config: SourceConfig,
    provider: str,
    query: str,
    max_records: int,
    window: ReportWindow,
) -> list[dict[str, Any]]:
    if provider == "gdelt_doc":
        response = session.get(
            config.url,
            params={
                "query": query,
                "mode": "ArtList",
                "format": "json",
                "maxrecords": max_records,
                "sort": "HybridRel",
                "startdatetime": compact_utc_datetime(window.start),
                "enddatetime": compact_utc_datetime(window.end),
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return list(response.json().get("articles", []))

    response = session.get(
        config.url,
        params={
            "q": query,
            "hl": str(config.params.get("hl") or "en-US"),
            "gl": str(config.params.get("gl") or "US"),
            "ceid": str(config.params.get("ceid") or "US:en"),
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return parse_google_news_search_items(response.text, max_records, window)


def parse_google_news_search_items(xml_text: str, max_records: int, window: ReportWindow) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    articles: list[dict[str, Any]] = []
    for node in root.findall("./channel/item"):
        if len(articles) >= max_records:
            break
        title = clean_text(node.findtext("title") or "")
        link = clean_text(node.findtext("link") or "")
        if not title or not link:
            continue
        source_node = node.find("source")
        source_name = clean_text(source_node.text if source_node is not None and source_node.text else "")
        source_domain = ""
        if source_node is not None and source_node.get("url"):
            source_domain = clean_text(urlparse(source_node.get("url") or "").netloc)
        description = clean_text(strip_html_fragments(node.findtext("description") or ""))
        published_at = parse_http_datetime(node.findtext("pubDate") or "", window.timezone)
        articles.append(
            {
                "title": title,
                "url": link,
                "snippet": description,
                "published_at": published_at,
                "domain": source_name or source_domain,
            }
        )
    return articles


def parse_feed_items(
    xml_text: str,
    source_name: str,
    window: ReportWindow,
    filter_func: Callable[[str, str], bool] | None = None,
) -> list[RawItem]:
    root = ET.fromstring(xml_text)
    items: list[RawItem] = []
    for index, node in enumerate(root.findall("./channel/item"), start=1):
        title = clean_text(node.findtext("title") or "")
        link = clean_text(node.findtext("link") or "")
        if not title or not link:
            continue
        if filter_func and not filter_func(title, link):
            continue
        published_at = parse_http_datetime(node.findtext("pubDate") or "", window.timezone)
        if published_at and not within_window(published_at, window):
            continue
        items.append(
            RawItem(
                source_name=source_name,
                source_type="weekly",
                title=title,
                summary=clean_text(node.findtext("description") or ""),
                url=link,
                published_at=published_at,
                observed_at=datetime.now(window.timezone),
                position=index,
            )
        )
    return items


def parse_thursdai(
    session: requests.Session,
    window: ReportWindow,
    fixture_dir: Path | None,
    url: str = "https://sub.thursdai.news/feed",
    fixture_name: str | None = "thursdai_feed.xml",
    source_name: str = "thursdai",
) -> list[RawItem]:
    xml_text = fetch_text(session, url, fixture_dir, fixture_name)
    return parse_feed_items(xml_text, source_name, window)


def parse_latent_ainews(
    session: requests.Session,
    window: ReportWindow,
    fixture_dir: Path | None,
    url: str = "https://www.latent.space/feed",
    fixture_name: str | None = "latent_feed.xml",
    source_name: str = "latent-ainews",
) -> list[RawItem]:
    xml_text = fetch_text(session, url, fixture_dir, fixture_name)
    return parse_feed_items(
        xml_text,
        source_name,
        window,
        filter_func=lambda title, link: title.startswith("[AINews]") or "/p/ainews-" in link,
    )


def source_param_list(config: SourceConfig, key: str, default: Iterable[str]) -> list[str]:
    value = config.params.get(key)
    if isinstance(value, list):
        return [str(item) for item in value]
    return list(default)


def build_feed_filter(params: dict[str, Any]) -> Callable[[str, str], bool] | None:
    title_prefix = str(params.get("title_prefix") or "")
    link_contains = str(params.get("link_contains") or "")
    if not title_prefix and not link_contains:
        return None

    def filter_func(title: str, link: str) -> bool:
        return bool((title_prefix and title.startswith(title_prefix)) or (link_contains and link_contains in link))

    return filter_func


def parse_smol_source(
    config: SourceConfig,
    session: requests.Session,
    window: ReportWindow,
    fixture_dir: Path | None,
) -> list[RawItem]:
    issue_fixture = str(config.params.get("issue_fixture") or "smol_issue.html")
    return [
        parsed_item
        for issue_url in choose_smol_issue_urls(session, window, fixture_dir, config.url, config.fixture)
        for parsed_item in parse_smol_issue(session, issue_url, window, fixture_dir, config.id, issue_fixture)
    ]


def parse_hn_front_source(
    config: SourceConfig,
    session: requests.Session,
    window: ReportWindow,
    fixture_dir: Path | None,
) -> list[RawItem]:
    return parse_hn_front(session, window, fixture_dir, config.url, config.fixture, config.id)


def parse_hn_algolia_source(
    config: SourceConfig,
    session: requests.Session,
    window: ReportWindow,
    fixture_dir: Path | None,
) -> list[RawItem]:
    return parse_hn_algolia(session, window, config.url, config.id, source_param_list(config, "queries", HN_QUERIES))


def parse_daily_dev_highlights_source(
    config: SourceConfig,
    session: requests.Session,
    window: ReportWindow,
    fixture_dir: Path | None,
) -> list[RawItem]:
    return parse_daily_dev_highlights(session, window, fixture_dir, config.url, config.fixture, config.id)


def parse_ai_bot_source(
    config: SourceConfig,
    session: requests.Session,
    window: ReportWindow,
    fixture_dir: Path | None,
) -> list[RawItem]:
    return parse_ai_bot(session, window, fixture_dir, config.url, config.fixture, config.id)


def parse_aibase_source(
    config: SourceConfig,
    session: requests.Session,
    window: ReportWindow,
    fixture_dir: Path | None,
) -> list[RawItem]:
    return parse_aibase(session, window, fixture_dir, config.url, config.fixture, config.id)


def parse_maomu_source(
    config: SourceConfig,
    session: requests.Session,
    window: ReportWindow,
    fixture_dir: Path | None,
) -> list[RawItem]:
    return parse_maomu(session, window, fixture_dir, config.url, config.fixture, config.id)


def parse_github_trending_source(
    config: SourceConfig,
    session: requests.Session,
    window: ReportWindow,
    fixture_dir: Path | None,
) -> list[RawItem]:
    return parse_github_trending(session, window, fixture_dir, config.url, config.fixture, config.id)


def parse_search_recall_source(
    config: SourceConfig,
    session: requests.Session,
    window: ReportWindow,
    fixture_dir: Path | None,
) -> list[RawItem]:
    return parse_search_recall(session, window, config)


def parse_rss_feed_source(
    config: SourceConfig,
    session: requests.Session,
    window: ReportWindow,
    fixture_dir: Path | None,
) -> list[RawItem]:
    xml_text = fetch_text(session, config.url, fixture_dir, config.fixture)
    return parse_feed_items(xml_text, config.id, window, filter_func=build_feed_filter(config.params))


def parse_daily_dev_arena_source(
    config: SourceConfig,
    session: requests.Session,
    window: ReportWindow,
    fixture_dir: Path | None,
) -> tuple[list[RawItem], list[ArenaEntry]]:
    return parse_daily_dev_arena(session, window, fixture_dir, config.url, config.fixture)


NEWS_SOURCE_PARSERS: dict[
    str,
    Callable[[SourceConfig, requests.Session, ReportWindow, Path | None], list[RawItem]],
] = {
    "smol_issue": parse_smol_source,
    "hn_front": parse_hn_front_source,
    "hn_algolia": parse_hn_algolia_source,
    "daily_dev_highlights": parse_daily_dev_highlights_source,
    "ai_bot": parse_ai_bot_source,
    "aibase": parse_aibase_source,
    "maomu": parse_maomu_source,
    "github_trending": parse_github_trending_source,
    "search_recall": parse_search_recall_source,
    "rss_feed": parse_rss_feed_source,
}


ARENA_SOURCE_PARSERS: dict[
    str,
    Callable[[SourceConfig, requests.Session, ReportWindow, Path | None], tuple[list[RawItem], list[ArenaEntry]]],
] = {
    "daily_dev_arena": parse_daily_dev_arena_source,
}


def gather_news_sources(
    session: requests.Session,
    window: ReportWindow,
    fixture_dir: Path | None,
    source_configs: list[SourceConfig],
) -> tuple[list[RawItem], list[SourceStatus]]:
    items: list[RawItem] = []
    statuses: list[SourceStatus] = []
    for config in source_configs:
        if not config.supports(window.mode, "news"):
            continue
        parser = NEWS_SOURCE_PARSERS.get(config.parser)
        if parser is None:
            statuses.append(SourceStatus(config.name, False, f"unsupported parser: {config.parser}"))
            continue
        try:
            chunk = parser(config, session, window, fixture_dir)
            items.extend(chunk)
            statuses.append(SourceStatus(config.name, True, f"{len(chunk)} 条"))
        except Exception as exc:  # pragma: no cover - exercised via runtime
            statuses.append(SourceStatus(config.name, False, str(exc)))
    return items, statuses


def gather_daily_sources(
    session: requests.Session,
    window: ReportWindow,
    fixture_dir: Path | None,
    source_configs: list[SourceConfig] | None = None,
) -> tuple[list[RawItem], list[ArenaEntry], list[SourceStatus]]:
    if source_configs is None:
        source_configs = load_source_configs()
    arena_entries: list[ArenaEntry] = []
    items, statuses = gather_news_sources(session, window, fixture_dir, source_configs)
    return items, arena_entries, statuses


def gather_arena_source(
    session: requests.Session,
    window: ReportWindow,
    fixture_dir: Path | None,
    source_configs: list[SourceConfig] | None = None,
) -> tuple[list[ArenaEntry], list[SourceStatus]]:
    if source_configs is None:
        source_configs = load_source_configs()
    arena_entries: list[ArenaEntry] = []
    statuses: list[SourceStatus] = []
    for config in source_configs:
        if not config.supports(window.mode, "arena"):
            continue
        parser = ARENA_SOURCE_PARSERS.get(config.parser)
        if parser is None:
            statuses.append(SourceStatus(config.name, False, f"unsupported parser: {config.parser}"))
            continue
        try:
            arena_items, arena_entries = parser(config, session, window, fixture_dir)
            statuses.append(SourceStatus(config.name, True, f"{len(arena_entries)} 条排行"))
        except Exception as exc:  # pragma: no cover
            statuses.append(SourceStatus(config.name, False, str(exc)))
            if not config.params.get("browser_fallback"):
                continue
            browser_html = maybe_fetch_with_browser(config.url)
            if browser_html:
                try:
                    arena_items, arena_entries = parse_daily_dev_arena_html(browser_html, window)
                    statuses.append(SourceStatus(f"{config.name}-browser", True, f"{len(arena_entries)} 条排行"))
                except Exception as second_exc:  # pragma: no cover
                    statuses.append(SourceStatus(f"{config.name}-browser", False, str(second_exc)))
    return arena_entries, statuses


def gather_weekly_sources(
    session: requests.Session,
    window: ReportWindow,
    fixture_dir: Path | None,
    source_configs: list[SourceConfig] | None = None,
) -> tuple[list[RawItem], list[ArenaEntry], list[SourceStatus]]:
    if source_configs is None:
        source_configs = load_source_configs()
    items, statuses = gather_news_sources(session, window, fixture_dir, source_configs)
    arena_entries, arena_statuses = gather_arena_source(session, window, fixture_dir, source_configs)
    statuses.extend(arena_statuses)
    return items, arena_entries, statuses


def filter_items_by_window(items: list[RawItem], window: ReportWindow) -> list[RawItem]:
    filtered = []
    for item in items:
        if "observed_at_only" in item.notes:
            filtered.append(item)
            continue
        point = item.effective_time()
        if within_window(point, window):
            filtered.append(item)
    return filtered


def main() -> int:
    args = parse_args()
    if args.mode == "render":
        if not args.input_json:
            raise ValueError("render 模式必须提供 --input-json")
        payload = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
        markdown = render_payload_report(payload)
        if args.output:
            Path(args.output).write_text(markdown, encoding="utf-8")
        else:
            sys.stdout.write(markdown)
        return 0

    fixture_dir = Path(args.fixture_dir) if args.fixture_dir else None
    source_config_path = Path(args.sources_config) if args.sources_config else None
    source_configs = load_source_configs(source_config_path)
    window = compute_window(args.mode, args.timezone, args.date_text, args.from_text, args.to_text)
    session = ensure_session()

    if args.mode == "daily":
        raw_items, arena_entries, statuses = gather_daily_sources(session, window, fixture_dir, source_configs)
    else:
        raw_items, arena_entries, statuses = gather_weekly_sources(session, window, fixture_dir, source_configs)

    raw_items = filter_items_by_window(raw_items, window)
    events = merge_items(raw_items)
    candidate_pool_size = max(args.max_items, int(args.candidate_pool_size or args.max_items))
    grouped = group_events(events, window, candidate_pool_size if args.output_json else args.max_items)
    prepare_grouped_events(grouped, session)

    if args.output_json:
        payload = build_candidate_payload(
            window,
            grouped,
            arena_entries,
            statuses,
            args.max_items,
            candidate_pool_size,
        )
        output_json = json.dumps(payload, ensure_ascii=False, indent=2)
        Path(args.output_json).write_text(output_json, encoding="utf-8")
        return 0

    trimmed_grouped = {
        section: items[: args.max_items]
        for section, items in grouped.items()
    }
    markdown = render_report(window, trimmed_grouped, arena_entries, statuses)

    if args.output:
        Path(args.output).write_text(markdown, encoding="utf-8")
    else:
        sys.stdout.write(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
