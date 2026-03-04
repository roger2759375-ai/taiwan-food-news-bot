"""
台灣食安 & 營養新聞 Telegram Bot
每天定時推播食品安全與營養相關新聞
"""

# macOS SSL 憑證修正（Linux/Render 不需要）
import platform, ssl, certifi
if platform.system() == "Darwin":
    ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())

import asyncio
import logging
import os
import json
from pathlib import Path
from datetime import time
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from telegram.constants import ParseMode

from news_fetcher import fetch_all_news, format_news_message

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
PUSH_HOUR = int(os.getenv("PUSH_HOUR", "8"))       # 預設早上 8 點
PUSH_MINUTE = int(os.getenv("PUSH_MINUTE", "0"))
TZ_TAIPEI = ZoneInfo("Asia/Taipei")

# 儲存訂閱者清單（簡單 JSON 檔案）
SUBSCRIBERS_FILE = Path(__file__).parent / "subscribers.json"


def load_subscribers() -> set[int]:
    if SUBSCRIBERS_FILE.exists():
        try:
            return set(json.loads(SUBSCRIBERS_FILE.read_text()))
        except Exception:
            pass
    return set()


def save_subscribers(subs: set[int]) -> None:
    SUBSCRIBERS_FILE.write_text(json.dumps(list(subs)))


# ─── Command Handlers ────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """訂閱每日推播"""
    chat_id = update.effective_chat.id
    subs = load_subscribers()
    if chat_id in subs:
        await update.message.reply_text(
            "✅ 你已經訂閱囉！每天早上會自動推播食安 & 營養新聞。\n"
            "輸入 /news 可立即取得今日新聞。"
        )
        return

    subs.add(chat_id)
    save_subscribers(subs)
    await update.message.reply_text(
        "🎉 訂閱成功！\n\n"
        "每天早上會自動推播台灣食品安全及營養相關新聞。\n\n"
        "📌 可用指令：\n"
        "  /news  — 立即取得今日新聞\n"
        "  /stop  — 取消訂閱\n"
        "  /help  — 顯示說明"
    )
    logger.info("New subscriber: %s", chat_id)


async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """取消訂閱"""
    chat_id = update.effective_chat.id
    subs = load_subscribers()
    if chat_id not in subs:
        await update.message.reply_text("你尚未訂閱，無需取消。")
        return

    subs.discard(chat_id)
    save_subscribers(subs)
    await update.message.reply_text("已取消訂閱，掰掰！若想重新訂閱請輸入 /start。")
    logger.info("Unsubscribed: %s", chat_id)


async def cmd_news(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """立即取得今日新聞"""
    msg = await update.message.reply_text("🔍 正在抓取最新新聞，請稍候…")
    try:
        news = await asyncio.get_event_loop().run_in_executor(
            None, fetch_all_news, 48
        )
        text = format_news_message(news)
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)
    except Exception as e:
        logger.exception("Error fetching news for /news command")
        await msg.edit_text(f"抓取新聞時發生錯誤：{e}\n請稍後再試。")


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """說明"""
    await update.message.reply_text(
        "📋 *台灣食安 & 營養新聞 Bot*\n\n"
        "自動整理來自食藥署、衛福部及各大媒體的\n"
        "台灣食品安全與營養相關新聞，每天定時推播。\n\n"
        "📌 指令列表：\n"
        "  /start — 訂閱每日推播\n"
        "  /stop  — 取消訂閱\n"
        "  /news  — 立即取得今日新聞\n"
        "  /help  — 顯示此說明\n\n"
        "📡 資料來源：\n"
        "  • 食品藥物管理署 (FDA)\n"
        "  • 衛生福利部\n"
        "  • Google 新聞（台灣食安/營養）",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


# ─── Scheduled Job ────────────────────────────────────────────────────────────

async def daily_push(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """每日定時推播給所有訂閱者"""
    subs = load_subscribers()
    if not subs:
        logger.info("No subscribers to push to.")
        return

    logger.info("Starting daily push to %d subscribers…", len(subs))

    news = await asyncio.get_event_loop().run_in_executor(None, fetch_all_news, 48)
    text = format_news_message(news)

    failed = []
    for chat_id in subs:
        try:
            await ctx.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN_V2,
                disable_web_page_preview=True,
            )
            logger.info("Pushed to %s", chat_id)
        except Exception as e:
            logger.warning("Failed to push to %s: %s", chat_id, e)
            failed.append(chat_id)

    # 移除推播失敗（帳號已封鎖 bot）的訂閱者
    if failed:
        subs -= set(failed)
        save_subscribers(subs)
        logger.info("Removed %d inactive subscribers.", len(failed))


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    # 指令
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("news", cmd_news))
    app.add_handler(CommandHandler("help", cmd_help))

    # 每日定時任務（台北時間）
    push_time = time(hour=PUSH_HOUR, minute=PUSH_MINUTE, tzinfo=TZ_TAIPEI)
    app.job_queue.run_daily(daily_push, time=push_time, name="daily_news_push")
    logger.info("Daily push scheduled at %02d:%02d (Asia/Taipei)", PUSH_HOUR, PUSH_MINUTE)

    logger.info("Bot started. Polling…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
