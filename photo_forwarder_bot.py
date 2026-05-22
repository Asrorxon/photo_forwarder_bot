"""
Telegram Photo & Video Forwarder Bot
Rasm va videolarni bitta albom qilib gruppaga yuboradi.
"""

import logging
import asyncio
from collections import defaultdict
from telegram import Update, InputMediaPhoto, InputMediaVideo
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    filters,
    ContextTypes,
)

# ─── SOZLAMALAR ────────────────────────────────────────────────────────────────

BOT_TOKEN = "8642383057:AAHRC0GeMskxA8c8cg3IRYl_t3Qmnhntvf4"       # @BotFather dan olingan token
TARGET_GROUP_ID = "-1003316220353"        # Maqsad gruppa ID (manfiy son)
ALBUM_WAIT_SECONDS = 1.5               # Media to'plash uchun kutish vaqti

# ─── LOGGING ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Albom medialarini vaqtinchalik saqlash
# format: { media_group_id: [ {"type": "photo"|"video", "file_id": "..."} ] }
album_cache: dict = defaultdict(list)
album_tasks: dict = {}
album_users: dict = {}


# ─── HANDLERS ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Salom! Men media forwarder botman.\n\n"
        "📸 Rasm yoki 🎥 video yuboring — men ularni gruppaga yuboraman!"
    )


async def send_album(media_group_id: str, context: ContextTypes.DEFAULT_TYPE, user) -> None:
    """To'plangan rasm/videolarni bitta albom qilib yuboradi."""
    await asyncio.sleep(ALBUM_WAIT_SECONDS)

    items = album_cache.pop(media_group_id, [])
    album_tasks.pop(media_group_id, None)
    album_users.pop(media_group_id, None)

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
        f"📦 Yangi media!\n"
        f"👤 Yuboruvchi: {user.full_name}"
        + (f" (@{user.username})" if user.username else "")
        + f"\n🆔 User ID: {user.id}\n"
        + " | ".join(parts)
    )

    try:
        media = []
        for i, item in enumerate(items):
            cap = caption if i == 0 else None
            if item["type"] == "photo":
                media.append(InputMediaPhoto(media=item["file_id"], caption=cap))
            else:
                media.append(InputMediaVideo(media=item["file_id"], caption=cap))

        await context.bot.send_media_group(chat_id=TARGET_GROUP_ID, media=media)
        logger.info(f"Albom yuborildi: {photo_count} rasm, {video_count} video.")
    except Exception as e:
        logger.error(f"Albom yuborishda xato: {e}")


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Rasm yoki videoni qabul qiladi."""
    message = update.message
    user = message.from_user
    media_group_id = message.media_group_id

    # Fayl turini aniqlash
    if message.photo:
        item = {"type": "photo", "file_id": message.photo[-1].file_id}
        label = "📸 Rasm"
    elif message.video:
        item = {"type": "video", "file_id": message.video.file_id}
        label = "🎥 Video"
    else:
        return

    if media_group_id:
        # Albom — bir nechta media birgalikda
        album_cache[media_group_id].append(item)
        album_users[media_group_id] = user

        if media_group_id in album_tasks:
            album_tasks[media_group_id].cancel()

        task = asyncio.create_task(send_album(media_group_id, context, user))
        album_tasks[media_group_id] = task

        if len(album_cache[media_group_id]) == 1:
            await message.reply_text("✅ Media qabul qilindi, yuborilmoqda...")
    else:
        # Bitta rasm yoki video
        caption = (
            f"{label}!\n"
            f"👤 Yuboruvchi: {user.full_name}"
            + (f" (@{user.username})" if user.username else "")
            + f"\n🆔 User ID: {user.id}"
        )
        try:
            if item["type"] == "photo":
                await context.bot.send_photo(
                    chat_id=TARGET_GROUP_ID,
                    photo=item["file_id"],
                    caption=caption,
                )
            else:
                await context.bot.send_video(
                    chat_id=TARGET_GROUP_ID,
                    video=item["file_id"],
                    caption=caption,
                )
            await message.reply_text("✅ Muvaffaqiyatli yuborildi!")
            logger.info(f"{label} yuborildi.")
        except Exception as e:
            logger.error(f"Xato: {e}")
            await message.reply_text("❌ Xato yuz berdi. Administrator bilan bog'laning.")


async def not_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📸🎥 Iltimos, faqat rasm yoki video yuboring."
    )


# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, handle_media))
    app.add_handler(
        MessageHandler(
            filters.TEXT | filters.Document.ALL | filters.AUDIO,
            not_media,
        )
    )

    logger.info("✅ Bot ishga tushdi. To'xtatish uchun Ctrl+C bosing.")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
