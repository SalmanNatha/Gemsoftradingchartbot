import os
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from playwright.async_api import async_playwright

BOT_TOKEN = os.environ.get("BOT_TOKEN")

SYMBOLS = {
    "RELIANCE": "NSE:RELIANCE",
    "TCS": "NSE:TCS",
    "INFY": "NSE:INFY",
    "WIPRO": "NSE:WIPRO",
    "HDFCBANK": "NSE:HDFCBANK",
    "ICICIBANK": "NSE:ICICIBANK",
    "SBIN": "NSE:SBIN",
    "AXISBANK": "NSE:AXISBANK",
    "NIFTY": "NSE:NIFTY",
    "BANKNIFTY": "NSE:BANKNIFTY",
    "SENSEX": "BSE:SENSEX",
}

INTERVALS = {
    "1d": "D",
    "1w": "W",
    "1h": "60",
    "15m": "15",
}

async def get_chart(symbol: str, interval: str = "D") -> str:
    tv_symbol = SYMBOLS.get(symbol.upper(), f"NSE:{symbol.upper()}")
    url = (
        f"https://s.tradingview.com/widgetembed/?"
        f"symbol={tv_symbol}"
        f"&interval={interval}"
        f"&theme=dark"
        f"&style=1"
        f"&locale=en"
        f"&hide_side_toolbar=1"
        f"&allow_symbol_change=0"
        f"&save_image=0"
        f"&studies=RSI%40tv-basicstudies%1FMACD%40tv-basicstudies"
    )
    path = f"/tmp/{symbol}_{interval}.png"
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        page = await browser.new_page(viewport={"width": 1000, "height": 600})
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(4000)
        await page.screenshot(path=path, full_page=False)
        await browser.close()
    return path

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📊 *Games of Trading Chart Bot*\n\n"
        "*Commands:*\n"
        "/chart RELIANCE — Daily chart\n"
        "/chart TCS 1w — Weekly chart\n"
        "/chart INFY 1h — 1hr chart\n"
        "/multi — Get Nifty50 top stocks\n\n"
        "*Supported intervals:*\n"
        "1d (Daily) | 1w (Weekly) | 1h (1hr) | 15m (15min)\n\n"
        "*Popular symbols:*\n"
        "RELIANCE, TCS, INFY, WIPRO\n"
        "HDFCBANK, ICICIBANK, SBIN\n"
        "NIFTY, BANKNIFTY, SENSEX"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Usage: /chart RELIANCE or /chart TCS 1w")
        return

    symbol = context.args[0].upper()
    interval_key = context.args[1].lower() if len(context.args) > 1 else "1d"
    interval = INTERVALS.get(interval_key, "D")

    msg = await update.message.reply_text(f"⏳ Fetching {symbol} chart...")

    try:
        path = await get_chart(symbol, interval)
        with open(path, "rb") as img:
            await update.message.reply_photo(
                photo=img,
                caption=f"📈 *{symbol}* | {interval_key.upper()} Chart\n_via Games of Trading_",
                parse_mode="Markdown"
            )
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ Error fetching chart for {symbol}. Try again.")
        print(f"Error: {e}")

async def multi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbols = ["NIFTY", "BANKNIFTY", "RELIANCE", "TCS", "HDFCBANK"]
    await update.message.reply_text("⏳ Fetching top 5 charts... this takes ~30 sec")
    for sym in symbols:
        try:
            path = await get_chart(sym, "D")
            with open(path, "rb") as img:
                await update.message.reply_photo(
                    photo=img,
                    caption=f"📈 *{sym}* | Daily",
                    parse_mode="Markdown"
                )
        except Exception as e:
            await update.message.reply_text(f"❌ Failed for {sym}")
            print(f"Error: {e}")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("chart", chart))
    app.add_handler(CommandHandler("multi", multi))
    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
