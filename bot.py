import os
import re
import tempfile
import traceback
import threading
from flask import Flask
from PIL import Image, ImageDraw, ImageFont

from telegram import Update, InputMediaPhoto
from telegram.ext import Application, CommandHandler, ContextTypes
from playwright.async_api import async_playwright

BRAND_LINE_1 = "@Gems_of_trading"
BRAND_LINE_2 = "SALMAN NATHA | NISM CERTIFIED"

DEFAULT_BG = "black"
PADDING = 26
FOOTER_HEIGHT = 62

# Previous fixes retained:
# - top chart text should not cut now
# - bottom-left TradingView logo is cleaned/covered
# - footer looks cleaner with divider line
# - crop settings are easier to adjust later
CROP_LEFT = 0.045
CROP_TOP = 0.030
CROP_RIGHT = 0.805
CROP_BOTTOM = 0.875

COVER_TRADINGVIEW_LOGO = True
MAX_MULTI_CHARTS = 10

BG_COLORS = {
    "black": (18, 18, 18),
    "dark": (18, 18, 18),
    "blue": (12, 22, 40),
    "green": (10, 35, 25),
    "grey": (30, 30, 30),
    "gray": (30, 30, 30),
    "white": (245, 245, 245),
}

web_app = Flask(__name__)

@web_app.route("/")
def home():
    return "Trading Chart Bot is running ✅"

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web_server, daemon=True).start()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing. Add it in Render Environment Variables.")

POPULAR_SYMBOLS = (
    "RELIANCE, TCS, INFY, WIPRO, HDFCBANK, ICICIBANK, SBIN, "
    "NIFTY, BANKNIFTY, SENSEX"
)

TIMEFRAME_MAP = {
    "d": "D", "1d": "D", "day": "D", "daily": "D",
    "w": "W", "1w": "W", "week": "W", "weekly": "W",
    "m": "M", "1m": "M", "month": "M", "monthly": "M",
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
        return (80, 80, 80)
    return (170, 170, 170)

def load_font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
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
    return f"NSE:{symbol}"

def normalize_timeframe(raw_tf: str) -> str:
    return TIMEFRAME_MAP.get(raw_tf.strip().lower(), "D")

def is_valid_symbol(symbol: str) -> bool:
    return bool(re.match(r"^[A-Za-z0-9:_-]+$", symbol.strip()))

def parse_multi_symbols(raw_symbols: str):
    parts = [x.strip() for x in raw_symbols.split(",")]
    parts = [x for x in parts if x]
    return parts[:MAX_MULTI_CHARTS]

def cover_tradingview_logo(cropped: Image.Image) -> Image.Image:
    if not COVER_TRADINGVIEW_LOGO:
        return cropped
    img = cropped.convert("RGB")
    draw = ImageDraw.Draw(img)
    w, h = img.size
    sample_x = max(10, int(w * 0.03))
    sample_y = max(10, int(h * 0.88))
    bg = img.getpixel((sample_x, sample_y))
    x1, y1 = 0, int(h * 0.935)
    x2, y2 = int(w * 0.18), h
    draw.rectangle((x1, y1, x2, y2), fill=bg)
    return img

def add_premium_frame(cropped: Image.Image, symbol: str, timeframe: str, bg_name: str) -> Image.Image:
    bg_color = get_bg_color(bg_name)
    text_color = get_text_color(bg_name)
    muted_color = get_muted_text_color(bg_name)

    cropped = cropped.convert("RGB")
    cw, ch = cropped.size
    final_w = cw + PADDING * 2
    final_h = ch + PADDING * 2 + FOOTER_HEIGHT

    canvas = Image.new("RGB", (final_w, final_h), bg_color)
    canvas.paste(cropped, (PADDING, PADDING))
    draw = ImageDraw.Draw(canvas)

    title_font = load_font(22, bold=True)
    small_font = load_font(16, bold=False)
    brand_font = load_font(20, bold=True)
    sub_font = load_font(15, bold=False)

    divider_y = PADDING + ch + 8
    line_color = (50, 50, 50) if bg_name.lower() != "white" else (210, 210, 210)
    draw.line((PADDING, divider_y, final_w - PADDING, divider_y), fill=line_color, width=1)

    y = PADDING + ch + 16
    left_text = f"{normalize_symbol(symbol)}  •  {normalize_timeframe(timeframe)}"
    draw.text((PADDING, y), left_text, fill=text_color, font=title_font)
    draw.text((PADDING, y + 30), "Clean chart snapshot", fill=muted_color, font=small_font)

    brand_bbox = draw.textbbox((0, 0), BRAND_LINE_1, font=brand_font)
    sub_bbox = draw.textbbox((0, 0), BRAND_LINE_2, font=sub_font)
    brand_w = brand_bbox[2] - brand_bbox[0]
    sub_w = sub_bbox[2] - sub_bbox[0]

    draw.text((final_w - PADDING - brand_w, y), BRAND_LINE_1, fill=text_color, font=brand_font)
    draw.text((final_w - PADDING - sub_w, y + 30), BRAND_LINE_2, fill=muted_color, font=sub_font)
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
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--disable-setuid-sandbox"],
        )
        page = await browser.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=1)
        await page.goto(url, wait_until="domcontentloaded", timeout=70000)
        await page.wait_for_timeout(13000)

        for text in ["Accept all", "Accept", "I agree", "Maybe later", "Close", "Got it", "Continue", "No thanks"]:
            try:
                btn = page.get_by_text(text, exact=False).first
                await btn.click(timeout=1200)
                await page.wait_for_timeout(800)
            except Exception:
                pass

        await page.add_style_tag(content="""
            header, nav, aside, footer,
            [data-name="right-toolbar"], [data-name="left-toolbar"], [data-name="header-toolbar-symbol-search"],
            [class*="right-toolbar"], [class*="left-toolbar"],
            [class*="layout__area--top"], [class*="layout__area--right"], [class*="layout__area--left"], [class*="layout__area--bottom"],
            [class*="tv-header"], [class*="toastList"], [class*="watchlist"], [class*="floatingToolbar"],
            [class*="hotlist"], [class*="dialog"], [class*="popup"], [class*="tooltip"], [class*="market-status"] {
                visibility: hidden !important;
            }
            body { overflow: hidden !important; }
        """)
        await page.wait_for_timeout(2500)
        await page.screenshot(path=full_path, full_page=False)
        await browser.close()

    img = Image.open(full_path)
    w, h = img.size
    cropped = img.crop((
        int(w * CROP_LEFT),
        int(h * CROP_TOP),
        int(w * CROP_RIGHT),
        int(h * CROP_BOTTOM),
    ))
    cropped = cover_tradingview_logo(cropped)
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
        "Single chart:\n"
        "/chart RELIANCE 1d\n"
        "/chart TCS 1w blue\n\n"
        "Multi chart (up to 10):\n"
        "/multichart RELIANCE,TCS,INFY,WIPRO,SBIN 1d black\n\n"
        "Background options:\n"
        "black, blue, green, grey, white\n\n"
        f"Popular symbols:\n{POPULAR_SYMBOLS}"
    )
    await update.message.reply_text(message)

async def chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("❌ Usage:\n/chart RELIANCE 1d\n/chart WIPRO 1w black")
        return
    symbol = context.args[0]
    timeframe = context.args[1] if len(context.args) >= 2 else "1d"
    bg_name = context.args[2] if len(context.args) >= 3 else DEFAULT_BG

    if not is_valid_symbol(symbol):
        await update.message.reply_text("❌ Invalid symbol. Example: /chart RELIANCE 1w")
        return
    if bg_name.lower() not in BG_COLORS:
        bg_name = DEFAULT_BG

    await update.message.reply_text(f"⏳ Fetching {symbol.upper()} chart...")
    image_path = None
    try:
        image_path = await capture_chart(symbol, timeframe, bg_name)
        caption = f"📊 {normalize_symbol(symbol)} | Timeframe: {normalize_timeframe(timeframe)}\nPowered by {BRAND_LINE_1}"
        with open(image_path, "rb") as photo:
            await update.message.reply_photo(photo=photo, caption=caption)
    except Exception as e:
        print("CHART ERROR:", traceback.format_exc(), flush=True)
        await update.message.reply_text(
            "❌ Error fetching chart.\n\nReason:\n" + (str(e)[:900] if str(e) else "Unknown error")
        )
    finally:
        if image_path:
            try:
                os.remove(image_path)
            except Exception:
                pass

async def multichart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("❌ Usage:\n/multichart RELIANCE,TCS,INFY 1d black")
        return

    raw_symbols = context.args[0]
    timeframe = context.args[1] if len(context.args) >= 2 else "1d"
    bg_name = context.args[2] if len(context.args) >= 3 else DEFAULT_BG
    if bg_name.lower() not in BG_COLORS:
        bg_name = DEFAULT_BG

    symbols = parse_multi_symbols(raw_symbols)
    if not symbols:
        await update.message.reply_text("❌ No valid symbols found. Example: /multichart RELIANCE,TCS,INFY 1d black")
        return

    invalid_symbols = [s for s in symbols if not is_valid_symbol(s)]
    symbols = [s for s in symbols if is_valid_symbol(s)]
    if not symbols:
        await update.message.reply_text("❌ All symbols were invalid.")
        return

    status_msg = await update.message.reply_text(
        f"⏳ Generating {len(symbols)} chart(s)...\nTimeframe: {normalize_timeframe(timeframe)} | Background: {bg_name}"
    )

    generated_paths = []
    failed_symbols = []

    try:
        total = len(symbols)
        for i, symbol in enumerate(symbols, start=1):
            try:
                await status_msg.edit_text(
                    f"⏳ Generating {i}/{total}\nCurrent: {symbol.upper()}\nTimeframe: {normalize_timeframe(timeframe)} | Background: {bg_name}"
                )
            except Exception:
                pass
            try:
                path = await capture_chart(symbol, timeframe, bg_name)
                generated_paths.append((symbol, path))
            except Exception as e:
                print(f"MULTICHART ERROR for {symbol}: {traceback.format_exc()}", flush=True)
                failed_symbols.append(f"{symbol} ({str(e)[:120]})")

        if not generated_paths:
            await status_msg.edit_text("❌ Could not generate any charts.")
            return

        if len(generated_paths) == 1:
            symbol, path = generated_paths[0]
            caption = f"📊 {normalize_symbol(symbol)} | Timeframe: {normalize_timeframe(timeframe)}\nPowered by {BRAND_LINE_1}"
            with open(path, "rb") as photo:
                await update.message.reply_photo(photo=photo, caption=caption)
        else:
            media = []
            opened_files = []
            try:
                for idx, (symbol, path) in enumerate(generated_paths):
                    fh = open(path, "rb")
                    opened_files.append(fh)
                    caption = None
                    if idx == 0:
                        caption = (
                            f"📊 Multi Chart Pack ({len(generated_paths)})\n"
                            f"Timeframe: {normalize_timeframe(timeframe)} | Background: {bg_name}\n"
                            f"Powered by {BRAND_LINE_1}"
                        )
                    media.append(InputMediaPhoto(media=fh, caption=caption))
                await update.message.reply_media_group(media=media)
            finally:
                for fh in opened_files:
                    try:
                        fh.close()
                    except Exception:
                        pass

        summary_lines = []
        if invalid_symbols:
            summary_lines.append("Invalid skipped: " + ", ".join(invalid_symbols))
        if failed_symbols:
            summary_lines.append("Failed: " + ", ".join(failed_symbols[:10]))
        if summary_lines:
            await update.message.reply_text("⚠️ Summary:\n" + "\n".join(summary_lines))

        try:
            await status_msg.edit_text(f"✅ Done. Generated {len(generated_paths)} chart(s).")
        except Exception:
            pass

    except Exception as e:
        print("MULTICHART MAIN ERROR:", traceback.format_exc(), flush=True)
        await update.message.reply_text("❌ Error generating multichart.\n\nReason:\n" + (str(e)[:900] if str(e) else "Unknown error"))
    finally:
        for _, path in generated_paths:
            try:
                os.remove(path)
            except Exception:
                pass

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("chart", chart))
    app.add_handler(CommandHandler("multichart", multichart))
    print("✅ Telegram bot started", flush=True)
    app.run_polling()

if __name__ == "__main__":
    main()
