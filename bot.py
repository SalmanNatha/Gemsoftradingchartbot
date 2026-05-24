import os
import re
import tempfile
import traceback
import threading
from flask import Flask
from PIL import Image, ImageDraw, ImageFont

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from playwright.async_api import async_playwright


# =========================================================
# PREMIUM BOT SETTINGS
# =========================================================

BRAND_LINE_1 = "@Gems_of_trading"
BRAND_LINE_2 = "SALMAN NATHA | NISM CERTIFIED"

DEFAULT_BG = "black"
PADDING = 28
WATERMARK_HEIGHT = 58

# Use 3rd command word to change background:
# /chart WIPRO 1w black
# /chart WIPRO 1w blue
# /chart WIPRO 1w green
# /chart WIPRO 1w grey
BG_COLORS = {
    "black": (18, 18, 18),
    "dark": (18, 18, 18),
    "blue": (12, 22, 40),
    "green": (10, 35, 25),
    "grey": (30, 30, 30),
    "gray": (30, 30, 30),
    "white": (245, 245, 245),
}


# =========================================================
# SMALL WEB SERVER FOR RENDER
# =========================================================

web_app = Flask(__name__)

@web_app.route("/")
def home():
    return "Trading Chart Bot is running ✅"

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web_server, daemon=True).start()


# =========================================================
# TELEGRAM BOT
# =========================================================

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


def get_bg_color(bg_name: str):
    if not bg_name:
        bg_name = DEFAULT_BG
    return BG_COLORS.get(bg_name.lower(), BG_COLORS[DEFAULT_BG])


def get_text_color(bg_name: str):
    if bg_name and bg_name.lower() == "white":
        return (20, 20, 20)
    return (235, 235, 235)


def get_muted_text_color(bg_name: str):
    if bg_name and bg_name.lower() == "white":
        return (70, 70, 70)
    return (170, 170, 170)


def load_font(size: int, bold: bool = False):
    candidates = []
    if bold:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        ]

    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass

    return ImageFont.load_default()


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


def add_premium_frame(cropped: Image.Image, symbol: str, timeframe: str, bg_name: str) -> Image.Image:
    bg_color = get_bg_color(bg_name)
    text_color = get_text_color(bg_name)
    muted_color = get_muted_text_color(bg_name)

    cropped = cropped.convert("RGB")
    cw, ch = cropped.size

    final_w = cw + PADDING * 2
    final_h = ch + PADDING * 2 + WATERMARK_HEIGHT

    canvas = Image.new("RGB", (final_w, final_h), bg_color)
    canvas.paste(cropped, (PADDING, PADDING))

    draw = ImageDraw.Draw(canvas)

    title_font = load_font(22, bold=True)
    small_font = load_font(17, bold=False)
    brand_font = load_font(20, bold=True)
    sub_font = load_font(15, bold=False)

    # bottom premium strip
    y = PADDING + ch + 14

    left_text = f"{normalize_symbol(symbol)}  •  {normalize_timeframe(timeframe)}"
    draw.text((PADDING, y), left_text, fill=text_color, font=title_font)

    sub_text = "Auto chart snapshot"
    draw.text((PADDING, y + 28), sub_text, fill=muted_color, font=small_font)

    # right aligned watermark
    brand_bbox = draw.textbbox((0, 0), BRAND_LINE_1, font=brand_font)
    sub_bbox = draw.textbbox((0, 0), BRAND_LINE_2, font=sub_font)

    brand_w = brand_bbox[2] - brand_bbox[0]
    sub_w = sub_bbox[2] - sub_bbox[0]

    right_x_brand = final_w - PADDING - brand_w
    right_x_sub = final_w - PADDING - sub_w

    draw.text((right_x_brand, y), BRAND_LINE_1, fill=text_color, font=brand_font)
    draw.text((right_x_sub, y + 28), BRAND_LINE_2, fill=muted_color, font=sub_font)

    return canvas


async def capture_chart(symbol: str, timeframe: str, bg_name: str = DEFAULT_BG) -> str:
    tv_symbol = normalize_symbol(symbol)
    interval = normalize_timeframe(timeframe)

    url = f"https://www.tradingview.com/chart/?symbol={tv_symbol}&interval={interval}"

    full_path = tempfile.NamedTemporaryFile(delete=False, suffix=".png").name
    final_path = tempfile.NamedTemporaryFile(delete=False, suffix=".png").name

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
            viewport={"width": 1600, "height": 900},
            device_scale_factor=1,
        )

        await page.goto(url, wait_until="domcontentloaded", timeout=70000)
        await page.wait_for_timeout(12000)

        # Try closing popups / cookie banners
        for text in [
            "Accept all", "Accept", "I agree", "Maybe later",
            "Close", "Got it", "Continue", "No thanks"
        ]:
            try:
                btn = page.get_by_text(text, exact=False).first
                await btn.click(timeout=1200)
                await page.wait_for_timeout(800)
            except Exception:
                pass

        # Hide extra UI as much as possible
        await page.add_style_tag(content="""
            header,
            nav,
            aside,
            footer,
            [data-name="right-toolbar"],
            [data-name="left-toolbar"],
            [data-name="header-toolbar-symbol-search"],
            [data-name="legend-source-item"],
            [class*="right-toolbar"],
            [class*="left-toolbar"],
            [class*="layout__area--top"],
            [class*="layout__area--right"],
            [class*="layout__area--left"],
            [class*="layout__area--bottom"],
            [class*="tv-header"],
            [class*="toastList"],
            [class*="watchlist"],
            [class*="floatingToolbar"],
            [class*="hotlist"],
            [class*="dialog"],
            [class*="popup"],
            [class*="tooltip"],
            [class*="market-status"] {
                visibility: hidden !important;
            }

            body {
                overflow: hidden !important;
            }
        """)

        await page.wait_for_timeout(2500)

        await page.screenshot(path=full_path, full_page=False)
        await browser.close()

    # Crop to mostly only chart + price scale + volume.
    # Tuned for 1600 x 900 viewport.
    img = Image.open(full_path)
    w, h = img.size

    left = int(w * 0.045)
    top = int(h * 0.065)
    right = int(w * 0.805)
    bottom = int(h * 0.905)

    cropped = img.crop((left, top, right, bottom))

    final_canvas = add_premium_frame(cropped, symbol, timeframe, bg_name)
    final_canvas.save(final_path, quality=95)

    try:
        os.remove(full_path)
    except Exception:
        pass

    return final_path


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = (
        "✅ Trading Chart Bot is live!\n\n"
        "Use:\n"
        "/chart RELIANCE 1d\n"
        "/chart TCS 1w\n"
        "/chart WIPRO 1m\n\n"
        "Premium background options:\n"
        "/chart WIPRO 1w black\n"
        "/chart WIPRO 1w blue\n"
        "/chart WIPRO 1w green\n"
        "/chart WIPRO 1w grey\n\n"
        f"Popular symbols:\n{POPULAR_SYMBOLS}"
    )
    await update.message.reply_text(message)


async def chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text(
            "❌ Usage:\n"
            "/chart RELIANCE 1d\n"
            "/chart WIPRO 1w black"
        )
        return

    symbol = context.args[0]
    timeframe = context.args[1] if len(context.args) >= 2 else "1d"
    bg_name = context.args[2] if len(context.args) >= 3 else DEFAULT_BG

    if not re.match(r"^[A-Za-z0-9:_-]+$", symbol):
        await update.message.reply_text("❌ Invalid symbol. Example: /chart RELIANCE 1w")
        return

    if bg_name.lower() not in BG_COLORS:
        bg_name = DEFAULT_BG

    await update.message.reply_text(f"⏳ Fetching {symbol.upper()} chart...")

    image_path = None
    try:
        image_path = await capture_chart(symbol, timeframe, bg_name)

        caption = (
            f"📊 {normalize_symbol(symbol)} | Timeframe: {normalize_timeframe(timeframe)}\n"
            f"Powered by {BRAND_LINE_1}"
        )

        with open(image_path, "rb") as photo:
            await update.message.reply_photo(photo=photo, caption=caption)

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
            "If needed, send this screenshot to ChatGPT."
        )
    finally:
        if image_path:
            try:
                os.remove(image_path)
            except Exception:
                pass


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("chart", chart))

    print("✅ Telegram bot started", flush=True)
    app.run_polling()


if __name__ == "__main__":
    main()
