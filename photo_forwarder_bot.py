"""
Telegram Photo & Video Forwarder Bot
- Toy egasi to'lov qilib unikal link oladi
- Mehmonlar link orqali rasm/video yuboradi
- Bot toy egasining gruppasiga yuboradi
"""

import logging
import asyncio
import os
import json
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
DB_FILE = "users.json"
ALBUM_WAIT_SECONDS = 1.5

PLANS = {
    "plan_1": {"name": "1 oylik",  "stars": 1,  "days": 30,  "emoji": "🥉"},
    "plan_2": {"name": "2 oylik",  "stars": 1000,  "days": 60,  "emoji": "🥈"},
    "plan_3": {"name": "3 oylik",  "stars": 1500, "days": 90,  "emoji": "🥇"},
}

# ─── LOGGING ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── DATABASE ──────────────────────────────────────────────────────────────────

def load_db() -> dict:
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return json.load(f)
    return {"users": {}, "links": {}}

def save_db(db: dict):
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=2)

def get_user(user_id: int) -> dict | None:
    return load_db()["users"].get(str(user_id))

def save_user(user_id: int, data: dict):
    db = load_db()
    db["users"][str(user_id)] = data
    save_db(db)

def get_link_owner(link_code: str) -> dict | None:
    """Link orqali toy egasini topish."""
    db = load_db()
    user_id = db["links"].get(link_code)
    if not user_id:
        return None
    user = db["users"].get(str(user_id))
    if not user:
        return None
    # Link muddati tekshirish
    expires = datetime.fromisoformat(user["expires"])
    if datetime.now() > expires:
        return None
    return user

def generate_link(user_id: int) -> str:
    """Foydalanuvchi uchun unikal link kodi yaratish."""
    db = load_db()
    # Avvalgi linkni o'chirish
    old_links = [k for k, v in db["links"].items() if v == str(user_id)]
    for old in old_links:
        del db["links"][old]
    # Yangi link
    code = secrets.token_urlsafe(8)
    db["links"][code] = str(user_id)
    save_db(db)
    return code

def is_subscribed(user_id: int) -> bool:
    user = get_user(user_id)
    if not user:
        return False
    return datetime.now() < datetime.fromisoformat(user["expires"])

def get_group_id(user_id: int) -> int | None:
    user = get_user(user_id)
    return user.get("group_id") if user else None

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
    args = context.args  # /start link_code

    # Admin uchun bepul
    if user.id == ADMIN_ID:
        db = load_db()
        if str(user.id) not in db.get("users", {}):
            expires = datetime.now() + timedelta(days=36500)  # 100 yil
            code = generate_link(user.id)
            save_user(user.id, {
                "name": user.full_name,
                "username": user.username,
                "expires": expires.isoformat(),
                "group_id": None,
                "plan": "Admin",
                "link_code": code,
            })
            db = load_db()
            db["links"][code] = str(user.id)
            save_db(db)

    # ── Mehmon: link orqali kirdi ──
    if args:
        link_code = args[0]
        owner = get_link_owner(link_code)

        if not owner:
            await update.message.reply_text(
                "❌ Bu link muddati tugagan yoki noto'g'ri.\n"
                "Toy egasidan yangi link so'rang."
            )
            return

        # Mehmon ma'lumotini saqlaymiz (link_code orqali)
        context.user_data["guest_link"] = link_code
        context.user_data["guest_group"] = owner["group_id"]

        await update.message.reply_text(
            f"👋 Xush kelibsiz!\n\n"
            f"📸 Rasm yoki 🎥 video yuboring — "
            f"bot avtomatik gruppaga yuboradi!\n\n"
            f"⚠️ Faqat rasm va video qabul qilinadi."
        )
        return

    # ── Toy egasi: oddiy /start ──
    user_data = get_user(user.id)

    if user_data and is_subscribed(user.id):
        expires = datetime.fromisoformat(user_data["expires"])
        group_id = user_data.get("group_id")
        link_code = user_data.get("link_code")
        bot_username = (await context.bot.get_me()).username

        group_text = f"✅ Gruppa: `{group_id}`" if group_id else "⚠️ Gruppa ulanmagan — /setgroup"
        link_text = (
            f"🔗 Sizning linkingiz:\n`t.me/{bot_username}?start={link_code}`"
            if link_code else "⚠️ Link yo'q — /mylink"
        )

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 Obunani uzaytirish", callback_data="extend")
        ]])

        await update.message.reply_text(
            f"👋 Salom, {user.first_name}!\n\n"
            f"📅 Obuna: *{expires.strftime('%d.%m.%Y')}* gacha\n"
            f"{group_text}\n\n"
            f"{link_text}\n\n"
            f"Bu linkni mehmonlaringizga yuboring!",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"👋 Salom, {user.first_name}!\n\n"
            f"🤖 Bu bot rasmlarni avtomatik gruppangizga yuboradi.\n"
            f"Mehmonlaringizga link ulashаsiz — ular rasm yuborganda "
            f"to'g'ridan-to'g'ri gruppangizga tushadi!\n\n"
            f"💎 *Tariflar:*\n"
            f"🥉 1 oy — 750 Stars\n"
            f"🥈 2 oy — 1000 Stars\n"
            f"🥇 3 oy — 1500 Stars\n\n"
            f"Tarif tanlang 👇",
            reply_markup=plans_keyboard(),
            parse_mode="Markdown"
        )


async def mylink(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toy egasi o'z linkini ko'radi."""
    user = update.effective_user

    if not is_subscribed(user.id):
        await update.message.reply_text("❌ Obunangiz yo'q. /start buyrug'ini yuboring.")
        return

    user_data = get_user(user.id)
    if not user_data.get("group_id"):
        await update.message.reply_text("⚠️ Avval gruppangizni ulang: /setgroup")
        return

    link_code = user_data.get("link_code")
    if not link_code:
        await update.message.reply_text("⚠️ Link topilmadi. /newlink buyrug'i bilan yangi link oling.")
        return

    bot_username = (await context.bot.get_me()).username
    expires = datetime.fromisoformat(user_data["expires"])

    await update.message.reply_text(
        f"🔗 *Sizning linkingiz:*\n"
        f"`t.me/{bot_username}?start={link_code}`\n\n"
        f"📅 Muddat: *{expires.strftime('%d.%m.%Y')}* gacha\n\n"
        f"Bu linkni mehmonlaringizga yuboring!",
        parse_mode="Markdown"
    )


async def newlink(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Yangi link olish (eski link o'chadi)."""
    user = update.effective_user

    if not is_subscribed(user.id):
        await update.message.reply_text("❌ Obunangiz yo'q. /start buyrug'ini yuboring.")
        return

    user_data = get_user(user.id)
    if not user_data.get("group_id"):
        await update.message.reply_text("⚠️ Avval gruppangizni ulang: /setgroup")
        return

    link_code = generate_link(user.id)
    user_data["link_code"] = link_code
    save_user(user.id, user_data)

    bot_username = (await context.bot.get_me()).username

    await update.message.reply_text(
        f"✅ Yangi link yaratildi!\n\n"
        f"🔗 *Linkingiz:*\n"
        f"`t.me/{bot_username}?start={link_code}`\n\n"
        f"⚠️ Eski link endi ishlamaydi!",
        parse_mode="Markdown"
    )


async def buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "extend":
        await query.message.reply_text(
            "🔄 Obunani uzaytirish uchun tarif tanlang 👇",
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
        description=f"{plan['name']} davomida rasmlaringizni gruppangizga avtomatik yuboradi.",
        payload=plan_key,
        currency="XTR",
        prices=[LabeledPrice(plan["name"], plan["stars"])],
    )


async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.pre_checkout_query
    if query.invoice_payload in PLANS:
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Xato yuz berdi.")


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    plan_key = update.message.successful_payment.invoice_payload
    plan = PLANS[plan_key]

    existing = get_user(user.id)

    # Obuna uzaytirilsa — ustiga qo'shiladi
    if existing and is_subscribed(user.id):
        current_expires = datetime.fromisoformat(existing["expires"])
        expires = current_expires + timedelta(days=plan["days"])
    else:
        expires = datetime.now() + timedelta(days=plan["days"])

    group_id = existing.get("group_id") if existing else None
    old_link = existing.get("link_code") if existing else None

    # Yangi link faqat birinchi marta yaratiladi
    link_code = old_link if old_link else generate_link(user.id)

    save_user(user.id, {
        "name": user.full_name,
        "username": user.username,
        "expires": expires.isoformat(),
        "group_id": group_id,
        "plan": plan["name"],
        "link_code": link_code,
    })

    # links jadvalini yangilash
    db = load_db()
    db["links"][link_code] = str(user.id)
    save_db(db)

    logger.info(f"To'lov: {user.full_name}, {plan['name']}, {plan['stars']} Stars")

    bot_username = (await context.bot.get_me()).username

    msg = (
        f"✅ To'lov qabul qilindi! Rahmat!\n\n"
        f"{plan['emoji']} *{plan['name']}* obuna faollashtirildi\n"
        f"📅 Muddat: *{expires.strftime('%d.%m.%Y')}* gacha\n\n"
    )

    if group_id:
        msg += (
            f"🔗 *Sizning linkingiz:*\n"
            f"`t.me/{bot_username}?start={link_code}`\n\n"
            f"Bu linkni mehmonlaringizga yuboring!"
        )
    else:
        msg += "Endi /setgroup buyrug'i bilan gruppangizni ulang."

    await update.message.reply_text(msg, parse_mode="Markdown")


async def setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user

    if not is_subscribed(user.id):
        await update.message.reply_text("❌ Obunangiz yo'q. /start buyrug'ini yuboring.")
        return

    await update.message.reply_text(
        "📋 *Gruppani ulash qadamlari:*\n\n"
        "1️⃣ Botni gruppaga qo'shing\n"
        "2️⃣ Botni gruppada *admin* qiling\n"
        "3️⃣ Gruppa ID ni yuboring\n\n"
        "📌 Gruppa ID olish: @userinfobot ga /start yozing\n\n"
        "Gruppa ID ni shu yerga yuboring (masalan: `-1001234567890`)",
        parse_mode="Markdown"
    )
    context.user_data["waiting_group"] = True


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    text = update.message.text.strip()

    # Mehmon — link orqali kirgan
    if context.user_data.get("guest_link"):
        await update.message.reply_text("📸 Iltimos, faqat rasm yoki 🎥 video yuboring.")
        return

    # Gruppa ID kutilmoqda
    if context.user_data.get("waiting_group"):
        try:
            group_id = int(text)
            existing = get_user(user.id)
            if existing:
                existing["group_id"] = group_id
                # Agar link yo'q bo'lsa — yaratamiz
                if not existing.get("link_code"):
                    link_code = generate_link(user.id)
                    existing["link_code"] = link_code
                    db = load_db()
                    db["links"][link_code] = str(user.id)
                    save_db(db)

                save_user(user.id, existing)
                context.user_data["waiting_group"] = False

                bot_username = (await context.bot.get_me()).username
                link_code = existing["link_code"]

                await update.message.reply_text(
                    f"✅ Gruppa muvaffaqiyatli ulandi!\n\n"
                    f"🔗 *Sizning linkingiz:*\n"
                    f"`t.me/{bot_username}?start={link_code}`\n\n"
                    f"Bu linkni mehmonlaringizga yuboring! 🚀",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text("❌ Avval obuna qiling. /start")
        except ValueError:
            await update.message.reply_text(
                "❌ Noto'g'ri format!\n"
                "Manfiy son kiriting, masalan: `-1001234567890`",
                parse_mode="Markdown"
            )
        return

    # Oddiy matn
    if not is_subscribed(user.id):
        await update.message.reply_text(
            "❌ Obunangiz yo'q.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⭐ Obuna qilish", callback_data="buy_plan_1")
            ]])
        )
    else:
        await update.message.reply_text("📸 Rasm yoki 🎥 video yuboring.")


async def send_album(media_group_id: str, context: ContextTypes.DEFAULT_TYPE, user, group_id: int) -> None:
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

    # ── Mehmon ──
    guest_group = context.user_data.get("guest_group")
    guest_link = context.user_data.get("guest_link")

    if guest_link:
        # Linkni qayta tekshirish (muddati tugaganmi)
        owner = get_link_owner(guest_link)
        if not owner:
            await message.reply_text(
                "❌ Linkingiz muddati tugagan.\n"
                "Toy egasidan yangi link so'rang."
            )
            context.user_data.clear()
            return
        group_id = owner["group_id"]
    elif is_subscribed(user.id):
        # Toy egasi o'zi rasm yubormoqda
        group_id = get_group_id(user.id)
        if not group_id:
            await message.reply_text("⚠️ Gruppa ulanmagan. /setgroup buyrug'ini yuboring.")
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
            await message.reply_text("✅ Media qabul qilindi, yuborilmoqda...")
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
            await message.reply_text("❌ Xato yuz berdi. Gruppa ID to'g'riligini tekshiring.")


async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        return

    db = load_db()
    users = db.get("users", {})

    if not users:
        await update.message.reply_text("Hech kim obuna qilmagan.")
        return

    active = sum(1 for u in users.values() if datetime.now() < datetime.fromisoformat(u["expires"]))
    text = f"👥 Jami: {len(users)} | ✅ Faol: {active}\n\n"

    for uid, data in users.items():
        expires = datetime.fromisoformat(data["expires"])
        status = "✅" if datetime.now() < expires else "❌"
        text += (
            f"{status} {data['name']}"
            + (f" (@{data['username']})" if data.get('username') else "")
            + f"\n📅 {expires.strftime('%d.%m.%Y')} | {data.get('plan', '-')}\n"
            + f"🔗 Gruppa: {data.get('group_id', 'ulanmagan')}\n\n"
        )
    await update.message.reply_text(text)


# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main() -> None:
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
