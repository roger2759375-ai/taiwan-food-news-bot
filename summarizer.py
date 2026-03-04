"""
文章全文抓取 + 提取式摘要（不需要 API Key）
以關鍵字權重 + 句子位置評分，挑出最重要的句子作為條列重點。
"""

import logging
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

FETCH_TIMEOUT = 12

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

# 重要關鍵字（命中越多，句子分數越高）
HIGH_VALUE_KEYWORDS = [
    "下架", "回收", "違規", "不合格", "超標", "禁止", "罰款", "裁罰",
    "食物中毒", "中毒", "汙染", "污染", "殘留", "檢出", "抽查",
    "警告", "注意", "建議", "提醒", "呼籲", "公告",
    "營養", "研究", "發現", "顯示", "證實", "效果", "功效",
    "攝取", "飲食", "健康", "預防", "降低", "風險",
]

# 雜訊句型（排除廣告、版權聲明等）
NOISE_PATTERNS = [
    r"版權所有", r"著作權", r"Copyright", r"All rights reserved",
    r"廣告", r"訂閱", r"加入會員", r"免費下載", r"點擊",
    r"更多新聞", r"延伸閱讀", r"相關新聞", r"推薦閱讀",
    r"^\s*\d+\s*$",          # 純數字行
    r"^.{1,8}$",             # 太短的句子
]
NOISE_RE = re.compile("|".join(NOISE_PATTERNS))


def fetch_article_text(url: str) -> Optional[str]:
    """抓取文章頁面，回傳清理後的純文字（最多 4000 字）"""
    try:
        resp = httpx.get(
            url,
            headers=HEADERS,
            timeout=FETCH_TIMEOUT,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer",
                          "header", "aside", "form", "figure",
                          "noscript", "iframe"]):
            tag.decompose()

        main = (
            soup.find("article")
            or soup.find(class_=re.compile(
                r"article|content|main|post|story|news[-_]body|entry", re.I
            ))
            or soup.find("main")
            or soup.body
        )
        if not main:
            return None

        text = main.get_text(separator="\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text[:4000] if text else None

    except Exception as e:
        logger.debug("fetch_article_text failed (%s): %s", url[:60], e)
        return None


def _split_sentences(text: str) -> list[str]:
    """將文章切成句子清單"""
    # 以中文句號、問號、驚嘆號，以及換行為斷句點
    raw = re.split(r"(?<=[。！？!?])\s*|\n+", text)
    sentences = []
    for s in raw:
        s = s.strip()
        # 去除太短、有雜訊的句子
        if len(s) < 12 or NOISE_RE.search(s):
            continue
        sentences.append(s)
    return sentences


def _score_sentence(sent: str, position: int, total: int, title: str) -> float:
    """對句子打分數（越高越重要）"""
    score = 0.0

    # 1. 關鍵字命中數
    for kw in HIGH_VALUE_KEYWORDS:
        if kw in sent:
            score += 1.5

    # 2. 句子包含標題關鍵詞（與主題直接相關）
    title_words = set(re.findall(r"[\u4e00-\u9fff]{2,}", title))
    for w in title_words:
        if w in sent:
            score += 1.0

    # 3. 位置偏重：新聞首段最重要
    if position == 0:
        score += 2.0
    elif position <= 2:
        score += 1.0
    elif position >= total - 2:
        score += 0.3   # 結尾句有時是總結

    # 4. 長度適中的句子優先（太短或太長都扣分）
    length = len(sent)
    if 20 <= length <= 80:
        score += 0.5
    elif length > 150:
        score -= 0.5

    return score


def extractive_summary(title: str, text: str, n: int = 4) -> list[str]:
    """
    從文章文字提取最重要的 n 句，以出現順序排列後回傳。
    """
    sentences = _split_sentences(text)
    if not sentences:
        return []

    total = len(sentences)
    scored = [
        (i, sent, _score_sentence(sent, i, total, title))
        for i, sent in enumerate(sentences)
    ]

    # 取分數最高的 n 句，保持原文順序
    top = sorted(scored, key=lambda x: x[2], reverse=True)[:n]
    top.sort(key=lambda x: x[0])  # 恢復原始順序

    # 截斷過長的句子
    result = []
    for _, sent, _ in top:
        if len(sent) > 70:
            sent = sent[:68] + "…"
        result.append(sent)
    return result


def _fallback_sentences(summary: str) -> list[str]:
    """RSS summary 備援：拆句"""
    if not summary or len(summary) < 15:
        return []
    sentences = re.split(r"[。！？\n]", summary)
    cleaned = [s.strip() for s in sentences if len(s.strip()) > 10]
    return cleaned[:3]


def get_bullet_points(title: str, link: str, fallback_summary: str) -> list[str]:
    """
    主要入口：
    1. 嘗試抓文章全文 → 提取式摘要
    2. 失敗則用 RSS summary 拆句備援
    """
    text = fetch_article_text(link)
    if text and len(text) > 100:
        points = extractive_summary(title, text, n=4)
        if points:
            return points

    return _fallback_sentences(fallback_summary)
