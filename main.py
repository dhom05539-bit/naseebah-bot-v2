
import os
import sqlite3
import logging
from datetime import datetime, timedelta
from telegram import KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ========== التوكن الجديد ==========
BOT_TOKEN = os.getenv("BOT_TOKEN") or "8602717112:AAG2938mP0gzTnuRYWvFuHcoK5i8rbI66rM"
PORT = int(os.environ.get("PORT", 10000))
WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("RENDER_EXTERNAL_HOSTNAME") or "https://naseebahbot-2.onrender.com"
if not WEBHOOK_URL.startswith("https://"):
    WEBHOOK_URL = f"https://{WEBHOOK_URL}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

def get_user(tid):
    conn = sqlite3.connect("attendance.db")
    c = conn.cursor()
    c.execute("SELECT name, branch FROM users WHERE telegram_id=?", (tid,))
    row = c.fetchone()
    conn.close()
    return row

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
        await update.message.reply_text(f"أهلاً {name} 👋\nفرعك: {branch}\n🟢 نظام نُسيبه V2 شغال 24/7\n@NaseebahV2_bot", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
    else:
        kb = []
        names = list(EMPLOYEES.keys())
        for i in range(0, len(names), 2):
            row = [InlineKeyboardButton(names[j], callback_data=f"reg_{names[j]}") for j in range(i, min(i+2, len(names)))]
            kb.append(row)
        await update.message.reply_text("👋 مرحباً في بوت بصمة نُسيبه V2\nاختر اسمك:", reply_markup=InlineKeyboardMarkup(kb))

async def register_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    name = q.data.replace("reg_", "")
    branch = EMPLOYEES.get(name, "فرع ساحة دان")
    conn = sqlite3.connect("attendance.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users VALUES (?,?,?,?)", (q.from_user.id, name, branch, datetime.now().isoformat()))
    conn.commit(); conn.close()
    await q.edit_message_text(f"✅ تم تسجيلك: {name}\n🏢 {branch}\n\nارسل /start")

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ud = get_user(uid)
    if not ud:
        await update.message.reply_text("سجل /start أولاً")
        return
    name, assigned = ud
    lat = update.message.location.latitude
    lon = update.message.location.longitude
    closest, mind = None, float('inf')
    for bn, bd in BRANCHES.items():
        d = haversine(lat, lon, bd["lat"], bd["lon"])
        if d < mind:
            mind = d
            closest = bn
    action = context.user_data.get("action", "in")
    allowed = BRANCHES[closest]["radius"]
    if mind > allowed:
        await update.message.reply_text(f"❌ بعيد {int(mind)}م عن {closest} - لازم داخل {allowed}م")
        return
    today = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%H:%M:%S")
    now_t = datetime.now()
    from datetime import timedelta
    import datetime as dt
    work = dt.datetime.strptime("08:00", "%H:%M").replace(year=now_t.year, month=now_t.month, day=now_t.day)
    late = work + timedelta(minutes=15)
    conn = sqlite3.connect("attendance.db")
    c = conn.cursor()
    if action == "in":
        c.execute("SELECT id FROM attendance WHERE telegram_id=? AND date=? AND check_in IS NOT NULL", (uid, today))
        if c.fetchone():
            await update.message.reply_text("⚠️ مسجل حضور اليوم")
            conn.close()
            return
        status = "متأخر" if now_t > late else "حاضر"
        c.execute("INSERT INTO attendance (telegram_id, name, branch, date, check_in, check_in_lat, check_in_lon, status) VALUES (?,?,?,?,?,?,?,?)",
                  (uid, name, closest, today, now_str, lat, lon, status))
        conn.commit()
        await update.message.reply_text(f"✅ حضور\n{name}\n{closest}\n{now_str} - {int(mind)}م\n{status}")
    else:
        c.execute("SELECT id, check_out FROM attendance WHERE telegram_id=? AND date=? ORDER BY id DESC LIMIT 1", (uid, today))
        row = c.fetchone()
        if not row:
            await update.message.reply_text("❌ ما سجلت حضور")
            conn.close()
            return
        if row[1]:
            await update.message.reply_text("⚠️ مسجل انصراف")
            conn.close()
            return
        c.execute("UPDATE attendance SET check_out=?, check_out_lat=?, check_out_lon=? WHERE id=?", (now_str, lat, lon, row[0]))
        conn.commit()
        await update.message.reply_text(f"✅ انصراف\n{name}\n{now_str}")
    conn.close()

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text or ""
    if "حضور" in t:
        context.user_data["action"] = "in"
        await update.message.reply_text("📍 أرسل موقعك:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("📍 إرسال موقعي", request_location=True)]], resize_keyboard=True))
    elif "انصراف" in t:
        context.user_data["action"] = "out"
        await update.message.reply_text("📍 أرسل موقعك:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("📍 إرسال موقعي", request_location=True)]], resize_keyboard=True))
    elif "سجلي" in t:
        conn = sqlite3.connect("attendance.db")
        c = conn.cursor()
        c.execute("SELECT date, check_in, check_out, branch, status FROM attendance WHERE telegram_id=? ORDER BY date DESC LIMIT 7", (update.effective_user.id,))
        rows = c.fetchall(); conn.close()
        msg = "\n".join([f"{r[0]} {r[3]} دخول {r[1]} خروج {r[2] or '-'} {r[4]}" for r in rows]) if rows else "لا يوجد سجل"
        await update.message.reply_text(msg)
    elif "تقرير" in t:
        today = datetime.now().strftime("%Y-%m-%d")
        conn = sqlite3.connect("attendance.db")
        c = conn.cursor()
        c.execute("SELECT name, branch, check_in, check_out, status FROM attendance WHERE date=? ORDER BY check_in", (today,))
        rows = c.fetchall(); conn.close()
        if not rows:
            await update.message.reply_text(f"لا يوجد حضور اليوم {today}")
        else:
            msg = f"📋 تقرير {today}:\n"
            for r in rows:
                msg += f"{r[0]} | {r[1]} | {r[2]} - {r[3] or '--'} | {r[4]}\n"
            await update.message.reply_text(msg)
    else:
        await start(update, context)

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(register_callback, pattern="^reg_"))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    webhook_full = f"{WEBHOOK_URL}/{BOT_TOKEN}"
    logger.info(f"🚀 V2 Webhook: {webhook_full} on port {PORT}")
    app.run_webhook(listen="0.0.0.0", port=PORT, url_path=BOT_TOKEN, webhook_url=webhook_full, drop_pending_updates=True)

if __name__ == "__main__":
    main()
