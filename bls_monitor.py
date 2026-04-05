"""
=======================================================
  BLS Algeria Spain Visa Appointment Monitor Bot
  يراقب مواعيد BLS الجزائر ويرسل عدد المواعيد المتوفرة
=======================================================

INSTALLATION:
  pip install playwright requests
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
from playwright_stealth import stealth_async

# =============================================
#           USER CONFIGURATION - عدّل هنا
# =============================================

TELEGRAM_BOT_TOKEN = "8674136162:AAF7erCPgpP81NkS0NSz_7ssdruOmEW9eNc"
TELEGRAM_CHAT_ID   = "8499305437"

BLS_URL   = "https://algeria.blsspainglobal.com/DZA/bls/appointment"
HEADLESS  = True
MIN_DELAY = 25   # ثانية
MAX_DELAY = 40   # ثانية

# =============================================
#   قائمة المراكز والأنواع الكاملة
# =============================================

# كل التركيبات الممكنة: Location + Visa Type + Visa Sub Type + Category
COMBINATIONS = []

# الجزائر العاصمة - Algiers
for sub in ["ALG 1", "ALG 2", "ALG 3", "ALG 4"]:
    for visa_type in [
        "First application / première demande",
        "Schengen Visa",
        "Schengen visa (Estonia)",
        "Visa renewal / renouvellement de visa",
    ]:
        for category in ["Normal", "Premium", "Prime Time"]:
            COMBINATIONS.append({
                "location":   "Algiers",
                "location_ar": "الجزائر العاصمة",
                "visa_type":  visa_type,
                "sub_type":   sub,
                "category":   category,
            })

# وهران - Oran
for sub in ["Oran 2", "Oran 3", "Oran 4"]:
    for visa_type in [
        "First application / première demande",
        "Schengen Visa",
        "Schengen visa (Estonia)",
        "Visa renewal / renouvellement de visa",
    ]:
        for category in ["Normal", "Premium", "Prime Time"]:
            COMBINATIONS.append({
                "location":   "Oran",
                "location_ar": "وهران",
                "visa_type":  visa_type,
                "sub_type":   sub,
                "category":   category,
            })

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
            log.info("[✅ Telegram] رسالة أُرسلت")
        else:
            log.error(f"[❌ Telegram] {r.text[:200]}")
    except Exception as e:
        log.error(f"[❌ Telegram] {e}")

# =============================================
#           BROWSER
# =============================================

async def make_browser(playwright):
    agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    ]
    # محاولة تشغيل المتصفح مع معالجة الأخطاء الشائعة في Railway
    try:
        browser = await playwright.chromium.launch(headless=HEADLESS)
    except Exception as e:
        log.error(f"Failed to launch chromium: {e}")
        # محاولة التثبيت التلقائي إذا فشل التشغيل (كحل أخير)
        import subprocess
        subprocess.run(["playwright", "install", "chromium"], check=True)
        browser = await playwright.chromium.launch(headless=HEADLESS)

    context = await browser.new_context(
        user_agent=random.choice(agents),
        viewport={"width": 1366, "height": 768},
        locale="fr-FR",
    )
    
    # استخدام stealth لمنع اكتشاف البوت بشكل أفضل
    page = await context.new_page()
    await stealth_async(page)
    
    return browser, context, page

# =============================================
#   اختيار عنصر من dropdown بالنص
# =============================================

async def select_by_text(page, selector: str, text: str) -> bool:
    """يختار خيار من dropdown بالنص. يرجع True إذا نجح."""
    try:
        locator = page.locator(selector).first
        if await locator.count() == 0:
            return False
        await locator.select_option(label=text)
        await asyncio.sleep(random.uniform(0.8, 1.5))
        return True
    except Exception:
        return False

# =============================================
#   فحص تركيبة واحدة
# =============================================

async def check_combination(page, combo: dict) -> list:
    """
    يفحص تركيبة (Location + VisaType + SubType + Category)
    ويرجع قائمة المواعيد المتوفرة.
    """
    try:
        await page.goto(BLS_URL, timeout=30000, wait_until="domcontentloaded")
        await asyncio.sleep(random.uniform(1.5, 3))

        # 1. اختيار Location
        loc_ok = await select_by_text(
            page,
            'select[name*="ocation"], select[id*="ocation"], select[id*="Location"]',
            combo["location"]
        )
        if not loc_ok:
            # جرب أي select أول
            selects = await page.locator("select").all()
            if selects:
                try:
                    await selects[0].select_option(label=combo["location"])
                    await asyncio.sleep(1)
                except Exception:
                    pass

        # 2. اختيار Visa Type
        await select_by_text(
            page,
            'select[name*="isa"], select[id*="isa"], select[id*="Visa"]',
            combo["visa_type"]
        )

        # 3. اختيار Visa Sub Type
        await asyncio.sleep(random.uniform(0.5, 1))
        await select_by_text(
            page,
            'select[name*="ub"], select[id*="ub"], select[id*="Sub"]',
            combo["sub_type"]
        )

        # 4. اختيار Category
        await asyncio.sleep(random.uniform(0.5, 1))
        await select_by_text(
            page,
            'select[name*="ategory"], select[id*="ategory"], select[id*="Category"]',
            combo["category"]
        )

        # 5. Submit لعرض التقويم
        await asyncio.sleep(random.uniform(0.5, 1))
        submit_btn = page.locator('button[type="submit"], input[type="submit"], button:has-text("Submit")').first
        if await submit_btn.count() > 0:
            await submit_btn.click()
            await asyncio.sleep(random.uniform(2, 4))

        # 6. قراءة المواعيد المتوفرة
        slots = []

        # محاولة 1: صفوف التقويم مع data-remaining
        rows = await page.locator("[data-remaining]").all()
        for row in rows:
            remaining = await row.get_attribute("data-remaining")
            date_str  = await row.get_attribute("data-date") or \
                        await row.get_attribute("data-date-formatted") or ""
            try:
                if int(remaining or 0) > 0:
                    slots.append({"date": date_str, "count": int(remaining)})
            except Exception:
                pass

        # محاولة 2: أيام التقويم المتاحة (غير معطّلة)
        if not slots:
            available_days = await page.locator(
                "td.day:not(.disabled):not(.old):not(.new):not(.off)"
            ).all()
            for day in available_days:
                day_text = await day.inner_text()
                if day_text.strip().isdigit():
                    slots.append({"date": day_text.strip(), "count": 1})

        # محاولة 3: رسالة "No appointments available"
        page_text = await page.inner_text("body")
        if "no appointment" in page_text.lower() or "aucun rendez" in page_text.lower():
            return []

        return slots

    except Exception as e:
        log.debug(f"خطأ في {combo['sub_type']} {combo['category']}: {e}")
        return []

# =============================================
#   فحص كل التركيبات
# =============================================

async def check_all(page) -> dict:
    """
    يفحص كل التركيبات ويجمع النتائج حسب المركز.
    """
    # نجمع النتائج: key = (location, sub_type, category)
    found = {}

    for combo in COMBINATIONS:
        key = f"{combo['location']}|{combo['sub_type']}|{combo['category']}"
        log.debug(f"🔍 {combo['location']} / {combo['sub_type']} / {combo['category']}")

        slots = await check_combination(page, combo)
        if slots:
            found[key] = {**combo, "slots": slots}
            log.info(f"✅ وُجدت مواعيد: {combo['location']} {combo['sub_type']} [{combo['category']}] — {len(slots)} تاريخ")

        # تأخير قصير بين الطلبات
        await asyncio.sleep(random.uniform(1, 2))

    return found

# =============================================
#   بناء رسالة التلقرام
# =============================================

def format_message(found: dict) -> str | None:
    if not found:
        return None

    lines = []
    # تجميع حسب المركز
    by_location = {}
    for data in found.values():
        loc = data["location"]
        if loc not in by_location:
            by_location[loc] = []
        by_location[loc].append(data)

    for loc, items in by_location.items():
        loc_ar = items[0]["location_ar"]
        lines.append(f"🚨 <b>مواعيد متوفرة في {loc} {loc_ar} 🇩🇿</b>\n")
        for item in items:
            lines.append(f"📌 <b>{item['sub_type']}</b> — {item['category']}")
            lines.append(f"   نوع التأشيرة: {item['visa_type']}")
            for s in item["slots"]:
                if s["date"]:
                    lines.append(f"   📅 {s['date']}  ←  المواعيد: {s['count']}")
                else:
                    lines.append(f"   📅 المواعيد المتوفرة: {s['count']}")
            lines.append("")
        lines.append(f"🔗 <a href='https://algeria.blsspainglobal.com/'>اضغط هنا للحجز الآن</a>\n")

    lines.append(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return "\n".join(lines)

# =============================================
#           MAIN LOOP
# =============================================

async def monitor():
    log.info("=" * 60)
    log.info("  🔔 BLS Algeria Appointment Monitor")
    log.info(f"  📍 المراكز: ALG1-4 | Oran2-4")
    log.info(f"  🗂️  الفئات: Normal | Premium | Prime Time")
    log.info(f"  ⏱️  الفحص كل: {MIN_DELAY}–{MAX_DELAY} ثانية")
    log.info("=" * 60)

    send_telegram(
        f"✅ <b>بوت مراقبة BLS الجزائر شغال!</b>\n\n"
        f"📍 المراكز:\n"
        f"  • الجزائر: ALG 1, ALG 2, ALG 3, ALG 4\n"
        f"  • وهران: Oran 2, Oran 3, Oran 4\n\n"
        f"🗂️ الفئات: Normal | Premium | Prime Time\n"
        f"⏱️ يفحص كل {MIN_DELAY}–{MAX_DELAY} ثانية\n"
        f"⏰ بدأ في: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    check_count = 0

    while True:
        async with async_playwright() as p:
            browser = None
            try:
                browser, context, page = await make_browser(p)

                while True:
                    check_count += 1
                    log.info(f"\n{'─'*60}")
                    log.info(f"  🔍 فحص #{check_count} — {datetime.now().strftime('%H:%M:%S')}")
                    log.info(f"{'─'*60}")

                    found = await check_all(page)
                    msg = format_message(found)

                    if msg:
                        send_telegram(msg)
                    else:
                        log.info("❌ لا توجد مواعيد متوفرة في أي مركز.")

                    delay = random.randint(MIN_DELAY, MAX_DELAY)
                    log.info(f"⏳ الفحص القادم بعد {delay} ثانية...")
                    await asyncio.sleep(delay)

            except KeyboardInterrupt:
                log.info("\n🛑 تم إيقاف البوت.")
                send_telegram("🛑 <b>البوت تم إيقافه.</b>")
                return

            except Exception as e:
                log.error(f"💥 خطأ: {e}")
                send_telegram(
                    f"⚠️ <b>خطأ - إعادة تشغيل</b>\n❗ {str(e)[:200]}\n"
                    f"⏰ {datetime.now().strftime('%H:%M:%S')}"
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
