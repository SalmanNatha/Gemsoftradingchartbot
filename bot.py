import os
import re
import tempfile
import traceback
import threading
from flask import Flask

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from playwright.async_api import async_playwright


# -----------------------------
# Small web server for Render
# -----------------------------
web_app = Flask(__name__)

@web_app.route("/")
def home():
    return "Trading Chart Bot is running ✅"

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web_server, daemon=True).start()


# -----------------------------
# Telegram Bot
# -----------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing. Add it in Render Environment Variables.")


POPULAR_SYMBOLS = (
    "RELIANCE, TCS, INFY, WIPRO, HDFCBANK, ICICIBANK, SBIN, "
    "NIFTY, BANKNIFTY, SENSEX"
)

TIMEFRAME_MAP = {
    "d": "D",
    "1d": "D",
    "day": "D",
    "daily": "D",
    "w": "W",
    "1w": "W",
    "week": "W",
    "weekly": "W",
    "m": "M",
    "1m": "M",
    "month": "M",
    "monthly": "M",
}


def normalize_symbol(raw_symbol: str) -> str:
    symbol = raw_symbol.strip().upper()

    aliases = {
        "NIFTY": "NSE:NIFTY",
        "NIFTY50": "NSE:NIFTY",
        "BANKNIFTY": "NSE:BANKNIFTY",
        "SENSEX": "BSE:SENSEX",
    }

    if symbol in aliases:
        return aliases[symbol]

    if ":" in symbol:
        return symbol

    # Default Indian stocks to NSE
    return f"NSE:{symbol}"


def normalize_timeframe(raw_tf: str) -> str:
    tf = raw_tf.strip().lower()
    return TIMEFRAME_MAP.get(tf, "D")


async def capture_chart(symbol: str, timeframe: str) -> str:
    tv_symbol = normalize_symbol(symbol)
    interval = normalize_timeframe(timeframe)

    url = f"https://www.tradingview.com/chart/?symbol={tv_symbol}&interval={interval}"

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    tmp.close()
    screenshot_path = tmp.name

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-setuid-sandbox",
            ],
        )

        page = await browser.new_page(
            viewport={"width": 1280, "height": 720},
            device_scale_factor=1,
        )

        await page.goto(url, wait_until="domcontentloaded", timeout=70000)

        # Give TradingView time to load the chart area
        await page.wait_for_timeout(12000)

        # Try to close popups/cookie banners if they appear
        for text in ["Accept all", "Accept", "I agree", "Maybe later", "Close"]:
            try:
                btn = page.get_by_text(text, exact=False).first
                if await btn.count() > 0:
                    await btn.click(timeout=1500)
                    await page.wait_for_timeout(1000)
            except Exception:
                pass

        await page.screenshot(path=screenshot_path, full_page=False)
        await browser.close()

    return screenshot_path


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = (
        "✅ Trading Chart Bot is live!\n\n"
        "Use:\n"
        "/chart RELIANCE 1d\n"
        "/chart TCS 1w\n"
        "/chart WIPRO 1m\n\n"
        f"Popular symbols:\n{POPULAR_SYMBOLS}"
    )
    await update.message.reply_text(message)


async def chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("❌ Usage: /chart RELIANCE 1d or /chart TCS 1w")
        return

    symbol = context.args[0]
    timeframe = context.args[1] if len(context.args) >= 2 else "1d"

    # Basic safety for symbol input
    if not re.match(r"^[A-Za-z0-9:_-]+$", symbol):
        await update.message.reply_text("❌ Invalid symbol. Example: /chart RELIANCE 1w")
        return

    await update.message.reply_text(f"⏳ Fetching {symbol.upper()} chart...")

    try:
        image_path = await capture_chart(symbol, timeframe)

        caption = f"📊 {normalize_symbol(symbol)} | Timeframe: {normalize_timeframe(timeframe)}"
        with open(image_path, "rb") as photo:
            await update.message.reply_photo(photo=photo, caption=caption)

        try:
            os.remove(image_path)
        except Exception:
            pass

    except Exception as e:
        error_details = traceback.format_exc()
        print("CHART ERROR:", error_details, flush=True)

        short_error = str(e)
        if len(short_error) > 900:
            short_error = short_error[:900] + "..."

        await update.message.reply_text(
            "❌ Error fetching chart.\n\n"
            "Reason:\n"
            f"{short_error}\n\n"
            "Send this error screenshot to ChatGPT."
        )


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("chart", chart))

    print("✅ Telegram bot started", flush=True)
    app.run_polling()


if __name__ == "__main__":
    main()
