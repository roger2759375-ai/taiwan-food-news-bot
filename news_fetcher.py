"""
新聞抓取模組 - 從多個來源抓取台灣食安與營養相關新聞
"""

# macOS SSL 憑證修正（Linux/Render 不需要）
import platform, ssl, certifi
if platform.system() == "Darwin":
    ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())

import feedparser
import httpx
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional
from zoneinfo import ZoneInfo

from summarizer import get_bullet_points

logger = logging.getLogger(__name__)

TZ_TAIPEI = ZoneInfo("Asia/Taipei")


@dataclass
class NewsItem:
    title: str
    link: str
    summary: str          # RSS 原始摘要（備援用）
    source: str
    published: Optional[datetime] = None
    bullet_points: list[str] = field(default_factory=list)

    def format_date(self) -> str:
        if self.published:
            return self.published.astimezone(TZ_TAIPEI).strftime("%m/%d %H:%M")
        return ""


# RSS 來源清單
RSS_SOURCES = [
    {
        "name": "食藥署 - 最新訊息",
        "url": "https://www.fda.gov.tw/RSS/rss.aspx?topic=3",
        "emoji": "🏛️",
    },
    {
        "name": "食藥署 - 消費者專區",
        "url": "https://www.fda.gov.tw/RSS/rss.aspx?topic=5",
        "emoji": "🏛️",
    },
    {
        "name": "衛福部 - 最新消息",
        "url": "https://www.mohw.gov.tw/rss-16-1.html",
        "emoji": "🏥",
    },
    {
        "name": "Google新聞 - 食品安全",
        "url": (
            "https://news.google.com/rss/search"
            "?q=台灣+食品安全+OR+食安+OR+食物中毒"
            "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        ),
        "emoji": "🔍",
    },
    {
        "name": "Google新聞 - 食品標示",
        "url": (
            "https://news.google.com/rss/search"
            "?q=台灣+食品標示+OR+違規+OR+下架+OR+回收"
            "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        ),
        "emoji": "🏷️",
    },
    {
        "name": "Google新聞 - 營養健康",
        "url": (
            "https://news.google.com/rss/search"
            "?q=台灣+營養+OR+飲食健康+OR+膳食指南"
            "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        ),
        "emoji": "🥗",
    },
]

KEYWORDS_FOOD_SAFETY = [
    "食安", "食品安全", "食物中毒", "農藥", "添加物", "違規", "下架",
    "回收", "不合格", "殘留", "汙染", "污染", "禁藥", "塑化劑",
    "防腐劑", "標示不實", "過期", "食品", "衛生",
]

KEYWORDS_NUTRITION = [
    "營養", "飲食", "健康", "膳食", "蛋白質", "維生素", "礦物質",
    "熱量", "卡路里", "蔬果", "均衡飲食", "膳食纖維", "益生菌",
    "腸胃", "減重", "體重", "飲食習慣",
]


def _parse_date(entry) -> Optional[datetime]:
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def _clean_text(text: str, max_len: int = 300) -> str:
    import re
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len] + "…" if len(text) > max_len else text


def _is_relevant(title: str, summary: str) -> bool:
    content = title + summary
    return any(kw in content for kw in KEYWORDS_FOOD_SAFETY + KEYWORDS_NUTRITION)


_RSS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TaiwanFoodNewsBot/1.0)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


def _fetch_rss_content(url: str) -> bytes:
    """用 httpx 抓 RSS 內容（繞過 feedparser 內建的 urllib SSL 問題）"""
    resp = httpx.get(url, headers=_RSS_HEADERS, timeout=15, follow_redirects=True)
    resp.raise_for_status()
    return resp.content


def fetch_from_rss(source: dict, hours_back: int = 48) -> list[NewsItem]:
    items: list[NewsItem] = []
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours_back)

    try:
        raw = _fetch_rss_content(source["url"])
        feed = feedparser.parse(raw)
        if feed.bozo and not feed.entries:
            logger.warning("RSS warning for %s: %s", source["name"], feed.bozo_exception)
            return items

        for entry in feed.entries[:20]:
            title = getattr(entry, "title", "").strip()
            link = getattr(entry, "link", "").strip()
            summary_raw = (
                getattr(entry, "summary", "")
                or getattr(entry, "description", "")
                or ""
            )
            summary = _clean_text(summary_raw)
            published = _parse_date(entry)

            if published and published < cutoff:
                continue
            if not title or not link:
                continue

            is_google_news = "news.google.com" in source["url"]
            if not is_google_news and not _is_relevant(title, summary):
                continue

            items.append(
                NewsItem(
                    title=title,
                    link=link,
                    summary=summary,
                    source=f"{source['emoji']} {source['name']}",
                    published=published,
                )
            )
    except Exception as e:
        logger.error("Failed to fetch %s: %s", source["name"], e)

    return items


def _enrich_item(item: NewsItem) -> NewsItem:
    """抓全文 + 整理重點（在 thread pool 中執行）"""
    try:
        item.bullet_points = get_bullet_points(item.title, item.link, item.summary)
    except Exception as e:
        logger.warning("Failed to enrich %s: %s", item.title[:30], e)
    return item


def fetch_all_news(hours_back: int = 48) -> dict[str, list[NewsItem]]:
    """
    從所有來源抓取並分類新聞，同時並行抓取全文 + 整理重點。
    回傳：{"食品安全": [...], "營養知識": [...]}
    """
    food_safety: list[NewsItem] = []
    nutrition: list[NewsItem] = []
    seen_titles: set[str] = set()

    # Step 1: 收集 RSS 條目
    for source in RSS_SOURCES:
        for item in fetch_from_rss(source, hours_back=hours_back):
            norm = item.title[:30]
            if norm in seen_titles:
                continue
            seen_titles.add(norm)

            content = item.title + item.summary
            if any(kw in content for kw in KEYWORDS_FOOD_SAFETY):
                food_safety.append(item)
            elif any(kw in content for kw in KEYWORDS_NUTRITION):
                nutrition.append(item)

    # 排序後取前 N 筆再抓全文（控制 API 費用）
    food_safety.sort(
        key=lambda x: x.published or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    nutrition.sort(
        key=lambda x: x.published or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    to_enrich = food_safety[:6] + nutrition[:4]

    # Step 2: 並行抓全文 + 整理重點
    if to_enrich:
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_enrich_item, item): item for item in to_enrich}
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.warning("Enrich task error: %s", e)

    return {
        "食品安全": food_safety[:6],
        "營養知識": nutrition[:4],
    }


def format_news_message(news_dict: dict[str, list[NewsItem]]) -> str:
    """將新聞整理成 Telegram MarkdownV2 訊息"""
    now_str = datetime.now(tz=TZ_TAIPEI).strftime("%Y年%m月%d日 %H:%M")
    lines = [
        "🗞 *台灣食安 \\& 營養日報*",
        f"📅 {escape_md(now_str)}",
        "",
    ]

    category_emojis = {"食品安全": "🚨", "營養知識": "🥦"}
    total = sum(len(v) for v in news_dict.values())

    if total == 0:
        lines.append("今日暫無相關新聞，明天見！")
        return "\n".join(lines)

    for category, items in news_dict.items():
        if not items:
            continue
        emoji = category_emojis.get(category, "📰")
        lines.append(f"{emoji} *{escape_md(category)}*")
        lines.append(escape_md("─" * 22))

        for item in items:
            # 標題（超連結）+ 時間
            date_str = f"  `{escape_md(item.format_date())}`" if item.format_date() else ""
            lines.append(f"*[{escape_md(item.title)}]({item.link})*{date_str}")

            # 條列重點
            if item.bullet_points:
                for point in item.bullet_points:
                    lines.append(f"  • {escape_md(point)}")
            elif item.summary:
                # 無重點時顯示 RSS 摘要
                lines.append(f"  _{escape_md(item.summary)}_")

            lines.append("")  # 新聞間空行

        lines.append("")

    lines.append(escape_md("─" * 22))
    lines.append("_資料來源：食藥署、衛福部、Google新聞_")
    return "\n".join(lines)


def escape_md(text: str) -> str:
    """Escape Telegram MarkdownV2 特殊字元"""
    special = r"\_*[]()~`>#+-=|{}.!"
    for ch in special:
        text = text.replace(ch, f"\\{ch}")
    return text
