"""
=======================================================
  BLS Algeria Spain Visa Appointment Monitor Bot
  يراقب مواعيد BLS الجزائر ويرسل عدد المواعيد المتوفرة
=======================================================
"""

import asyncio
import random
import logging
import requests
import json
import os
import subprocess
from datetime import datetime
from playwright.async_api import async_playwright
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

try:
    from playwright_stealth import stealth_async
except ImportError:
    stealth_async = None

# =============================================
#           USER CONFIGURATION (ENV VARS)
# =============================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

BLS_URL  = "https://algeria.blsspainglobal.com/DZA/bls/appointment"
HEADLESS = True

is_running = True

# =============================================
#   قائمة المراكز والأنواع
# =============================================

COMBINATIONS = []
for sub in ["ALG 1", "ALG 2", "ALG 3", "ALG 4"]:
    for vtype in ["Schengen Visa", "Visa renewal / renouvellement de visa"]:
        for cat in ["Normal", "Premium"]:
            COMBINATIONS.append({"loc": "Algiers", "loc_ar": "الجزائر", "vtype": vtype, "sub": sub, "cat": cat})

for sub in ["Oran 2", "Oran 3", "Oran 4"]:
    for vtype in ["Schengen Visa", "Visa renewal / renouvellement de visa"]:
        for cat in ["Normal", "Premium"]:
            COMBINATIONS.append({"loc": "Oran", "loc_ar": "وهران", "vtype": vtype, "sub": sub, "cat": cat})

# =============================================
#           LOGGING
# =============================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# =============================================
#           TELEGRAM HELPERS
# =============================================

async def set_commands(app):
    commands = [
        BotCommand("start", "تشغيل المراقبة"),
        BotCommand("stop", "إيقاف المراقبة"),
        BotCommand("status", "حالة البوت الحالية"),
        BotCommand("test", "إرسال رسالة تجريبية"),
    ]
    await app.bot.set_my_commands(commands)

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10
        )
        if not r.ok:
            log.error(f"Telegram send failed: {r.status_code} - {r.text}")
        else:
            log.info("Telegram message sent successfully.")
    except Exception as e:
        log.error(f"Telegram error: {e}")

# =============================================
#           TELEGRAM COMMANDS
# =============================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_running
    is_running = True
    await update.message.reply_text("✅ تم تشغيل المراقبة! سيبدأ الفحص في الدورة القادمة.")
    log.info("Bot started by user command.")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_running
    is_running = False
    await update.message.reply_text("🛑 تم إيقاف المراقبة مؤقتاً.")
    log.info("Bot stopped by user command.")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = "✅ تعمل" if is_running else "🛑 متوقفة"
    cookies_exist = "✅" if os.path.exists("cookies.json") else "❌ غير موجود"
    msg = (
        f"📊 <b>حالة البوت</b>\n"
        f"المراقبة: {state}\n"
        f"ملف الكوكيز: {cookies_exist}\n"
        f"عدد التركيبات: {len(COMBINATIONS)}"
    )
    await update.message.reply_text(msg, parse_mode="HTML")

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    send_telegram("🔔 <b>رسالة تجريبية</b>\nالبوت يعمل بشكل صحيح وقادر على إرسال الإشعارات.")
    await update.message.reply_text("✅ تم إرسال رسالة تجريبية.")

# =============================================
#           BROWSER ENGINE
# =============================================

async def get_browser_context(p):
    try:
        browser = await p.chromium.launch(
            headless=HEADLESS,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
    except Exception as e:
        log.warning(f"Launch failed, installing browsers: {e}")
        subprocess.run(["playwright", "install", "chromium"], check=False)
        browser = await p.chromium.launch(
            headless=HEADLESS,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )

    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 720}
    )
    return browser, context

# =============================================
#           LOGIN VIA COOKIES
# =============================================

async def load_cookies(context) -> bool:
    cookies_path = "cookies.json"
    if not os.path.exists(cookies_path):
        log.error("cookies.json not found!")
        send_telegram(
            "⚠️ <b>خطأ:</b> ملف cookies.json غير موجود.\n"
            "يرجى تصدير الكوكيز من المتصفح بعد تسجيل الدخول ورفعها على GitHub."
        )
        return False

    try:
        with open(cookies_path, "r") as f:
            cookies = json.load(f)

        pw_cookies = []
        for c in cookies:
            cookie = {
                "name": c["name"],
                "value": c["value"],
                "domain": c["domain"],
                "path": c.get("path", "/"),
                "httpOnly": c.get("httpOnly", False),
                "secure": c.get("secure", False),
            }
            same_site = c.get("sameSite", "Lax")
            if same_site and same_site.lower() in ["strict", "lax", "none"]:
                cookie["sameSite"] = same_site.capitalize()
            if c.get("expirationDate"):
                cookie["expires"] = int(c["expirationDate"])
            pw_cookies.append(cookie)

        await context.add_cookies(pw_cookies)
        log.info(f"Loaded {len(pw_cookies)} cookies successfully.")
        return True

    except Exception as e:
        log.error(f"Error loading cookies: {e}")
        send_telegram(f"⚠️ <b>خطأ في تحميل الكوكيز:</b> {e}")
        return False

async def verify_session(page) -> bool:
    try:
        await page.goto(BLS_URL, timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(3)
        if "login" in page.url.lower():
            log.warning("Session expired.")
            send_telegram(
                "⚠️ <b>انتهت صلاحية الجلسة!</b>\n"
                "يرجى تسجيل الدخول يدوياً وتصدير الكوكيز من جديد ورفعها على GitHub."
            )
            return False
        log.info(f"Session valid. URL: {page.url}")
        return True
    except Exception as e:
        log.error(f"Session verify error: {e}")
        return False

# =============================================
#           MONITOR LOGIC
# =============================================

async def check_combination(page, combo) -> list:
    try:
        log.info(f"Checking: {combo['loc_ar']} | {combo['sub']} | {combo['vtype']} | {combo['cat']}")
        await page.goto(BLS_URL, timeout=90000, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        if "login" in page.url.lower():
            log.warning("Session expired during check.")
            return None

        async def safe_select(selector, label):
            try:
                el = page.locator(selector).first
                await el.wait_for(state="visible", timeout=10000)
                await el.select_option(label=label)
                await asyncio.sleep(1.5)
                return True
            except Exception as e:
                log.debug(f"Select failed [{selector}={label}]: {e}")
                return False

        r1 = await safe_select('select[id*="Location"]', combo["loc"])
        r2 = await safe_select('select[id*="VisaType"]', combo["vtype"])
        r3 = await safe_select('select[id*="SubType"]', combo["sub"])
        r4 = await safe_select('select[id*="Category"]', combo["cat"])

        log.info(f"Selectors: Location={r1}, VisaType={r2}, SubType={r3}, Category={r4}")

        await asyncio.sleep(2)
        content = await page.content()

        no_slot_phrases = [
            "no appointment", "aucun rendez", "no slot", "pas de créneau",
            "no available", "غير متاح", "لا توجد"
        ]
        if any(phrase in content.lower() for phrase in no_slot_phrases):
            log.info(f"No slots: {combo['sub']} | {combo['cat']}")
            return []

        slots = await page.locator("td.day:not(.disabled):not(.old):not(.new)").all_inner_texts()
        log.info(f"Raw slots: {slots}")
        slots = [s.strip() for s in slots if s.strip() and s.strip().isdigit()]

        return slots

    except Exception as e:
        log.error(f"check_combination error: {e}")
        return []

# =============================================
#           MAIN MONITOR LOOP
# =============================================

async def run_monitor():
    log.info("Monitor loop started.")

    while True:
        if not is_running:
            await asyncio.sleep(10)
            continue

        async with async_playwright() as p:
            browser = None
            try:
                browser, context = await get_browser_context(p)

                cookies_ok = await load_cookies(context)
                if not cookies_ok:
                    log.warning("Cookies not loaded. Retrying in 5 minutes.")
                    await asyncio.sleep(300)
                    continue

                page = await context.new_page()
                if stealth_async:
                    await stealth_async(page)

                session_ok = await verify_session(page)
                if not session_ok:
                    log.warning("Session invalid. Retrying in 10 minutes.")
                    await asyncio.sleep(600)
                    continue

                while is_running:
                    log.info(f"=== Scan Cycle: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")

                    session_lost = False
                    for combo in COMBINATIONS:
                        if not is_running:
                            break

                        result = await check_combination(page, combo)

                        if result is None:
                            log.warning("Session lost during scan. Restarting...")
                            session_lost = True
                            break

                        if result:
                            msg = (
                                f"🚨 <b>مواعيد متاحة!</b>\n"
                                f"📍 المركز: {combo['loc_ar']} ({combo['sub']})\n"
                                f"🎫 النوع: {combo['vtype']}\n"
                                f"⭐ الفئة: {combo['cat']}\n"
                                f"📅 الأيام المتاحة: {', '.join(result[:10])}"
                            )
                            send_telegram(msg)
                            log.info(f"SLOTS FOUND: {combo} -> {result}")

                        await asyncio.sleep(random.randint(8, 15))

                    if session_lost:
                        break

                    wait_time = random.randint(60, 120)
                    log.info(f"=== Cycle Complete. Waiting {wait_time}s... ===")
                    await asyncio.sleep(wait_time)

            except Exception as e:
                log.error(f"Monitor loop error: {e}")
                send_telegram(f"⚠️ <b>خطأ في المراقب:</b> {e}\nإعادة المحاولة خلال 30 ثانية.")
                await asyncio.sleep(30)
            finally:
                if browser:
                    await browser.close()

# =============================================
#           MAIN ENTRY POINT
# =============================================

async def main():
    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not set!")
        return
    if not TELEGRAM_CHAT_ID:
        print("ERROR: TELEGRAM_CHAT_ID not set!")
        return

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("test", test_command))

    await set_commands(app)

    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()

        send_telegram("🤖 <b>البوت شغّال!</b>\nبدأت مراقبة مواعيد BLS عبر الكوكيز. اكتب /status للتحقق.")

        await run_monitor()

        await app.updater.stop()
        await app.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped.")
