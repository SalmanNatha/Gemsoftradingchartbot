import os
import re
import tempfile
import traceback
import threading
from urllib.parse import quote_plus
from flask import Flask
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageOps
from telegram import Update, InputMediaPhoto
from telegram.ext import Application, CommandHandler, ContextTypes
from playwright.async_api import async_playwright

# =========================================================
# TRADING CHART BOT - VERSION 6
# BSE default + bright/volume + mysetup mode
# =========================================================

BRAND_LINE_1 = "@Gems_of_trading"
BRAND_LINE_2 = "SALMAN NATHA | NISM CERTIFIED"

DEFAULT_EXCHANGE = "BSE"
DEFAULT_BG = "black"
DEFAULT_STYLE = "vivid"

# Your shared TradingView setup link.
# You can override this in Render Environment Variables:
# MY_SETUP_CHART_URL = your TradingView chart/layout link
MY_SETUP_CHART_URL = os.getenv(
    "MY_SETUP_CHART_URL",
    "https://www.tradingview.com/chart/SYSCHEM/PMk0CXuD-Syschem-Ind-Limited/"
)

PADDING = 26
FOOTER_HEIGHT = 62

# Crop settings:
# Left kept low so symbol / 1D / 1W line is visible
# Bottom increased so volume bars are visible
CROP_LEFT = 0.012
CROP_TOP = 0.028
CROP_RIGHT = 0.805
CROP_BOTTOM = 0.955

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

STYLE_OPTIONS = {"normal", "clean", "bright", "vivid", "sharp"}
SPECIAL_OPTIONS = {"mysetup"}

TIMEFRAME_MAP = {
    "d": "D", "1d": "D", "day": "D", "daily": "D",
    "w": "W", "1w": "W", "week": "W", "weekly": "W",
    "m": "M", "1m": "M", "month": "M", "monthly": "M",
}

RANGE_MAP = {
    "1m": "1M",
    "3m": "3M",
    "6m": "6M",
    "ytd": "YTD",
    "1y": "1Y",
    "2y": "2Y",
    "3y": "3Y",
    "5y": "5Y",
    "all": "All",
}

DEFAULT_RANGE_BY_INTERVAL = {
    "D": "1Y",
    "W": "5Y",
    "M": "All",
}

# =========================================================
# RENDER HEALTH SERVER
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
    "SYSCHEM, KPL, HFCL, RELIANCE, TCS, INFY, WIPRO, HDFCBANK, ICICIBANK, SBIN, "
    "SENSEX, NIFTY, BANKNIFTY"
)

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
    return f"{DEFAULT_EXCHANGE}:{symbol}"

def normalize_timeframe(raw_tf: str) -> str:
    return TIMEFRAME_MAP.get(raw_tf.strip().lower(), "D")

def is_valid_symbol(symbol: str) -> bool:
    return bool(re.match(r"^[A-Za-z0-9:_-]+$", symbol.strip()))

def parse_multi_symbols(raw_symbols: str):
    parts = [x.strip() for x in raw_symbols.split(",")]
    parts = [x for x in parts if x]
    return parts[:MAX_MULTI_CHARTS]

def parse_optional_args(optional_args, timeframe: str):
    bg_name = DEFAULT_BG
    style_name = DEFAULT_STYLE
    use_mysetup = False
    interval = normalize_timeframe(timeframe)
    range_label = DEFAULT_RANGE_BY_INTERVAL.get(interval, "1Y")

    for arg in optional_args:
        a = arg.strip().lower()
        if a in SPECIAL_OPTIONS:
            use_mysetup = True
            # mysetup should preserve the chart colors as much as possible.
            # Keep normal unless user also passes vivid/bright/sharp.
            style_name = "normal"
        elif a in BG_COLORS:
            bg_name = a
        elif a in RANGE_MAP:
            range_label = RANGE_MAP[a]
        elif a in STYLE_OPTIONS:
            style_name = a

    return bg_name, range_label, style_name, use_mysetup

def get_bg_color(bg_name: str):
    return BG_COLORS.get((bg_name or DEFAULT_BG).lower(), BG_COLORS[DEFAULT_BG])

def get_text_color(bg_name: str):
    return (20, 20, 20) if bg_name and bg_name.lower() == "white" else (235, 235, 235)

def get_muted_text_color(bg_name: str):
    return (80, 80, 80) if bg_name and bg_name.lower() == "white" else (170, 170, 170)

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

def enhance_chart(img: Image.Image, style_name: str) -> Image.Image:
    img = img.convert("RGB")
    style = (style_name or DEFAULT_STYLE).lower()

    if style == "normal":
        return img

    img = ImageOps.autocontrast(img, cutoff=1)

    if style == "clean":
        img = ImageEnhance.Contrast(img).enhance(1.10)
        img = ImageEnhance.Sharpness(img).enhance(1.18)
        return img

    if style == "bright":
        img = ImageEnhance.Brightness(img).enhance(1.10)
        img = ImageEnhance.Contrast(img).enhance(1.18)
        img = ImageEnhance.Color(img).enhance(1.12)
        img = ImageEnhance.Sharpness(img).enhance(1.20)
        return img

    if style == "sharp":
        img = ImageEnhance.Brightness(img).enhance(1.05)
        img = ImageEnhance.Contrast(img).enhance(1.25)
        img = ImageEnhance.Color(img).enhance(1.18)
        img = ImageEnhance.Sharpness(img).enhance(1.45)
        return img

    img = ImageEnhance.Brightness(img).enhance(1.08)
    img = ImageEnhance.Contrast(img).enhance(1.25)
    img = ImageEnhance.Color(img).enhance(1.25)
    img = ImageEnhance.Sharpness(img).enhance(1.30)
    return img

def cover_tradingview_logo(cropped: Image.Image) -> Image.Image:
    if not COVER_TRADINGVIEW_LOGO:
        return cropped

    img = cropped.convert("RGB")
    draw = ImageDraw.Draw(img)
    w, h = img.size

    sample_x = max(10, int(w * 0.035))
    sample_y = max(10, int(h * 0.90))
    bg = img.getpixel((sample_x, sample_y))

    x1 = 0
    y1 = int(h * 0.955)
    x2 = int(w * 0.16)
    y2 = h
    draw.rectangle((x1, y1, x2, y2), fill=bg)
    return img

def add_premium_frame(
    cropped: Image.Image,
    symbol: str,
    timeframe: str,
    bg_name: str,
    range_label: str,
    style_name: str,
    use_mysetup: bool
) -> Image.Image:
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
    left_text = f"{normalize_symbol(symbol)}  •  {normalize_timeframe(timeframe)}  •  {range_label}"
    draw.text((PADDING, y), left_text, fill=text_color, font=title_font)

    setup_text = "mysetup" if use_mysetup else style_name
    draw.text((PADDING, y + 30), f"Clean chart snapshot • {setup_text}", fill=muted_color, font=small_font)

    brand_bbox = draw.textbbox((0, 0), BRAND_LINE_1, font=brand_font)
    sub_bbox = draw.textbbox((0, 0), BRAND_LINE_2, font=sub_font)
    brand_w = brand_bbox[2] - brand_bbox[0]
    sub_w = sub_bbox[2] - sub_bbox[0]

    draw.text((final_w - PADDING - brand_w, y), BRAND_LINE_1, fill=text_color, font=brand_font)
    draw.text((final_w - PADDING - sub_w, y + 30), BRAND_LINE_2, fill=muted_color, font=sub_font)
    return canvas

def build_tradingview_url(tv_symbol: str, interval: str, use_mysetup: bool) -> str:
    if use_mysetup:
        base = MY_SETUP_CHART_URL.strip()
        sep = "&" if "?" in base else "?"
        # This works best with a true TradingView chart/layout URL.
        # If the link is a static published idea link, TradingView may ignore symbol/interval.
        return f"{base}{sep}symbol={quote_plus(tv_symbol)}&interval={quote_plus(interval)}"
    return f"https://www.tradingview.com/chart/?symbol={quote_plus(tv_symbol)}&interval={quote_plus(interval)}"

async def try_click_range(page, range_label: str) -> bool:
    strategies = [
        page.get_by_role("button", name=range_label),
        page.get_by_text(range_label, exact=True),
        page.locator(f"text='{range_label}'"),
    ]

    for locator in strategies:
        try:
            if await locator.count() > 0:
                await locator.first.click(timeout=2000)
                await page.wait_for_timeout(2500)
                return True
        except Exception:
            pass
    return False

async def try_zoom_out(page):
    try:
        for _ in range(4):
            await page.keyboard.press("-")
        await page.wait_for_timeout(1500)
    except Exception:
        pass

async def capture_chart(
    symbol: str,
    timeframe: str,
    bg_name: str = DEFAULT_BG,
    range_label: str = None,
    style_name: str = DEFAULT_STYLE,
    use_mysetup: bool = False
) -> str:
    tv_symbol = normalize_symbol(symbol)
    interval = normalize_timeframe(timeframe)
    range_label = range_label or DEFAULT_RANGE_BY_INTERVAL.get(interval, "1Y")
    url = build_tradingview_url(tv_symbol, interval, use_mysetup)

    full_path = tempfile.NamedTemporaryFile(delete=False, suffix=".png").name
    final_path = tempfile.NamedTemporaryFile(delete=False, suffix=".png").name

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--disable-setuid-sandbox"],
        )
        page = await browser.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=1)

        await page.goto(url, wait_until="domcontentloaded", timeout=70000)
        await page.wait_for_timeout(15000 if use_mysetup else 13000)

        for text in ["Accept all", "Accept", "I agree", "Maybe later", "Close", "Got it", "Continue", "No thanks", "Grab this chart"]:
            try:
                btn = page.get_by_text(text, exact=False).first
                await btn.click(timeout=1500)
                await page.wait_for_timeout(1200)
            except Exception:
                pass

        clicked = await try_click_range(page, range_label)
        if not clicked:
            await try_zoom_out(page)

        await page.add_style_tag(content="""
            header, nav, aside, footer,
            [data-name="right-toolbar"], [data-name="left-toolbar"], [data-name="header-toolbar-symbol-search"],
            [class*="right-toolbar"], [class*="left-toolbar"],
            [class*="layout__area--top"], [class*="layout__area--right"], [class*="layout__area--left"],
            [class*="tv-header"], [class*="toastList"], [class*="watchlist"], [class*="floatingToolbar"],
            [class*="hotlist"], [class*="dialog"], [class*="popup"], [class*="tooltip"], [class*="market-status"],
            [class*="modal"], [class*="overlay"], [class*="backdrop"] {
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

    # mysetup uses normal by default to preserve original chart colors.
    cropped = enhance_chart(cropped, style_name)
    cropped = cover_tradingview_logo(cropped)

    final_canvas = add_premium_frame(cropped, symbol, timeframe, bg_name, range_label, style_name, use_mysetup)
    final_canvas.save(final_path, quality=96)

    try:
        os.remove(full_path)
    except Exception:
        pass

    return final_path

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = (
        "✅ Trading Chart Bot is live!\n\n"
        f"Default exchange: {DEFAULT_EXCHANGE}\n\n"
        "Single chart:\n"
        "/chart HFCL 1d mysetup\n"
        "/chart HFCL 1d mysetup black 1y\n"
        "/chart HFCL 1d black 1y vivid\n"
        "/chart NSE:WIPRO 1d mysetup\n\n"
        "Multi chart:\n"
        "/multichart SYSCHEM,KPL,SUZLON 1d mysetup black 1y\n\n"
        "Background: black, blue, green, grey, white\n"
        "Range: 1m, 3m, 6m, ytd, 1y, 2y, 3y, 5y, all\n"
        "Style: normal, clean, bright, vivid, sharp\n"
        "Special mode: mysetup\n\n"
        f"Popular symbols:\n{POPULAR_SYMBOLS}"
    )
    await update.message.reply_text(message)

async def chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text(
            "❌ Usage examples:\n"
            "/chart HFCL 1d mysetup\n"
            "/chart HFCL 1d mysetup black 1y\n"
            "/chart HFCL 1d black 1y vivid"
        )
        return

    symbol = context.args[0]
    timeframe = context.args[1] if len(context.args) >= 2 else "1d"
    bg_name, range_label, style_name, use_mysetup = parse_optional_args(context.args[2:], timeframe)

    if not is_valid_symbol(symbol):
        await update.message.reply_text("❌ Invalid symbol. Example: /chart HFCL 1d")
        return

    setup_text = "mysetup" if use_mysetup else style_name

    await update.message.reply_text(
        f"⏳ Fetching {symbol.upper()} chart...\n"
        f"Exchange: {DEFAULT_EXCHANGE} | TF: {normalize_timeframe(timeframe)} | Range: {range_label} | BG: {bg_name} | Mode: {setup_text}"
    )

    image_path = None
    try:
        image_path = await capture_chart(symbol, timeframe, bg_name, range_label, style_name, use_mysetup)
        caption = (
            f"📊 {normalize_symbol(symbol)} | TF: {normalize_timeframe(timeframe)} | Range: {range_label} | Mode: {setup_text}\n"
            f"Powered by {BRAND_LINE_1}"
        )
        with open(image_path, "rb") as photo:
            await update.message.reply_photo(photo=photo, caption=caption)
    except Exception as e:
        print("CHART ERROR:", traceback.format_exc(), flush=True)
        await update.message.reply_text("❌ Error fetching chart.\n\nReason:\n" + (str(e)[:900] if str(e) else "Unknown error"))
    finally:
        if image_path:
            try:
                os.remove(image_path)
            except Exception:
                pass

async def multichart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("❌ Usage:\n/multichart SYSCHEM,KPL,SUZLON 1d mysetup black 1y")
        return

    raw_symbols = context.args[0]
    timeframe = context.args[1] if len(context.args) >= 2 else "1d"
    bg_name, range_label, style_name, use_mysetup = parse_optional_args(context.args[2:], timeframe)

    symbols = parse_multi_symbols(raw_symbols)
    if not symbols:
        await update.message.reply_text("❌ No valid symbols found.")
        return

    invalid_symbols = [s for s in symbols if not is_valid_symbol(s)]
    symbols = [s for s in symbols if is_valid_symbol(s)]
    if not symbols:
        await update.message.reply_text("❌ All symbols were invalid.")
        return

    setup_text = "mysetup" if use_mysetup else style_name

    status_msg = await update.message.reply_text(
        f"⏳ Generating {len(symbols)} chart(s)...\n"
        f"TF: {normalize_timeframe(timeframe)} | Range: {range_label} | BG: {bg_name} | Mode: {setup_text}"
    )

    generated_paths = []
    failed_symbols = []

    try:
        total = len(symbols)
        for i, symbol in enumerate(symbols, start=1):
            try:
                await status_msg.edit_text(
                    f"⏳ Generating {i}/{total}\nCurrent: {symbol.upper()}\n"
                    f"TF: {normalize_timeframe(timeframe)} | Range: {range_label} | BG: {bg_name} | Mode: {setup_text}"
                )
            except Exception:
                pass

            try:
                path = await capture_chart(symbol, timeframe, bg_name, range_label, style_name, use_mysetup)
                generated_paths.append((symbol, path))
            except Exception as e:
                print(f"MULTICHART ERROR for {symbol}: {traceback.format_exc()}", flush=True)
                failed_symbols.append(f"{symbol} ({str(e)[:120]})")

        if not generated_paths:
            await status_msg.edit_text("❌ Could not generate any charts.")
            return

        if len(generated_paths) == 1:
            symbol, path = generated_paths[0]
            caption = (
                f"📊 {normalize_symbol(symbol)} | TF: {normalize_timeframe(timeframe)} | Range: {range_label} | Mode: {setup_text}\n"
                f"Powered by {BRAND_LINE_1}"
            )
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
                            f"TF: {normalize_timeframe(timeframe)} | Range: {range_label} | BG: {bg_name} | Mode: {setup_text}\n"
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
