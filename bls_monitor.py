"""
=======================================================
  BLS Algeria Visa Appointment Monitor Bot
  يراقب مواعيد BLS الجزائر ويرسل عدد المواعيد المتوفرة
=======================================================

INSTALLATION:
  pip install playwright requests python-telegram-bot
  playwright install chromium

HOW TO RUN:
  python bls_monitor.py
"""

import asyncio
import random
import logging
import requests
from datetime import datetime
from playwright.async_api import async_playwright

# =============================================
#           USER CONFIGURATION - عدّل هنا
# =============================================

TELEGRAM_BOT_TOKEN = "8573323796:AAHbEo3X3ZqhWZ0aUXQ83_vVbNi-LTYGRRE"
TELEGRAM_CHAT_ID   = "8499305437"   # Chat ID الخاص بك

# المراكز المراد مراقبتها (اتركها كما هي لمراقبة الجميع)
CENTERS = [
    {"name": "Algiers", "name_ar": "الجزائر العاصمة"},
    {"name": "Oran",    "name_ar": "وهران"},
    {"name": "Constantine", "name_ar": "قسنطينة"},
    {"name": "Annaba",  "name_ar": "عنابة"},
]

BLS_URL    = "https://algeria.blsspainglobal.com/DZA/bls/appointment"
HEADLESS   = True
MIN_DELAY  = 25   # ثانية
MAX_DELAY  = 40   # ثانية

# =============================================
#           LOGGING
# =============================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bls_monitor.log", encoding="utf-8"),
    ]
)
log = logging.getLogger(__name__)

# =============================================
#           TELEGRAM
# =============================================

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=10)
        if r.status_code == 200:
            log.info("[✅ Telegram] رسالة أُرسلت بنجاح")
        else:
            log.error(f"[❌ Telegram] {r.text}")
    except Exception as e:
        log.error(f"[❌ Telegram] خطأ: {e}")

# =============================================
#           BROWSER
# =============================================

async def make_browser(playwright):
    agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    ]
    browser = await playwright.chromium.launch(headless=HEADLESS)
    context = await browser.new_context(
        user_agent=random.choice(agents),
        viewport={"width": 1920, "height": 1080},
    )
    # إخفاء علامات الأتمتة
    await context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return browser, context

# =============================================
#           CHECK APPOINTMENTS
# =============================================

async def check_center(page, center: dict) -> int:
    """
    يفحص مركزاً واحداً ويرجع عدد المواعيد المتوفرة.
    """
    try:
        log.info(f"🔍 فحص {center['name']} ({center['name_ar']})...")
        await page.goto(BLS_URL, timeout=30000)
        await asyncio.sleep(random.uniform(2, 4))

        # اختيار المركز
        center_select = page.locator('select[name="CenterId"], select[id*="center"], select[id*="Center"]').first
        if await center_select.count() > 0:
            try:
                await center_select.select_option(label=center["name"])
                await asyncio.sleep(random.uniform(1, 2))
            except Exception:
                pass  # المركز غير موجود في هذا الموقع

        # انتظر تحميل التقويم
        await asyncio.sleep(random.uniform(2, 3))

        # عدّ الأيام المتاحة (غير معطّلة)
        available = await page.locator(
            "td.day:not(.disabled):not(.old):not(.new), "
            "td[class*='available'], "
            "tr.calendar-dates[data-remaining]:not([data-remaining='0'])"
        ).count()

        # محاولة قراءة data-remaining إذا وُجد
        slots_data = []
        rows = await page.locator("tr.calendar-dates[data-remaining]").all()
        for row in rows:
            remaining = await row.get_attribute("data-remaining")
            date_str  = await row.get_attribute("data-date-formatted") or ""
            try:
                if int(remaining or 0) > 0:
                    slots_data.append({"date": date_str, "remaining": int(remaining)})
            except Exception:
                pass

        if slots_data:
            return slots_data
        elif available > 0:
            return [{"date": "—", "remaining": available}]
        else:
            return []

    except Exception as e:
        log.error(f"[⚠️] خطأ في فحص {center['name']}: {e}")
        return []


async def check_all_centers(page) -> dict:
    """يفحص كل المراكز ويرجع النتائج."""
    results = {}
    for center in CENTERS:
        slots = await check_center(page, center)
        results[center["name_ar"]] = {
            "name": center["name"],
            "slots": slots
        }
        await asyncio.sleep(random.uniform(3, 6))
    return results

# =============================================
#           FORMAT MESSAGE
# =============================================

def format_message(results: dict) -> str | None:
    """يبني رسالة التلقرام. يرجع None إذا ما في مواعيد."""
    lines = []
    found_any = False

    for name_ar, data in results.items():
        slots = data["slots"]
        if slots:
            found_any = True
            lines.append(f"🚨 <b>مواعيد متوفرة في {data['name']} {name_ar} 🇩🇿</b>\n")
            for s in slots:
                if s["date"] and s["date"] != "—":
                    lines.append(f"📅 التاريخ: {s['date']}  ←  المواعيد: {s['remaining']}")
                else:
                    lines.append(f"📅 المواعيد المتوفرة: {s['remaining']}")
            lines.append(f"\n🔗 <a href='https://algeria.blsspainglobal.com/'>اضغط هنا للحجز الآن</a>")
            lines.append("")

    if not found_any:
        return None

    lines.append(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return "\n".join(lines)

# =============================================
#           MAIN LOOP
# =============================================

async def monitor():
    log.info("=" * 55)
    log.info("  🔔 BLS Algeria Appointment Monitor Started")
    log.info(f"  ⏱️  Check interval: {MIN_DELAY}–{MAX_DELAY} seconds")
    log.info("=" * 55)

    send_telegram(
        f"✅ <b>بوت مراقبة BLS الجزائر شغال!</b>\n\n"
        f"🌐 يراقب: الجزائر، وهران، قسنطينة، عنابة\n"
        f"⏱️ يفحص كل {MIN_DELAY}–{MAX_DELAY} ثانية\n"
        f"⏰ بدأ في: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    check_count = 0

    while True:
        async with async_playwright() as p:
            browser = None
            try:
                browser, context = await make_browser(p)
                page = await context.new_page()

                while True:
                    check_count += 1
                    log.info(f"\n{'─'*55}")
                    log.info(f"  🔍 فحص #{check_count} — {datetime.now().strftime('%H:%M:%S')}")
                    log.info(f"{'─'*55}")

                    results = await check_all_centers(page)
                    msg = format_message(results)

                    if msg:
                        send_telegram(msg)
                    else:
                        log.info("❌ لا توجد مواعيد متوفرة في أي مركز.")

                    delay = random.randint(MIN_DELAY, MAX_DELAY)
                    log.info(f"⏳ الفحص القادم بعد {delay} ثانية...")
                    await asyncio.sleep(delay)

            except KeyboardInterrupt:
                log.info("\n🛑 تم إيقاف البوت يدوياً.")
                send_telegram("🛑 <b>البوت تم إيقافه يدوياً.</b>")
                return

            except Exception as e:
                log.error(f"💥 خطأ: {e}")
                send_telegram(
                    f"⚠️ <b>خطأ في البوت - إعادة تشغيل</b>\n❗ {str(e)[:200]}\n⏰ {datetime.now().strftime('%H:%M:%S')}"
                )
                await asyncio.sleep(15)

            finally:
                if browser:
                    try:
                        await browser.close()
                    except Exception:
                        pass

# =============================================
#           ENTRY POINT
# =============================================

if __name__ == "__main__":
    asyncio.run(monitor())
