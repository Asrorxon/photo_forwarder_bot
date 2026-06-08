"""
Telegram Photo & Video Forwarder Bot
- SQLite baza
- Telegram Stars to'lov
- Unikal link tizimi
"""

import logging
import asyncio
import os
import sqlite3
import secrets
from datetime import datetime, timedelta
from collections import defaultdict
from telegram import (
    Update, InputMediaPhoto, InputMediaVideo,
    LabeledPrice, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, MessageHandler, CommandHandler,
    filters, ContextTypes, PreCheckoutQueryHandler,
    CallbackQueryHandler,
)

# ─── SOZLAMALAR ────────────────────────────────────────────────────────────────

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8468983026:AAHxFW8tBhVMPkNaiWWeYri2NIJ_fz1cLt8")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "7156082393"))
DB_FILE = os.environ.get("DB_FILE", "bot.db")
ALBUM_WAIT_SECONDS = 1.5

PLANS = {
    "plan_1": {"name": "1 oylik",  "stars": 1,  "days": 30,  "emoji": "🥉"},
    "plan_2": {"name": "2 oylik",  "stars": 750,  "days": 60,  "emoji": "🥈"},
    "plan_3": {"name": "3 oylik",  "stars": 1000, "days": 90,  "emoji": "🥇"},
}

# ─── LOGGING ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── DATABASE ──────────────────────────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True) if "/" in DB_FILE else None
    
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                name        TEXT,
                username    TEXT,
                expires     TEXT,
                group_id    INTEGER,
                plan        TEXT,
                link_code   TEXT UNIQUE
            )
        """)
        conn.commit()

def get_user(user_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

def save_user(user_id: int, name: str, username: str, expires: str,
              group_id, plan: str, link_code: str):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO users (user_id, name, username, expires, group_id, plan, link_code)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                name=excluded.name, username=excluded.username,
                expires=excluded.expires, group_id=excluded.group_id,
                plan=excluded.plan, link_code=excluded.link_code
        """, (user_id, name, username, expires, group_id, plan, link_code))
        conn.commit()

def update_group(user_id: int, group_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE users SET group_id = ? WHERE user_id = ?", (group_id, user_id))
        conn.commit()

def get_user_by_link(link_code: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE link_code = ?", (link_code,)).fetchone()
        if not row:
            return None
        data = dict(row)
        if datetime.now() > datetime.fromisoformat(data["expires"]):
            return None
        return data

def is_subscribed(user_id: int) -> bool:
    user = get_user(user_id)
    if not user:
        return False
    return datetime.now() < datetime.fromisoformat(user["expires"])

def generate_link(user_id: int) -> str:
    code = secrets.token_urlsafe(8)
    with get_conn() as conn:
        conn.execute("UPDATE users SET link_code = ? WHERE user_id = ?", (code, user_id))
        conn.commit()
    return code

def get_all_users():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY expires DESC").fetchall()
        return [dict(r) for r in rows]

# ─── ALBUM CACHE ───────────────────────────────────────────────────────────────

album_cache: dict = defaultdict(list)
album_tasks: dict = {}

# ─── KLAVIATURA ────────────────────────────────────────────────────────────────

def plans_keyboard():
    buttons = []
    for key, plan in PLANS.items():
        buttons.append([InlineKeyboardButton(
            f"{plan['emoji']} {plan['name']} — {plan['stars']} Stars",
            callback_data=f"buy_{key}"
        )])
    return InlineKeyboardMarkup(buttons)

# ─── HANDLERS ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    args = context.args

    # Admin uchun bepul obuna
    if user.id == ADMIN_ID and not get_user(user.id):
        expires = datetime.now() + timedelta(days=36500)
        code = secrets.token_urlsafe(8)
        save_user(user.id, user.full_name, user.username,
                  expires.isoformat(), None, "Admin", None)
        logger.info(f"Admin obunasi yaratildi: {user.full_name}")

    # Mehmon: link orqali kirdi
    if args:
        link_code = args[0]
        owner = get_user_by_link(link_code)
        if not owner:
            await update.message.reply_text(
                "❌ Bu link muddati tugagan yoki noto'g'ri.\n"
                "Toy egasidan yangi link so'rang."
            )
            return
        context.user_data["guest_link"] = link_code
        context.user_data["guest_group"] = owner["group_id"]
        await update.message.reply_text(
            "👋 Xush kelibsiz!\n\n"
            "📸 Rasm yoki 🎥 video yuboring — "
            "bot avtomatik gruppaga yuboradi!"
        )
        return

    # Toy egasi
    user_data = get_user(user.id)
    if user_data and is_subscribed(user.id):
        expires = datetime.fromisoformat(user_data["expires"])
        group_id = user_data.get("group_id")
        link_code = user_data.get("link_code")
        bot_username = (await context.bot.get_me()).username

        group_text = f"✅ Gruppa: `{group_id}`" if group_id else "⚠️ Gruppa ulanmagan — /setgroup"
        link_text = (
            f"🔗 Linkingiz:\n`t.me/{bot_username}?start={link_code}`"
            if link_code else "⚠️ /mylink buyrug'ini yuboring"
        )
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 Obunani uzaytirish", callback_data="extend")
        ]])
        await update.message.reply_text(
            f"👋 Salom, {user.first_name}!\n\n"
            f"📅 Obuna: *{expires.strftime('%d.%m.%Y')}* gacha\n"
            f"{group_text}\n\n"
            f"{link_text}\n\n"
            f"Linkni mehmonlaringizga yuboring!",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"👋 Salom, {user.first_name}!\n\n"
            f"🤖 Bu bot rasmlarni avtomatik gruppangizga yuboradi.\n"
            f"Mehmonlarga link ulashасиз — ular rasm yuborganda "
            f"gruppangizga tushadi!\n\n"
            f"💎 *Tariflar:*\n"
            f"🥉 1 oy — 500 Stars\n"
            f"🥈 2 oy — 750 Stars\n"
            f"🥇 3 oy — 1000 Stars\n\n"
            f"Tarif tanlang 👇",
            reply_markup=plans_keyboard(),
            parse_mode="Markdown"
        )


async def mylink(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_subscribed(user.id):
        await update.message.reply_text("❌ Obunangiz yo'q. /start")
        return
    user_data = get_user(user.id)
    if not user_data.get("group_id"):
        await update.message.reply_text("⚠️ Avval gruppangizni ulang: /setgroup")
        return
    link_code = user_data.get("link_code")
    if not link_code:
        await update.message.reply_text("⚠️ /newlink buyrug'i bilan yangi link oling.")
        return
    bot_username = (await context.bot.get_me()).username
    expires = datetime.fromisoformat(user_data["expires"])
    await update.message.reply_text(
        f"🔗 *Sizning linkingiz:*\n"
        f"`t.me/{bot_username}?start={link_code}`\n\n"
        f"📅 Muddat: *{expires.strftime('%d.%m.%Y')}* gacha",
        parse_mode="Markdown"
    )


async def newlink(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_subscribed(user.id):
        await update.message.reply_text("❌ Obunangiz yo'q. /start")
        return
    user_data = get_user(user.id)
    if not user_data.get("group_id"):
        await update.message.reply_text("⚠️ Avval gruppangizni ulang: /setgroup")
        return
    code = generate_link(user.id)
    bot_username = (await context.bot.get_me()).username
    await update.message.reply_text(
        f"✅ Yangi link yaratildi!\n\n"
        f"🔗 *Linkingiz:*\n"
        f"`t.me/{bot_username}?start={code}`\n\n"
        f"⚠️ Eski link endi ishlamaydi!",
        parse_mode="Markdown"
    )


async def buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "extend":
        await query.message.reply_text(
            "🔄 Tarif tanlang 👇",
            reply_markup=plans_keyboard()
        )
        return
    plan_key = data.replace("buy_", "")
    plan = PLANS.get(plan_key)
    if not plan:
        return
    await context.bot.send_invoice(
        chat_id=query.from_user.id,
        title=f"📸 Photo Forwarder — {plan['name']}",
        description=f"{plan['name']} davomida rasmlarni gruppangizga yuboradi.",
        payload=plan_key,
        currency="XTR",
        prices=[LabeledPrice(plan["name"], plan["stars"])],
    )


async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.pre_checkout_query
    await query.answer(ok=query.invoice_payload in PLANS)


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    plan_key = update.message.successful_payment.invoice_payload
    plan = PLANS[plan_key]

    existing = get_user(user.id)
    if existing and is_subscribed(user.id):
        expires = datetime.fromisoformat(existing["expires"]) + timedelta(days=plan["days"])
    else:
        expires = datetime.now() + timedelta(days=plan["days"])

    group_id = existing.get("group_id") if existing else None
    link_code = existing.get("link_code") if existing else None

    save_user(user.id, user.full_name, user.username,
              expires.isoformat(), group_id, plan["name"], link_code)

    logger.info(f"To'lov: {user.full_name}, {plan['name']}, {plan['stars']} Stars")

    bot_username = (await context.bot.get_me()).username
    msg = (
        f"✅ To'lov qabul qilindi!\n\n"
        f"{plan['emoji']} *{plan['name']}* faollashtirildi\n"
        f"📅 Muddat: *{expires.strftime('%d.%m.%Y')}* gacha\n\n"
    )
    if group_id:
        msg += (
            f"🔗 *Linkingiz:*\n"
            f"`t.me/{bot_username}?start={link_code}`\n\n"
            f"Mehmonlaringizga yuboring!"
        )
    else:
        msg += "Endi /setgroup bilan gruppangizni ulang."
    await update.message.reply_text(msg, parse_mode="Markdown")


async def setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_subscribed(user.id):
        await update.message.reply_text("❌ Obunangiz yo'q. /start")
        return
    await update.message.reply_text(
        "📋 *Gruppani ulash:*\n\n"
        "1️⃣ Botni gruppaga qo'shing\n"
        "2️⃣ Botni *admin* qiling\n"
        "3️⃣ Gruppa ID ni yuboring\n\n"
        "📌 ID olish: @userinfobot ga /start yozing\n\n"
        "Gruppa ID ni yuboring (masalan: `-1001234567890`)",
        parse_mode="Markdown"
    )
    context.user_data["waiting_group"] = True

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    text = update.message.text.strip()

    if context.user_data.get("guest_link"):
        await update.message.reply_text(
            "📸 Faqat rasm yoki 🎥 video yuboring."
        )
        return

    if context.user_data.get("waiting_group"):
        try:
            group_id = int(text)

            # ID formatini tekshirish
            if not str(group_id).startswith("-100"):
                await update.message.reply_text(
                    "❌ Noto'g'ri guruh ID!\n\n"
                    "Masalan: -1001234567890"
                )
                return

            existing = get_user(user.id)

            if not existing:
                await update.message.reply_text(
                    "❌ Avval obuna qiling. /start"
                )
                return

            # Guruh mavjudligini tekshirish
            await context.bot.get_chat(group_id)

            me = await context.bot.get_me()

            member = await context.bot.get_chat_member(
                group_id,
                me.id
            )

            if member.status not in ["administrator", "creator"]:
                await update.message.reply_text(
                    "❌ Bot guruhda admin emas."
                )
                return

            # Hammasi joyida bo'lsa saqlaymiz
            update_group(user.id, group_id)
            context.user_data["waiting_group"] = False

            link_code = existing.get("link_code")

            if not link_code:
                link_code = generate_link(user.id)

            bot_username = me.username

            await update.message.reply_text(
                f"✅ Gruppa ulandi! ID: `{group_id}`\n\n"
                f"🔗 *Linkingiz:*\n"
                f"`t.me/{bot_username}?start={link_code}`\n\n"
                f"Mehmonlaringizga yuboring! 🚀",
                parse_mode="Markdown"
            )

        except ValueError:
            await update.message.reply_text(
                "❌ Noto'g'ri format!\n\n"
                "Masalan: `-1001234567890`",
                parse_mode="Markdown"
            )

        except Exception as e:
            print(f"GROUP ERROR: {e}")

            await update.message.reply_text(
                "❌ Bot bu guruhni topa olmadi yoki guruhga qo'shilmagan."
            )

        return

    if not is_subscribed(user.id):
        await update.message.reply_text(
            "❌ Obunangiz yo'q.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "⭐ Obuna qilish",
                    callback_data="buy_plan_1"
                )
            ]])
        )
    else:
        await update.message.reply_text(
            "📸 Rasm yoki 🎥 video yuboring."
        )

async def send_album(media_group_id: str, context: ContextTypes.DEFAULT_TYPE,
                     user, group_id: int) -> None:
    await asyncio.sleep(ALBUM_WAIT_SECONDS)
    items = album_cache.pop(media_group_id, [])
    album_tasks.pop(media_group_id, None)
    if not items:
        return

    photo_count = sum(1 for i in items if i["type"] == "photo")
    video_count = sum(1 for i in items if i["type"] == "video")
    parts = []
    if photo_count:
        parts.append(f"🖼 {photo_count} ta rasm")
    if video_count:
        parts.append(f"🎥 {video_count} ta video")

    caption = (
        f"📦 Yangi media!\n👤 {user.full_name}"
        + (f" (@{user.username})" if user.username else "")
        + "\n" + " | ".join(parts)
    )
    try:
        media = []
        for i, item in enumerate(items):
            cap = caption if i == 0 else None
            if item["type"] == "photo":
                media.append(InputMediaPhoto(media=item["file_id"], caption=cap))
            else:
                media.append(InputMediaVideo(media=item["file_id"], caption=cap))
        await context.bot.send_media_group(chat_id=group_id, media=media)
        logger.info(f"Albom: {user.full_name} → group {group_id}")
    except Exception as e:
        logger.error(f"Albom xato: {e}")


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.message

    guest_link = context.user_data.get("guest_link")
    if guest_link:
        owner = get_user_by_link(guest_link)
        if not owner:
            await message.reply_text("❌ Linkingiz muddati tugagan. Toy egasidan yangi link so'rang.")
            context.user_data.clear()
            return
        group_id = owner["group_id"]
    elif is_subscribed(user.id):
        group_id = get_user(user.id).get("group_id")
        if not group_id:
            await message.reply_text("⚠️ Gruppa ulanmagan. /setgroup")
            return
    else:
        await message.reply_text(
            "❌ Obunangiz yo'q.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⭐ Obuna qilish", callback_data="buy_plan_1")
            ]])
        )
        return

    media_group_id = message.media_group_id
    if message.photo:
        item = {"type": "photo", "file_id": message.photo[-1].file_id}
        label = "📸 Rasm"
    elif message.video:
        item = {"type": "video", "file_id": message.video.file_id}
        label = "🎥 Video"
    else:
        return

    if media_group_id:
        album_cache[media_group_id].append(item)
        if media_group_id in album_tasks:
            album_tasks[media_group_id].cancel()
        task = asyncio.create_task(send_album(media_group_id, context, user, group_id))
        album_tasks[media_group_id] = task
        if len(album_cache[media_group_id]) == 1:
            await message.reply_text("✅ Media qabul qilindi!")
    else:
        caption = (
            f"{label}!\n👤 {user.full_name}"
            + (f" (@{user.username})" if user.username else "")
        )
        try:
            if item["type"] == "photo":
                await context.bot.send_photo(chat_id=group_id, photo=item["file_id"], caption=caption)
            else:
                await context.bot.send_video(chat_id=group_id, video=item["file_id"], caption=caption)
            await message.reply_text("✅ Yuborildi!")
        except Exception as e:
            logger.error(f"Xato: {e}")
            await message.reply_text("❌ Xato yuz berdi. Gruppa ID ni tekshiring.")


async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        return
    users = get_all_users()
    if not users:
        await update.message.reply_text("Hech kim obuna qilmagan.")
        return
    active = sum(1 for u in users if datetime.now() < datetime.fromisoformat(u["expires"]))
    text = f"👥 Jami: {len(users)} | ✅ Faol: {active}\n\n"
    for data in users:
        expires = datetime.fromisoformat(data["expires"])
        status = "✅" if datetime.now() < expires else "❌"
        text += (
            f"{status} {data['name']}"
            + (f" (@{data['username']})" if data.get('username') else "")
            + f"\n📅 {expires.strftime('%d.%m.%Y')} | {data.get('plan', '-')}\n"
            + f"🔗 {data.get('group_id', 'ulanmagan')}\n\n"
        )
    await update.message.reply_text(text)


# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main() -> None:
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setgroup", setgroup))
    app.add_handler(CommandHandler("mylink", mylink))
    app.add_handler(CommandHandler("newlink", newlink))
    app.add_handler(CommandHandler("users", admin_users))
    app.add_handler(CallbackQueryHandler(buy_callback, pattern="^(buy_|extend)"))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, handle_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("✅ Bot ishga tushdi.")
    app.run_polling(allowed_updates=["message", "callback_query", "pre_checkout_query"])


if __name__ == "__main__":
    main()