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
import json
from datetime import datetime, time
from playwright.async_api import async_playwright
from telegram import Update, Bot, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# محاولة استيراد stealth بأمان
try:
    from playwright_stealth import stealth_async
except ImportError:
    stealth_async = None

# =============================================
#           USER CONFIGURATION (ENV VARS)
# =============================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8674136162:AAF7erCPgpP81NkS0NSz_7ssdruOmEW9eNc")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "8499305437")
BLS_EMAIL          = os.getenv("BLS_EMAIL", "")
BLS_PASSWORD       = os.getenv("BLS_PASSWORD", "")

BLS_URL   = "https://algeria.blsspainglobal.com/DZA/bls/appointment"
HEADLESS  = True

# إعدادات افتراضية قابلة للتغيير عبر الأوامر
config = {
    "is_running": True,
    "min_delay": 60,
    "max_delay": 120,
    "drop_threshold": 1, # حد النقصان
    "quiet_hours": {"start": "00:00", "end": "06:00"},
    "stats": {"total_scans": 0, "found_slots": 0, "last_scan": "Never"}
}

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
#           TELEGRAM HELPERS & COMMANDS
# =============================================

async def set_commands(app):
    commands = [
        BotCommand("start", "الرئيسية"),
        BotCommand("check", "فحص فوري"),
        BotCommand("stats", "الإحصائيات"),
        BotCommand("reset", "إعادة تعيين إحصائيات مركز"),
        BotCommand("daily", "تقرير يومي فوري"),
        BotCommand("intervals", "عرض التواقيت"),
        BotCommand("interval", "تغيير توقيت مركز"),
        BotCommand("drops", "عرض حدود النقصان"),
        BotCommand("drop", "تغيير حد النقصان"),
        BotCommand("quiet", "الساعات الصامتة"),
        BotCommand("stop", "إيقاف البوت مؤقتاً")
    ]
    await app.bot.set_my_commands(commands)

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        log.error(f"Telegram error: {e}")

# --- COMMAND HANDLERS ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    config["is_running"] = True
    await update.message.reply_text("✅ <b>أهلاً بك في بوت BLS Algeria!</b>\nتم تشغيل البوت بنجاح. يمكنك استخدام القائمة للتحكم.", parse_mode="HTML")

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 جاري بدء فحص فوري الآن... يرجى الانتظار.")
    # سيتم تنفيذ الفحص في الدورة القادمة فوراً
    config["force_check"] = True

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (f"📊 <b>إحصائيات البوت:</b>\n"
           f"• إجمالي عمليات الفحص: {config['stats']['total_scans']}\n"
           f"• مواعيد تم العثور عليها: {config['stats']['found_slots']}\n"
           f"• آخر فحص: {config['stats']['last_scan']}\n"
           f"• الحالة: {'🟢 يعمل' if config['is_running'] else '🔴 متوقف'}")
    await update.message.reply_text(msg, parse_mode="HTML")

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    config["stats"] = {"total_scans": 0, "found_slots": 0, "last_scan": "Reset"}
    await update.message.reply_text("🔄 تم إعادة تعيين الإحصائيات بنجاح.")

async def daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📅 تقرير اليوم: لا توجد بيانات كافية حالياً.")

async def intervals_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (f"⏱ <b>التواقيت الحالية:</b>\n"
           f"• الحد الأدنى: {config['min_delay']} ثانية\n"
           f"• الحد الأقصى: {config['max_delay']} ثانية")
    await update.message.reply_text(msg, parse_mode="HTML")

async def interval_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        try:
            new_val = int(context.args[0])
            config["min_delay"] = new_val
            config["max_delay"] = new_val + 60
            await update.message.reply_text(f"✅ تم تغيير التوقيت إلى {new_val} ثانية.")
        except:
            await update.message.reply_text("❌ يرجى إدخال رقم صحيح. مثال: /interval 60")
    else:
        await update.message.reply_text("💡 استخدم الأمر هكذا: /interval [عدد الثواني]")

async def drops_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"📉 حد النقصان الحالي: {config['drop_threshold']}")

async def drop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        try:
            config["drop_threshold"] = int(context.args[0])
            await update.message.reply_text(f"✅ تم تغيير حد النقصان إلى {config['drop_threshold']}.")
        except:
            await update.message.reply_text("❌ يرجى إدخال رقم صحيح.")
    else:
        await update.message.reply_text("💡 استخدم الأمر هكذا: /drop [الرقم]")

async def quiet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🤫 الساعات الصامتة: من {config['quiet_hours']['start']} إلى {config['quiet_hours']['end']}")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    config["is_running"] = False
    await update.message.reply_text("🛑 تم إيقاف البوت مؤقتاً.")

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
        return False
    try:
        await page.goto("https://algeria.blsspainglobal.com/DZA/account/login", timeout=60000)
        await asyncio.sleep(2)
        await page.fill('input[name="Email"]', BLS_EMAIL)
        await page.fill('input[name="Password"]', BLS_PASSWORD)
        await page.click('button[type="submit"]')
        await asyncio.sleep(5)
        return "dashboard" in page.url.lower() or "appointment" in page.url.lower()
    except:
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
            except: pass
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
    except:
        return []

async def run_monitor():
    log.info("Starting BLS Monitor Loop...")
    
    while True:
        if not config["is_running"] and not config.get("force_check"):
            await asyncio.sleep(10)
            continue

        async with async_playwright() as p:
            browser = None
            try:
                browser, context = await get_browser_context(p)
                page = await context.new_page()
                if stealth_async: await stealth_async(page)

                logged_in = await login_to_bls(page)
                
                while config["is_running"] or config.get("force_check"):
                    config["force_check"] = False
                    config["stats"]["total_scans"] += 1
                    config["stats"]["last_scan"] = datetime.now().strftime('%H:%M:%S')
                    
                    log.info(f"--- Scan Cycle: {config['stats']['last_scan']} ---")
                    sample = random.sample(COMBINATIONS, min(3, len(COMBINATIONS)))
                    
                    for combo in sample:
                        slots = await check_combination(page, combo)
                        if slots:
                            config["stats"]["found_slots"] += 1
                            msg = f"🚨 <b>مواعيد متاحة!</b>\n📍 المركز: {combo['loc_ar']} ({combo['sub']})\n🎫 الفئة: {combo['cat']}\n📅 التواريخ: {', '.join(slots[:5])}"
                            send_telegram(msg)
                        await asyncio.sleep(random.randint(10, 20))

                    wait_time = random.randint(config["min_delay"], config["max_delay"])
                    log.info(f"Waiting {wait_time}s...")
                    await asyncio.sleep(wait_time)

            except Exception as e:
                log.error(f"Main loop error: {e}")
                await asyncio.sleep(30)
            finally:
                if browser: await browser.close()

# =============================================
#           MAIN ENTRY POINT
# =============================================

async def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    # تسجيل الأوامر
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("check", check_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("daily", daily_command))
    app.add_handler(CommandHandler("intervals", intervals_command))
    app.add_handler(CommandHandler("interval", interval_command))
    app.add_handler(CommandHandler("drops", drops_command))
    app.add_handler(CommandHandler("drop", drop_command))
    app.add_handler(CommandHandler("quiet", quiet_command))
    app.add_handler(CommandHandler("stop", stop_command))
    
    # تحديث قائمة Menu في تلغرام
    await set_commands(app)
    
    log.info("Starting Telegram Bot Handlers...")
    monitor_task = asyncio.create_task(run_monitor())
    
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        await monitor_task

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
