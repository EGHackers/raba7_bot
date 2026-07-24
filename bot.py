import json
import sqlite3
import os
import requests
import asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from datetime import datetime

from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ---------- الإعدادات ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATA_URL = os.environ.get("DATA_URL", "https://raw.githubusercontent.com/your-username/rab7_bot/main/platforms.json")
DB_FILE = "bot_data.db"

# المشرف (أنت)
ADMIN_IDS = [1461088326]

# حالات المحادثة
SEARCH_WAIT = 1
ADD_NAME, ADD_CATEGORY, ADD_LINK, ADD_MIN = range(2, 6)
BROADCAST_MSG = 6

# ---------- خادم ويب صغير (لـ UptimeRobot) ----------
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_server():
    server = HTTPServer(('0.0.0.0', 8080), HealthHandler)
    server.serve_forever()

threading.Thread(target=run_server, daemon=True).start()

# ---------- قاعدة البيانات ----------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS votes (
            platform_name TEXT,
            user_id INTEGER,
            vote_type TEXT,
            PRIMARY KEY (platform_name, user_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS local_platforms (
            name TEXT PRIMARY KEY,
            category TEXT,
            link TEXT,
            min_withdraw TEXT,
            added_date TEXT
        )
    """)
    conn.commit()
    conn.close()

def add_user(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def cast_vote(platform_name, user_id, vote_type):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO votes VALUES (?, ?, ?)", (platform_name, user_id, vote_type))
        conn.commit()
        status = "✅ تم تسجيل تصويتك"
    except sqlite3.IntegrityError:
        c.execute("UPDATE votes SET vote_type = ? WHERE platform_name = ? AND user_id = ?",
                  (vote_type, platform_name, user_id))
        conn.commit()
        status = "🔄 تم تحديث تصويتك"
    c.execute("SELECT vote_type, COUNT(*) FROM votes WHERE platform_name = ? GROUP BY vote_type", (platform_name,))
    rows = c.fetchall()
    stats = {"trust": 0, "suspect": 0}
    for vtype, cnt in rows:
        stats[vtype] = cnt
    conn.close()
    return {"status": status, "stats": stats}

def get_platform_stats(platform_name):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT vote_type, COUNT(*) FROM votes WHERE platform_name = ? GROUP BY vote_type", (platform_name,))
    rows = c.fetchall()
    trust = suspect = 0
    for vtype, cnt in rows:
        if vtype == "trust": trust = cnt
        elif vtype == "suspect": suspect = cnt
    conn.close()
    return trust, suspect

def add_local_platform(name, category, link, min_withdraw):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    added_date = datetime.now().strftime("%Y-%m-%d")
    try:
        c.execute("INSERT INTO local_platforms (name, category, link, min_withdraw, added_date) VALUES (?, ?, ?, ?, ?)",
                  (name, category, link, min_withdraw, added_date))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    conn.close()
    return success

def get_local_platforms():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT name, category, link, min_withdraw, added_date FROM local_platforms")
    rows = c.fetchall()
    conn.close()
    return [{"name": r[0], "category": r[1], "link": r[2], "min_withdraw": r[3], "added_date": r[4]} for r in rows]

def load_platforms():
    remote = []
    try:
        resp = requests.get(DATA_URL, timeout=10)
        resp.raise_for_status()
        remote = json.loads(resp.text)
    except Exception:
        pass
    local = get_local_platforms()
    return remote + local

# ---------- لوحات المفاتيح ----------
main_keyboard = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📋 أحدث المنصات")],
        [KeyboardButton("📂 الفئات"), KeyboardButton("🔍 بحث عن منصة")],
    ],
    resize_keyboard=True
)

admin_keyboard = ReplyKeyboardMarkup(
    [
        [KeyboardButton("➕ إضافة منصة"), KeyboardButton("📢 إرسال إعلان")],
        [KeyboardButton("📋 منصاتي المحلية"), KeyboardButton("🔙 رجوع")],
    ],
    resize_keyboard=True
)

def is_admin(user_id):
    return user_id in ADMIN_IDS

# ---------- أوامر المستخدم ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    add_user(user_id)
    if is_admin(user_id):
        await update.message.reply_text(
            "🤖 <b>بوت دليل المنصات - وضع المشرف</b>\nاختر من القائمة:",
            parse_mode="HTML", reply_markup=admin_keyboard
        )
    else:
        await update.message.reply_text(
            "🤖 <b>بوت دليل منصات الربح</b>\nاختر ما تريده:",
            parse_mode="HTML", reply_markup=main_keyboard
        )

async def button_latest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    platforms = load_platforms()
    if not platforms:
        await update.message.reply_text("⚠️ لا توجد منصات.")
        return
    latest_plats = sorted(platforms, key=lambda x: x.get("added_date", ""), reverse=True)[:5]
    for p in latest_plats:
        trust, suspect = get_platform_stats(p["name"])
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"👍 موثوق ({trust})", callback_data=f"vote|{p['name']}|trust"),
             InlineKeyboardButton(f"👎 مشبوه ({suspect})", callback_data=f"vote|{p['name']}|suspect")]
        ])
        warning = " ⚠️" if suspect > trust and (trust + suspect) >= 3 else ""
        text = (
            f"📌 <b>{p['name']}{warning}</b>\n"
            f"🏷️ {p.get('category', 'غير محدد')}\n"
            f"🔗 <a href='{p['link']}'>رابط التسجيل</a>\n"
            f"💰 السحب الأدنى: {p.get('min_withdraw', 'غير معروف')}\n"
            f"📅 أُضيفت: {p.get('added_date', 'غير معروف')}"
        )
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)

async def button_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    platforms = load_platforms()
    cats = {}
    for p in platforms:
        cat = p.get("category", "أخرى")
        cats[cat] = cats.get(cat, 0) + 1
    if not cats:
        await update.message.reply_text("لا توجد فئات بعد.")
        return
    text = "📂 <b>الفئات:</b>\n" + "\n".join([f"• {c}: {n}" for c, n in cats.items()])
    await update.message.reply_text(text, parse_mode="HTML")

async def button_search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔍 أرسل اسم المنصة:",
        reply_markup=ReplyKeyboardMarkup([["/cancel"]], resize_keyboard=True)
    )
    return SEARCH_WAIT

async def button_search_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyword = update.message.text.strip()
    platforms = load_platforms()
    results = [p for p in platforms if keyword.lower() in p["name"].lower()]
    if not results:
        await update.message.reply_text("🔍 لا نتائج.")
        return ConversationHandler.END
    for p in results[:3]:
        trust, suspect = get_platform_stats(p["name"])
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"👍 ({trust})", callback_data=f"vote|{p['name']}|trust"),
             InlineKeyboardButton(f"👎 ({suspect})", callback_data=f"vote|{p['name']}|suspect")]
        ])
        text = f"✅ <b>{p['name']}</b>\n🏷️ {p.get('category','')}\n🔗 {p['link']}"
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)
    return ConversationHandler.END

async def cancel_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم الإلغاء.", reply_markup=main_keyboard)
    return ConversationHandler.END

async def vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, platform_name, vote_type = query.data.split("|")
    result = cast_vote(platform_name, query.from_user.id, vote_type)
    stats = result["stats"]
    new_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"👍 موثوق ({stats['trust']})", callback_data=f"vote|{platform_name}|trust"),
         InlineKeyboardButton(f"👎 مشبوه ({stats['suspect']})", callback_data=f"vote|{platform_name}|suspect")]
    ])
    await query.edit_message_reply_markup(reply_markup=new_keyboard)
    await query.message.reply_text(result["status"])

# ---------- لوحة تحكم المشرف ----------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ غير مسموح.")
        return
    await update.message.reply_text("🔧 <b>لوحة التحكم:</b>", parse_mode="HTML", reply_markup=admin_keyboard)

async def admin_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # العودة إلى القائمة المناسبة حسب المستخدم
    await start(update, context)

# --- إضافة منصة (محادثة) ---
async def add_platform_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    await update.message.reply_text(
        "➕ أدخل <b>اسم المنصة</b>:",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup([["/cancel"]], resize_keyboard=True)
    )
    return ADD_NAME

async def add_platform_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_platform"] = {"name": update.message.text}
    await update.message.reply_text("📂 أدخل <b>الفئة</b> (مثلاً: استطلاعات، تعدين):", parse_mode="HTML")
    return ADD_CATEGORY

async def add_platform_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_platform"]["category"] = update.message.text
    await update.message.reply_text("🔗 أرسل <b>رابط المنصة</b>:", parse_mode="HTML")
    return ADD_LINK

async def add_platform_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_platform"]["link"] = update.message.text
    await update.message.reply_text("💰 أدخل <b>الحد الأدنى للسحب</b> (مثلاً: 5$):", parse_mode="HTML")
    return ADD_MIN

async def add_platform_min(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data["new_platform"]
    data["min_withdraw"] = update.message.text
    success = add_local_platform(data["name"], data["category"], data["link"], data["min_withdraw"])
    if success:
        await update.message.reply_text("✅ تمت إضافة المنصة بنجاح!", reply_markup=admin_keyboard)
    else:
        await update.message.reply_text("⚠️ المنصة موجودة مسبقاً.", reply_markup=admin_keyboard)
    return ConversationHandler.END

# --- إرسال إعلان (محادثة) ---
async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    await update.message.reply_text(
        "📢 أرسل نص الرسالة التي تريد إرسالها لجميع المستخدمين:",
        reply_markup=ReplyKeyboardMarkup([["/cancel"]], resize_keyboard=True)
    )
    return BROADCAST_MSG

async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text
    users = get_all_users()
    success = 0
    for user_id in users:
        try:
            await context.bot.send_message(chat_id=user_id, text=msg)
            success += 1
            await asyncio.sleep(0.05)  # احترام حدود API
        except:
            pass
    await update.message.reply_text(f"✅ تم الإرسال إلى {success} مستخدم.", reply_markup=admin_keyboard)
    return ConversationHandler.END

# --- عرض المنصات المحلية ---
async def show_local_platforms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    local = get_local_platforms()
    if not local:
        await update.message.reply_text("لا توجد منصات محلية.")
        return
    text = "📋 <b>المنصات المضافة محلياً:</b>\n"
    for p in local:
        text += f"🔹 {p['name']} - {p['category']} - {p['link']}\n"
    await update.message.reply_text(text, parse_mode="HTML")

# ---------- المشغّل الرئيسي ----------
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # محادثة البحث
    search_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 بحث عن منصة$"), button_search_start)],
        states={SEARCH_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, button_search_receive)]},
        fallbacks=[CommandHandler("cancel", cancel_search)],
    )

    # محادثة إضافة منصة
    add_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ إضافة منصة$"), add_platform_start)],
        states={
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_platform_name)],
            ADD_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_platform_category)],
            ADD_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_platform_link)],
            ADD_MIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_platform_min)],
        },
        fallbacks=[CommandHandler("cancel", cancel_search)],
    )

    # محادثة الإعلان
    broadcast_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 إرسال إعلان$"), broadcast_start)],
        states={BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_send)]},
        fallbacks=[CommandHandler("cancel", cancel_search)],
    )

    # تسجيل المعالجات
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(MessageHandler(filters.Regex("^📋 أحدث المنصات$"), button_latest))
    app.add_handler(MessageHandler(filters.Regex("^📂 الفئات$"), button_categories))
    app.add_handler(MessageHandler(filters.Regex("^📋 منصاتي المحلية$"), show_local_platforms))
    app.add_handler(MessageHandler(filters.Regex("^🔙 رجوع$"), admin_back))
    app.add_handler(search_conv)
    app.add_handler(add_conv)
    app.add_handler(broadcast_conv)
    app.add_handler(CallbackQueryHandler(vote_callback, pattern="^vote\\|"))

    print("✅ البوت يعمل...")
    app.run_polling()

if __name__ == "__main__":
    main()
