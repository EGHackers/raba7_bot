import json
import sqlite3
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

BOT_TOKEN = "8800017634:AAEVSAqVuVzk_eXkaxB8_-kWU87YL0tgah0"
DATA_URL = "ضع_رابط_الملف_الخام_هنا"
DB_FILE = "ratings.db"

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
    conn.commit()
    conn.close()

def cast_vote(platform_name: str, user_id: int, vote_type: str) -> dict:
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

def get_platform_stats(platform_name: str):
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

def load_platforms():
    try:
        resp = requests.get(DATA_URL, timeout=10)
        resp.raise_for_status()
        return json.loads(resp.text)
    except Exception:
        return []

async def latest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    platforms = load_platforms()
    if not platforms:
        await update.message.reply_text("⚠️ لا توجد منصات حالياً.")
        return
    latest_plats = sorted(platforms, key=lambda x: x.get("added_date", ""), reverse=True)[:5]
    for p in latest_plats:
        trust, suspect = get_platform_stats(p["name"])
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"👍 موثوق ({trust})", callback_data=f"vote|{p['name']}|trust"),
                InlineKeyboardButton(f"👎 مشبوه ({suspect})", callback_data=f"vote|{p['name']}|suspect"),
            ]
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

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❓ استخدم: /search <اسم المنصة>")
        return
    keyword = " ".join(context.args).lower()
    platforms = load_platforms()
    results = [p for p in platforms if keyword in p["name"].lower()]
    if not results:
        await update.message.reply_text("🔍 لا توجد نتائج.")
        return
    for p in results[:3]:
        trust, suspect = get_platform_stats(p["name"])
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"👍 ({trust})", callback_data=f"vote|{p['name']}|trust"),
                InlineKeyboardButton(f"👎 ({suspect})", callback_data=f"vote|{p['name']}|suspect"),
            ]
        ])
        await update.message.reply_text(
            f"✅ <b>{p['name']}</b>\n🏷️ {p.get('category','')}\n🔗 {p['link']}",
            parse_mode="HTML", reply_markup=keyboard
        )

async def categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    platforms = load_platforms()
    cats = {}
    for p in platforms:
        cat = p.get("category", "أخرى")
        cats[cat] = cats.get(cat, 0) + 1
    text = "📂 <b>الفئات:</b>\n" + "\n".join([f"• {c}: {n}" for c, n in cats.items()])
    await update.message.reply_text(text, parse_mode="HTML")

async def vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("|")
    if len(data) != 3:
        return
    _, platform_name, vote_type = data
    user_id = query.from_user.id
    result = cast_vote(platform_name, user_id, vote_type)
    stats = result["stats"]
    new_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"👍 موثوق ({stats['trust']})", callback_data=f"vote|{platform_name}|trust"),
            InlineKeyboardButton(f"👎 مشبوه ({stats['suspect']})", callback_data=f"vote|{platform_name}|suspect"),
        ]
    ])
    await query.edit_message_reply_markup(reply_markup=new_keyboard)
    await query.message.reply_text(result["status"])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = (
        "🤖 <b>بوت دليل منصات الربح</b>\n\n"
        "الأوامر:\n"
        "/latest - أحدث 5 منصات\n"
        "/search اسم - بحث عن منصة\n"
        "/categories - عرض الفئات\n"
        "يمكنك تقييم المنصات عبر الأزرار."
    )
    await update.message.reply_text(welcome, parse_mode="HTML")

def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("latest", latest))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("categories", categories))
    app.add_handler(CallbackQueryHandler(vote_callback, pattern="^vote\\|"))
    print("✅ البوت يعمل...")
    app.run_polling()

if __name__ == "__main__":
    main()
