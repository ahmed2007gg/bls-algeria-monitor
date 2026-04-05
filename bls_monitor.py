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
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# محاولة استيراد stealth بأمان
try:
    from playwright_stealth import stealth_async
except ImportError:
    stealth_async = None

# =============================================
#           USER CONFIGURATION (ENV VARS)
# =============================================

# يفضل وضع هذه القيم في متغيرات البيئة في Railway
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8674136162:AAF7erCPgpP81NkS0NSz_7ssdruOmEW9eNc")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "8499305437")
BLS_EMAIL          = os.getenv("BLS_EMAIL", "")  # أضف إيميلك هنا أو في Railway
BLS_PASSWORD       = os.getenv("BLS_PASSWORD", "") # أضف كلمة سرك هنا أو في Railway

BLS_URL   = "https://algeria.blsspainglobal.com/DZA/bls/appointment"
HEADLESS  = True
MIN_DELAY = 60   # زيادة التأخير لتجنب الحظر
MAX_DELAY = 120

# حالة البوت (تشغيل/إيقاف)
is_running = True

# =============================================
#   قائمة المراكز والأنواع
# =============================================

COMBINATIONS = []
# الجزائر العاصمة
for sub in ["ALG 1", "ALG 2", "ALG 3", "ALG 4"]:
    for vtype in ["Schengen Visa", "Visa renewal / renouvellement de visa"]:
        for cat in ["Normal", "Premium"]:
            COMBINATIONS.append({"loc": "Algiers", "loc_ar": "الجزائر", "vtype": vtype, "sub": sub, "cat": cat})

# وهران
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

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        log.error(f"Telegram error: {e}")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_running
    is_running = True
    await update.message.reply_text("✅ تم تشغيل البوت بنجاح! سيبدأ الفحص الآن.")
    log.info("Bot started by user via Telegram.")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_running
    is_running = False
    await update.message.reply_text("🛑 تم إيقاف البوت مؤقتاً. لن يتم إجراء أي فحص حتى تعيد تشغيله.")
    log.info("Bot stopped by user via Telegram.")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = "🟢 يعمل" if is_running else "🔴 متوقف"
    await update.message.reply_text(f"حالة البوت الحالية: {status}")

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
        log.warning(f"Launch failed, trying to install browsers: {e}")
        subprocess.run(["playwright", "install", "chromium"], check=False)
        browser = await p.chromium.launch(headless=HEADLESS, args=["--no-sandbox"])

    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 720}
    )
    return browser, context

# =============================================
#           LOGIN LOGIC
# =============================================

async def login_to_bls(page):
    if not BLS_EMAIL or not BLS_PASSWORD:
        log.error("Email or Password not provided!")
        return False
    
    try:
        log.info(f"Attempting login for: {BLS_EMAIL}")
        await page.goto("https://algeria.blsspainglobal.com/DZA/account/login", timeout=60000)
        await asyncio.sleep(2)
        
        # إدخال البيانات
        await page.fill('input[name="Email"]', BLS_EMAIL)
        await page.fill('input[name="Password"]', BLS_PASSWORD)
        
        # الضغط على زر الدخول (قد يحتاج لتعديل الـ selector بناءً على الموقع)
        await page.click('button[type="submit"]')
        await asyncio.sleep(5)
        
        if "dashboard" in page.url.lower() or "appointment" in page.url.lower():
            log.info("Login successful!")
            return True
        else:
            log.warning("Login might have failed or CAPTCHA appeared.")
            return False
    except Exception as e:
        log.error(f"Login error: {e}")
        return False

# =============================================
#           MONITOR LOGIC
# =============================================

async def check_combination(page, combo):
    try:
        await page.goto(BLS_URL, timeout=60000, wait_until="networkidle")
        await asyncio.sleep(2)

        async def safe_select(selector, label):
            try:
                el = page.locator(selector).first
                if await el.is_visible(timeout=5000):
                    await el.select_option(label=label)
                    await asyncio.sleep(1)
                    return True
            except:
                pass
            return False

        await safe_select('select[id*="Location"]', combo["loc"])
        await safe_select('select[id*="VisaType"]', combo["vtype"])
        await safe_select('select[id*="SubType"]', combo["sub"])
        await safe_select('select[id*="Category"]', combo["cat"])

        content = await page.content()
        if "no appointment" in content.lower() or "aucun rendez" in content.lower():
            return []

        slots = await page.locator("td.day:not(.disabled)").all_inner_texts()
        return slots if slots else []

    except Exception as e:
        log.debug(f"Check failed for {combo['sub']}: {e}")
        return []

async def run_monitor():
    log.info("Starting BLS Monitor Loop...")
    
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

                # تسجيل الدخول أولاً
                logged_in = await login_to_bls(page)
                if not logged_in:
                    log.warning("Continuing without login or login failed.")

                while is_running:
                    log.info(f"--- New Scan Cycle: {datetime.now().strftime('%H:%M:%S')} ---")
                    sample = random.sample(COMBINATIONS, min(3, len(COMBINATIONS)))
                    
                    for combo in sample:
                        if not is_running: break
                        slots = await check_combination(page, combo)
                        if slots:
                            msg = f"🚨 <b>مواعيد متاحة!</b>\n📍 المركز: {combo['loc_ar']} ({combo['sub']})\n🎫 الفئة: {combo['cat']}\n📅 التواريخ: {', '.join(slots[:5])}"
                            send_telegram(msg)
                            # أخذ لقطة شاشة للتأكيد
                            await page.screenshot(path="screenshot.png")
                            # هنا يمكن إضافة كود لإرسال الصورة عبر تلغرام
                        
                        await asyncio.sleep(random.randint(10, 20))

                    wait_time = random.randint(MIN_DELAY, MAX_DELAY)
                    log.info(f"Cycle finished. Waiting {wait_time}s...")
                    await asyncio.sleep(wait_time)

            except Exception as e:
                log.error(f"Main loop error: {e}")
                await asyncio.sleep(30)
            finally:
                if browser:
                    await browser.close()

# =============================================
#           MAIN ENTRY POINT
# =============================================

async def main():
    # تشغيل نظام أوامر تلغرام في الخلفية
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("status", status_command))
    
    # تشغيل البوت وتلغرام معاً
    log.info("Starting Telegram Bot Handlers...")
    
    # تشغيل المراقبة كمهمة منفصلة
    monitor_task = asyncio.create_task(run_monitor())
    
    # تشغيل استقبال أوامر تلغرام
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        
        # إبقاء البرنامج يعمل
        await monitor_task

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
