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

# محاولة استيراد stealth بأمان
try:
    from playwright_stealth import stealth_async
except ImportError:
    stealth_async = None

# =============================================
#           USER CONFIGURATION
# =============================================

TELEGRAM_BOT_TOKEN = "8674136162:AAF7erCPgpP81NkS0NSz_7ssdruOmEW9eNc"
TELEGRAM_CHAT_ID   = "8499305437"

BLS_URL   = "https://algeria.blsspainglobal.com/DZA/bls/appointment"
HEADLESS  = True
MIN_DELAY = 30   # زيادة التأخير لتجنب الحظر
MAX_DELAY = 60

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
#           TELEGRAM
# =============================================

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        log.error(f"Telegram error: {e}")

# =============================================
#           BROWSER ENGINE
# =============================================

async def get_browser_context(p):
    try:
        # إعدادات التشغيل لـ Railway
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
#           MONITOR LOGIC
# =============================================

async def check_combination(page, combo):
    try:
        await page.goto(BLS_URL, timeout=60000, wait_until="networkidle")
        await asyncio.sleep(2)

        # دالة مساعدة للاختيار الآمن
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

        # محاولة اختيار العناصر
        await safe_select('select[id*="Location"]', combo["loc"])
        await safe_select('select[id*="VisaType"]', combo["vtype"])
        await safe_select('select[id*="SubType"]', combo["sub"])
        await safe_select('select[id*="Category"]', combo["cat"])

        # التحقق من وجود مواعيد في الصفحة
        content = await page.content()
        if "no appointment" in content.lower() or "aucun rendez" in content.lower():
            return []

        # البحث عن أي تواريخ متاحة في التقويم
        slots = await page.locator("td.day:not(.disabled)").all_inner_texts()
        return slots if slots else []

    except Exception as e:
        log.debug(f"Check failed for {combo['sub']}: {e}")
        return []

async def run_monitor():
    log.info("Starting BLS Monitor...")
    send_telegram("🚀 <b>البوت بدأ العمل بنجاح على Railway</b>")
    
    while True:
        async with async_playwright() as p:
            browser = None
            try:
                browser, context = await get_browser_context(p)
                page = await context.new_page()
                if stealth_async:
                    await stealth_async(page)

                while True:
                    log.info(f"--- New Scan Cycle: {datetime.now().strftime('%H:%M:%S')} ---")
                    
                    # فحص عينة عشوائية في كل دورة لتجنب الحظر السريع
                    sample = random.sample(COMBINATIONS, min(5, len(COMBINATIONS)))
                    
                    for combo in sample:
                        slots = await check_combination(page, combo)
                        if slots:
                            msg = f"🚨 <b>مواعيد متاحة!</b>\n📍 المركز: {combo['loc_ar']} ({combo['sub']})\n🎫 الفئة: {combo['cat']}\n📅 التواريخ: {', '.join(slots[:5])}"
                            send_telegram(msg)
                            log.info(f"Found slots for {combo['sub']}")
                        
                        await asyncio.sleep(random.randint(5, 10))

                    wait_time = random.randint(MIN_DELAY, MAX_DELAY)
                    log.info(f"Cycle finished. Waiting {wait_time}s...")
                    await asyncio.sleep(wait_time)

            except Exception as e:
                log.error(f"Main loop error: {e}")
                send_telegram(f"⚠️ <b>تنبيه:</b> حدث خطأ في البوت، سيتم إعادة التشغيل تلقائياً.\n<code>{str(e)[:100]}</code>")
                await asyncio.sleep(30)
            finally:
                if browser:
                    await browser.close()

if __name__ == "__main__":
    try:
        asyncio.run(run_monitor())
    except KeyboardInterrupt:
        pass
