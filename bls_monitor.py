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
import os
import subprocess
from datetime import datetime
from playwright.async_api import async_playwright
from telegram import Update, Bot, BotCommand
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
BLS_EMAIL          = os.getenv("BLS_EMAIL", "")
BLS_PASSWORD       = os.getenv("BLS_PASSWORD", "")

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
    email_set = "✅" if BLS_EMAIL else "❌ غير محددة"
    pass_set  = "✅" if BLS_PASSWORD else "❌ غير محددة"
    msg = (
        f"📊 <b>حالة البوت</b>\n"
        f"المراقبة: {state}\n"
        f"البريد الإلكتروني: {email_set}\n"
        f"كلمة المرور: {pass_set}\n"
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
#           LOGIN LOGIC
# =============================================

async def login_to_bls(page) -> bool:
    if not BLS_EMAIL or not BLS_PASSWORD:
        log.error("BLS_EMAIL or BLS_PASSWORD not set in environment variables!")
        send_telegram("⚠️ <b>خطأ:</b> لم يتم تحديد البريد الإلكتروني أو كلمة المرور في متغيرات Railway.")
        return False
    try:
        log.info(f"Attempting login for: {BLS_EMAIL}")
        await page.goto("https://algeria.blsspainglobal.com/DZA/account/login", timeout=60000)
        await asyncio.sleep(3)

        await page.fill('input[name="Email"]', BLS_EMAIL)
        await page.fill('input[name="Password"]', BLS_PASSWORD)
        await page.click('button[type="submit"]')
        await asyncio.sleep(6)

        current_url = page.url.lower()
        success = "login" not in current_url and ("dashboard" in current_url or "appointment" in current_url or "dza" in current_url)

        if success:
            log.info("Login successful.")
        else:
            log.error(f"Login may have failed. Current URL: {page.url}")
            send_telegram(f"⚠️ <b>تحذير:</b> فشل تسجيل الدخول. تحقق من البيانات في Railway.\nالرابط الحالي: {page.url}")

        return success
    except Exception as e:
        log.error(f"Login error: {e}")
        send_telegram(f"⚠️ <b>خطأ في تسجيل الدخول:</b> {e}")
        return False

# =============================================
#           MONITOR LOGIC
# =============================================

async def check_combination(page, combo) -> list:
    try:
        log.info(f"Checking: {combo['loc_ar']} | {combo['sub']} | {combo['vtype']} | {combo['cat']}")
        await page.goto(BLS_URL, timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # تحقق أننا لا زلنا مسجلين دخول
        if "login" in page.url.lower():
            log.warning("Session expired, need to re-login.")
            return None  # None = إشارة لإعادة اللوجين

        async def safe_select(selector, label):
            try:
                el = page.locator(selector).first
                await el.wait_for(state="visible", timeout=8000)
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

        # فحص نصوص "لا يوجد موعد"
        no_slot_phrases = [
            "no appointment", "aucun rendez", "no slot", "pas de créneau",
            "no available", "غير متاح", "لا توجد"
        ]
        if any(phrase in content.lower() for phrase in no_slot_phrases):
            log.info(f"No slots found for {combo['sub']} | {combo['cat']}")
            return []

        # محاولة إيجاد خلايا التقويم المتاحة
        slots = await page.locator("td.day:not(.disabled):not(.old):not(.new)").all_inner_texts()
        log.info(f"Raw slots found: {slots}")
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
                page = await context.new_page()
                if stealth_async:
                    await stealth_async(page)

                logged_in = await login_to_bls(page)
                if not logged_in:
                    log.warning("Login failed. Retrying in 5 minutes.")
                    await asyncio.sleep(300)
                    continue

                # فحص كل التركيبات (لا عشوائي) — دورة كاملة ثم انتظار
                while is_running:
                    log.info(f"=== Scan Cycle Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")

                    for combo in COMBINATIONS:
                        if not is_running:
                            break

                        result = await check_combination(page, combo)

                        if result is None:
                            # انتهت الجلسة — إعادة لوجين
                            log.warning("Session lost, re-logging in...")
                            logged_in = await login_to_bls(page)
                            if not logged_in:
                                break
                            result = await check_combination(page, combo)

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

                    wait_time = random.randint(60, 120)
                    log.info(f"=== Cycle Complete. Waiting {wait_time}s... ===")
                    await asyncio.sleep(wait_time)

            except Exception as e:
                log.error(f"Monitor loop error: {e}")
                send_telegram(f"⚠️ <b>خطأ في المراقب:</b> {e}\nسيتم إعادة المحاولة خلال 30 ثانية.")
                await asyncio.sleep(30)
            finally:
                if browser:
                    await browser.close()

# =============================================
#           MAIN ENTRY POINT
# =============================================

async def main():
    # التحقق من المتغيرات الأساسية عند البدء
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

    log.info("Initializing Telegram bot...")

    # تشغيل البوت والمراقب معاً بشكل صحيح
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()

        log.info("Bot is running. Starting monitor...")
        send_telegram("🤖 <b>البوت شغّال!</b>\nبدأت مراقبة مواعيد BLS. اكتب /status للتحقق من الحالة.")

        await run_monitor()  # يشتغل إلى الأبد هنا

        await app.updater.stop()
        await app.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped.")