
import os
import sqlite3
import logging
from datetime import datetime, timedelta
from telegram import KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ========== الإعدادات ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    # للتجربة المحلية فقط - في Render لازم تحطه في Environment
    BOT_TOKEN = "ضع_التوكن_هنا_او_في_Environment"

PORT = int(os.environ.get("PORT", 10000))
WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("RENDER_EXTERNAL_HOSTNAME") or "https://naseebahbot-2.onrender.com"
if not WEBHOOK_URL.startswith("https://"):
    WEBHOOK_URL = f"https://{WEBHOOK_URL}"

# إعداد السجلات عشان نشوف الأخطاء
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== الفروع والموظفين ==========
BRANCHES = {
    "فرع ساحة دان": {"lat": 21.311746875, "lon": 39.51455625, "radius": 80},
    "فرع درايف ثرو العوالي": {"lat": 21.311863594, "lon": 39.51664031, "radius": 80},
    "فرع درايف ثرو الشوقيه": {"lat": 21.312759375, "lon": 39.39463125, "radius": 80},
}
EMPLOYEES = {
    "احمد": "فرع ساحة دان", "محمود": "فرع ساحة دان", "عبدالعزيز": "فرع ساحة دان",
    "نواف": "فرع درايف ثرو العوالي", "حنشون": "فرع درايف ثرو العوالي", "بدوي": "فرع درايف ثرو العوالي",
    "علي": "فرع درايف ثرو الشوقيه", "اسامه": "فرع درايف ثرو الشوقيه",
}
WORK_START = "08:00"
ALLOWED_LATE_MINUTES = 15

def haversine(lat1, lon1, lat2, lon2):
    import math
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def init_db():
    conn = sqlite3.connect("attendance.db")
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS users (telegram_id INTEGER PRIMARY KEY, name TEXT, branch TEXT, created_at TEXT)")
    c.execute("""CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER, name TEXT, branch TEXT, date TEXT,
        check_in TEXT, check_out TEXT,
        check_in_lat REAL, check_in_lon REAL,
        check_out_lat REAL, check_out_lon REAL,
        status TEXT
    )""")
    conn.commit(); conn.close()
    logger.info("✅ قاعدة البيانات جاهزة")

def get_user(tid):
    conn = sqlite3.connect("attendance.db")
    c = conn.cursor()
    c.execute("SELECT name, branch FROM users WHERE telegram_id=?", (tid,))
    row = c.fetchone()
    conn.close()
    return row

# ========== أوامر البوت ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ex = get_user(uid)
    if ex:
        name, branch = ex
        kb = [
            [KeyboardButton("📍 تسجيل حضور")],
            [KeyboardButton("🚪 تسجيل انصراف")],
            [KeyboardButton("📊 سجلي اليوم"), KeyboardButton("🏢 الفروع")],
            [KeyboardButton("📋 تقرير اليوم")]
        ]
        await update.message.reply_text(
            f"أهلاً {name} 👋\nفرعك: {branch}\n🟢 النظام شغال 24/7\nاختر من القائمة:",
            reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
        )
    else:
        kb = []
        names = list(EMPLOYEES.keys())
        for i in range(0, len(names), 2):
            row = [InlineKeyboardButton(names[j], callback_data=f"reg_{names[j]}") for j in range(i, min(i+2, len(names)))]
            kb.append(row)
        await update.message.reply_text(
            "👋 مرحباً في بوت بصمة نُسيبه\n\nاختر اسمك للتسجيل:",
            reply_markup=InlineKeyboardMarkup(kb)
        )

async def register_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    name = q.data.replace("reg_", "")
    branch = EMPLOYEES.get(name, "فرع ساحة دان")
    conn = sqlite3.connect("attendance.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users VALUES (?,?,?,?)", (q.from_user.id, name, branch, datetime.now().isoformat()))
    conn.commit(); conn.close()
    await q.edit_message_text(f"✅ تم تسجيلك بنجاح\n👤 الاسم: {name}\n🏢 الفرع: {branch}\n\nالآن ارسل /start")

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ud = get_user(uid)
    if not ud:
        await update.message.reply_text("❌ سجل أولاً بالأمر /start")
        return
    name, assigned = ud
    lat = update.message.location.latitude
    lon = update.message.location.longitude

    # أقرب فرع
    closest, mind = None, float('inf')
    for bn, bd in BRANCHES.items():
        d = haversine(lat, lon, bd["lat"], bd["lon"])
        if d < mind:
            mind = d
            closest = bn

    action = context.user_data.get("action", "in")
    allowed = BRANCHES[closest]["radius"]

    if mind > allowed:
        await update.message.reply_text(f"❌ أنت بعيد {int(mind)} متر عن {closest}\nيجب أن تكون داخل {allowed} متر")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%H:%M:%S")
    now_t = datetime.now()
    work = datetime.strptime(WORK_START, "%H:%M").replace(year=now_t.year, month=now_t.month, day=now_t.day)
    late = work + timedelta(minutes=ALLOWED_LATE_MINUTES)

    conn = sqlite3.connect("attendance.db")
    c = conn.cursor()

    if action == "in":
        c.execute("SELECT id FROM attendance WHERE telegram_id=? AND date=? AND check_in IS NOT NULL", (uid, today))
        if c.fetchone():
            await update.message.reply_text("⚠️ سجلت حضور اليوم مسبقاً")
            conn.close()
            return
        status = "متأخر ⏰" if now_t > late else "حاضر ✅"
        c.execute("INSERT INTO attendance (telegram_id, name, branch, date, check_in, check_in_lat, check_in_lon, status) VALUES (?,?,?,?,?,?,?,?)",
                  (uid, name, closest, today, now_str, lat, lon, status))
        conn.commit()
        await update.message.reply_text(f"✅ تم تسجيل الحضور\n👤 {name}\n🏢 {closest}\n⏰ {now_str}\n📍 {int(mind)}م\n📌 {status}")
    else:
        c.execute("SELECT id, check_in, check_out FROM attendance WHERE telegram_id=? AND date=? ORDER BY id DESC LIMIT 1", (uid, today))
        row = c.fetchone()
        if not row:
            await update.message.reply_text("❌ لم تسجل حضور اليوم")
            conn.close()
            return
        if row[2]:
            await update.message.reply_text("⚠️ سجلت انصراف اليوم مسبقاً")
            conn.close()
            return
        c.execute("UPDATE attendance SET check_out=?, check_out_lat=?, check_out_lon=? WHERE id=?", (now_str, lat, lon, row[0]))
        conn.commit()
        await update.message.reply_text(f"✅ تم تسجيل الانصراف\n👤 {name}\n🏢 {closest}\n⏰ {now_str}")
    conn.close()

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text or ""
    if "حضور" in t:
        context.user_data["action"] = "in"
        await update.message.reply_text("📍 أرسل موقعك الحالي:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("📍 إرسال موقعي", request_location=True)]], resize_keyboard=True))
    elif "انصراف" in t:
        context.user_data["action"] = "out"
        await update.message.reply_text("📍 أرسل موقعك الحالي:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("📍 إرسال موقعي", request_location=True)]], resize_keyboard=True))
    elif "سجلي" in t:
        conn = sqlite3.connect("attendance.db")
        c = conn.cursor()
        c.execute("SELECT date, check_in, check_out, branch, status FROM attendance WHERE telegram_id=? ORDER BY date DESC LIMIT 7", (update.effective_user.id,))
        rows = c.fetchall(); conn.close()
        if not rows:
            await update.message.reply_text("لا يوجد سجل")
        else:
            msg = "📊 آخر 7 أيام:\n\n"
            for r in rows:
                msg += f"{r[0]} - {r[3]}\nدخول {r[1]} | خروج {r[2] or '--'} | {r[4]}\n---\n"
            await update.message.reply_text(msg)
    elif "تقرير" in t or "report" in t.lower():
        today = datetime.now().strftime("%Y-%m-%d")
        conn = sqlite3.connect("attendance.db")
        c = conn.cursor()
        c.execute("SELECT name, branch, check_in, check_out, status FROM attendance WHERE date=? ORDER BY check_in", (today,))
        rows = c.fetchall(); conn.close()
        if not rows:
            await update.message.reply_text(f"📋 لا يوجد حضور اليوم {today}")
        else:
            msg = f"📋 تقرير حضور {today}:\n\n"
            for r in rows:
                msg += f"👤 {r[0]} | {r[1]}\n⏰ {r[2]} - {r[3] or '--'} | {r[4]}\n---\n"
            await update.message.reply_text(msg)
    elif "فروع" in t or "الفروع" in t:
        msg = "🏢 فروع نُسيبه (نطاق 80م):\n\n"
        for bn in BRANCHES:
            msg += f"📍 {bn}\n"
        await update.message.reply_text(msg)
    else:
        await start(update, context)

def main():
    init_db()
    if BOT_TOKEN.startswith("ضع_"):
        logger.error("❌ ضع توكن البوت في متغير البيئة BOT_TOKEN في Render")
        return

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("report", handle_text))
    app.add_handler(CallbackQueryHandler(register_callback, pattern="^reg_"))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    webhook_full = f"{WEBHOOK_URL}/{BOT_TOKEN}"
    logger.info(f"🚀 Starting Webhook mode on port {PORT}")
    logger.info(f"🔗 Webhook URL: {webhook_full}")

    # هذه هي الطريقة الصحيحة لـ Render
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,
        webhook_url=webhook_full,
        drop_pending_updates=True
    )

if __name__ == "__main__":
    main()
