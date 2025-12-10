import asyncio
import logging
import hashlib
import secrets

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, ContentType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import (
    BOT_TOKEN, ADMIN_ID, CHANNEL_ID, MODERATION_ENABLED,
    RATE_LIMIT_MESSAGES, RATE_LIMIT_WINDOW_MINUTES, SPAM_THRESHOLD
)
from keyboards import (
    get_main_keyboard, get_back_keyboard, get_reply_keyboard,
    get_moderation_keyboard, get_history_keyboard, get_cancel_keyboard,
    get_answer_sender_keyboard, get_user_reply_keyboard,
    get_admin_panel_keyboard, get_discussion_keyboard, get_block_user_keyboard,
    get_analytics_keyboard
)
import database as db
from analytics import (
    analyze_sentiment, generate_heatmap, generate_weekly_heatmap,
    generate_sentiment_chart, generate_activity_trend
)
from aiogram.types import BufferedInputFile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = Router()

MEDIA_TYPES = {
    ContentType.PHOTO: "photo",
    ContentType.VIDEO: "video",
    ContentType.VOICE: "voice",
    ContentType.VIDEO_NOTE: "video_note",
    ContentType.AUDIO: "audio",
    ContentType.DOCUMENT: "document",
    ContentType.STICKER: "sticker",
    ContentType.ANIMATION: "animation",
}


class SendMessage(StatesGroup):
    waiting_for_message = State()
    waiting_for_reply = State()


def generate_reply_hash(sender_id: int, receiver_id: int) -> str:
    data = f"{sender_id}:{receiver_id}:{secrets.token_hex(4)}"
    return hashlib.md5(data.encode()).hexdigest()[:8]


async def send_alert_to_admin(bot: Bot, message: str):
    try:
        await bot.send_message(ADMIN_ID, message, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Failed to send alert: {e}")


async def send_to_moderation(bot: Bot, message_id: int, sender_id: int, content: str = None, 
                             media_type: str = None, media_file_id: str = None, caption: str = None,
                             is_reply: bool = False, reply_to_id: int = None):
    # Analyze sentiment for display
    text_content = content or caption or ""
    sentiment = analyze_sentiment(text_content)
    
    sentiment_emoji = {"positive": "😊", "neutral": "😐", "negative": "😢"}.get(sentiment['sentiment'], "")
    urgent_mark = "🔥 <b>СРОЧНОЕ!</b>\n" if sentiment['urgent'] else ""
    
    prefix = "↩️ <b>Ответ на модерацию</b>" if is_reply else "📨 <b>Новое сообщение на модерацию</b>"
    text = f"{urgent_mark}{prefix}\n\n"
    
    if content:
        text += f"{content}\n\n"
    elif caption:
        text += f"{caption}\n\n"
    
    # User stats
    user_msgs_today = await db.get_user_message_count_today(sender_id)
    text += f"🆔 ID: <code>{message_id}</code> | От: <code>{sender_id}</code>\n"
    text += f"📊 Сегодня: {user_msgs_today} | {sentiment_emoji} {sentiment['sentiment']}"
    if reply_to_id:
        text += f" | Ответ на: <code>{reply_to_id}</code>"
    
    if media_type and media_file_id:
        send_func = {
            "photo": bot.send_photo,
            "video": bot.send_video,
            "voice": bot.send_voice,
            "video_note": bot.send_video_note,
            "audio": bot.send_audio,
            "document": bot.send_document,
            "sticker": bot.send_sticker,
            "animation": bot.send_animation,
        }.get(media_type)
        
        if send_func:
            if media_type in ("sticker", "video_note"):
                await send_func(ADMIN_ID, media_file_id)
                await bot.send_message(ADMIN_ID, text, parse_mode="HTML", 
                                       reply_markup=get_moderation_keyboard(message_id, sender_id))
            else:
                await send_func(ADMIN_ID, media_file_id, caption=text, parse_mode="HTML",
                               reply_markup=get_moderation_keyboard(message_id, sender_id))
    else:
        await bot.send_message(ADMIN_ID, text, parse_mode="HTML",
                              reply_markup=get_moderation_keyboard(message_id, sender_id))


async def publish_to_channel(bot: Bot, message_id: int, content: str = None, 
                             media_type: str = None, media_file_id: str = None, 
                             caption: str = None, is_reply: bool = False,
                             reply_to_channel_msg_id: int = None,
                             is_moderator: bool = False) -> int:
    if not CHANNEL_ID:
        return None
    
    if is_moderator:
        prefix = "👑 <b>Ответ модератора:</b>"
    elif is_reply:
        prefix = "↩️ <b>Ответ:</b>"
    else:
        prefix = "📨 <b>Анонимное сообщение:</b>"
    text = f"{prefix}\n\n"
    
    if content:
        text += content
    elif caption:
        text += caption
    
    reply_params = {"reply_to_message_id": reply_to_channel_msg_id} if reply_to_channel_msg_id else {}
    
    sent_msg = None
    if media_type and media_file_id:
        send_func = {
            "photo": bot.send_photo,
            "video": bot.send_video,
            "voice": bot.send_voice,
            "video_note": bot.send_video_note,
            "audio": bot.send_audio,
            "document": bot.send_document,
            "sticker": bot.send_sticker,
            "animation": bot.send_animation,
        }.get(media_type)
        
        if send_func:
            if media_type in ("sticker", "video_note"):
                sent_msg = await send_func(CHANNEL_ID, media_file_id, **reply_params)
                await bot.send_message(CHANNEL_ID, text, parse_mode="HTML",
                                       reply_to_message_id=sent_msg.message_id)
            else:
                sent_msg = await send_func(CHANNEL_ID, media_file_id, caption=text, 
                                          parse_mode="HTML", **reply_params)
    else:
        sent_msg = await bot.send_message(CHANNEL_ID, text, parse_mode="HTML", **reply_params)
    
    return sent_msg.message_id if sent_msg else None


async def deliver_message(bot: Bot, message_id: int, receiver_id: int, sender_id: int,
                          content: str = None, media_type: str = None, 
                          media_file_id: str = None, caption: str = None, is_reply: bool = False):
    reply_hash = generate_reply_hash(sender_id, receiver_id)
    await db.save_pending_reply(reply_hash, sender_id, receiver_id)
    
    prefix = "↩️ <b>Анонимный ответ:</b>" if is_reply else "📨 <b>Анонимное сообщение:</b>"
    text = f"{prefix}\n\n"
    
    if content:
        text += content
    elif caption:
        text += caption
    
    keyboard = get_reply_keyboard(message_id)
    
    if media_type and media_file_id:
        send_func = {
            "photo": bot.send_photo,
            "video": bot.send_video,
            "voice": bot.send_voice,
            "video_note": bot.send_video_note,
            "audio": bot.send_audio,
            "document": bot.send_document,
            "sticker": bot.send_sticker,
            "animation": bot.send_animation,
        }.get(media_type)
        
        if send_func:
            if media_type in ("sticker", "video_note"):
                await send_func(receiver_id, media_file_id)
                await bot.send_message(receiver_id, text, parse_mode="HTML", reply_markup=keyboard)
            else:
                await send_func(receiver_id, media_file_id, caption=text, 
                               parse_mode="HTML", reply_markup=keyboard)
    else:
        await bot.send_message(receiver_id, text, parse_mode="HTML", reply_markup=keyboard)


@router.message(CommandStart(deep_link=True))
async def cmd_start_deep_link(message: Message, state: FSMContext):
    await db.get_or_create_user(message.from_user.id, message.from_user.username)
    
    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        payload = args[1]
        
        if payload.startswith("r_"):
            reply_hash = payload[2:]
            pending = await db.get_pending_reply(reply_hash)
            if pending:
                await state.update_data(
                    target_id=pending['sender_id'],
                    is_reply=True
                )
                await state.set_state(SendMessage.waiting_for_reply)
                await message.answer(
                    "✍️ Напишите ваш ответ.\n"
                    "Отправьте текст, фото, видео, голосовое или стикер.",
                    reply_markup=get_cancel_keyboard()
                )
                return
        
        target_user = await db.get_user_by_code(payload)
        if target_user:
            if target_user['user_id'] == message.from_user.id and message.from_user.id != ADMIN_ID:
                await message.answer(
                    "🙈 Вы не можете отправить сообщение самому себе!\n\n"
                    "Отправьте свою ссылку друзьям.",
                    reply_markup=get_main_keyboard()
                )
                return
            
            await state.update_data(target_id=target_user['user_id'])
            await state.set_state(SendMessage.waiting_for_message)
            await message.answer(
                "✍️ Напишите анонимное сообщение.\n"
                "Отправьте текст, фото, видео, голосовое или стикер.\n\n"
                "Получатель не узнает, кто его отправил.",
                reply_markup=get_cancel_keyboard()
            )
        else:
            await cmd_start(message, state)
    else:
        await cmd_start(message, state)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await db.get_or_create_user(message.from_user.id, message.from_user.username)
    
    is_admin = message.from_user.id == ADMIN_ID
    text = (
        f"👋 Добро пожаловать в <b>AntiCensura</b>!\n\n"
        f"🔐 Отправляйте и получайте анонимные сообщения.\n\n"
        f"📩 Нажмите <b>«Моя ссылка»</b> для получения персональной ссылки."
    )
    
    if is_admin:
        pending = await db.get_pending_messages_count()
        alerts = await db.get_unresolved_alerts()
        text += f"\n\n👑 <b>Админ</b> | На модерации: {pending}"
        if alerts:
            text += f" | 🚨 Алертов: {len(alerts)}"
    
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_keyboard(is_admin))


@router.callback_query(F.data == "my_link")
async def show_my_link(callback: CallbackQuery):
    user = await db.get_or_create_user(callback.from_user.id, callback.from_user.username)
    bot_info = await callback.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={user['code']}"
    
    await callback.message.edit_text(
        f"🔗 Ваша персональная ссылка:\n\n"
        f"<code>{link}</code>\n\n"
        f"📤 Отправьте её друзьям, чтобы получать анонимные сообщения!",
        parse_mode="HTML",
        reply_markup=get_back_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "stats")
async def show_stats(callback: CallbackQuery):
    stats = await db.get_user_stats(callback.from_user.id)
    
    await callback.message.edit_text(
        f"📊 <b>Ваша статистика</b>\n\n"
        f"📥 Получено сообщений: <b>{stats['received']}</b>\n"
        f"📤 Отправлено сообщений: <b>{stats['sent']}</b>",
        parse_mode="HTML",
        reply_markup=get_back_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("history:"))
async def show_history(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    limit = 5
    offset = page * limit
    
    messages = await db.get_user_messages(callback.from_user.id, limit + 1, offset)
    has_more = len(messages) > limit
    messages = messages[:limit]
    
    if not messages:
        text = "📭 У вас пока нет сообщений."
    else:
        text = f"📬 <b>История сообщений</b> (стр. {page + 1})\n\n"
        for i, msg in enumerate(messages, 1):
            status = "✅" if msg['is_read'] else "🆕"
            content = msg['content'] or msg['caption'] or f"[{msg['media_type']}]"
            if len(content) > 50:
                content = content[:50] + "..."
            text += f"{status} {content}\n"
    
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=get_history_keyboard(page, has_more)
    )
    await callback.answer()


@router.callback_query(F.data == "back")
async def go_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    
    is_admin = callback.from_user.id == ADMIN_ID
    text = (
        f"👋 <b>AntiCensura</b>\n\n"
        f"🔐 Отправляйте и получайте анонимные сообщения."
    )
    
    if is_admin:
        pending = await db.get_pending_messages_count()
        alerts = await db.get_unresolved_alerts()
        text += f"\n\n👑 <b>Админ</b> | На модерации: {pending}"
        if alerts:
            text += f" | 🚨 Алертов: {len(alerts)}"
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_main_keyboard(is_admin))
    await callback.answer()


# === ADMIN PANEL ===

@router.callback_query(F.data == "admin_panel")
async def show_admin_panel(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    pending = await db.get_pending_messages_count()
    alerts = await db.get_unresolved_alerts()
    logs = await db.get_mod_log(5)
    
    text = (
        f"👑 <b>Админ-панель</b>\n\n"
        f"📋 На модерации: {pending}\n"
        f"🚨 Активных алертов: {len(alerts)}\n\n"
        f"<b>Последние действия:</b>\n"
    )
    
    if logs:
        for log in logs[:5]:
            text += f"• {log['action']} (ID:{log['message_id'] or '-'})\n"
    else:
        text += "• Нет действий\n"
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_admin_panel_keyboard())
    await callback.answer()


@router.callback_query(F.data == "mod_log")
async def show_mod_log(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    logs = await db.get_mod_log(20)
    
    text = "📋 <b>Журнал модерации</b>\n\n"
    
    if logs:
        for log in logs:
            action_emoji = {"approve": "✅", "reject": "❌", "answer_dm": "💬", "answer_channel": "📢", "block": "🚫"}.get(log['action'], "•")
            text += f"{action_emoji} {log['action']} | ID:{log['message_id'] or '-'} | {log['created_at'][:16]}\n"
    else:
        text += "Журнал пуст"
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_back_keyboard())
    await callback.answer()


@router.callback_query(F.data == "alerts")
async def show_alerts(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    alerts = await db.get_unresolved_alerts()
    
    text = "🚨 <b>Активные алерты</b>\n\n"
    
    if alerts:
        for alert in alerts:
            text += f"• [{alert['alert_type']}] {alert['details'] or ''}\n  ID:{alert['id']} | User:{alert['user_id'] or '-'}\n\n"
    else:
        text += "Нет активных алертов ✅"
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_back_keyboard())
    await callback.answer()


@router.callback_query(F.data == "urgent_messages")
async def show_urgent_messages(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    urgent = await db.get_urgent_messages()
    
    text = "🔥 <b>Срочные сообщения</b>\n\n"
    
    if urgent:
        for msg in urgent[:10]:
            content = (msg['content'] or msg['caption'] or '[медиа]')[:50]
            text += f"• ID:{msg['id']} | {content}...\n"
    else:
        text += "Нет срочных сообщений ✅"
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_back_keyboard())
    await callback.answer()


# === ANALYTICS ===

@router.callback_query(F.data == "analytics")
async def show_analytics(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    stats = await db.get_analytics_summary()
    
    text = (
        f"📊 <b>Аналитика</b>\n\n"
        f"📨 Всего сообщений: <b>{stats['total']}</b>\n"
        f"📅 Сегодня: <b>{stats['today']}</b>\n"
        f"📆 За неделю: <b>{stats['week']}</b>\n"
        f"⏳ На модерации: <b>{stats['pending']}</b>\n"
    )
    
    if stats['urgent_pending']:
        text += f"🔥 Срочных: <b>{stats['urgent_pending']}</b>\n"
    
    if stats['peak_hour'] is not None:
        text += f"\n⏰ Пик активности: <b>{stats['peak_hour']}:00</b>\n"
    
    if stats['sentiments']:
        text += f"\n<b>Тональность:</b>\n"
        emoji = {"positive": "😊", "neutral": "😐", "negative": "😢"}
        for sent, count in stats['sentiments'].items():
            text += f"{emoji.get(sent, '•')} {sent}: {count}\n"
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_analytics_keyboard())
    await callback.answer()


@router.callback_query(F.data == "chart_heatmap")
async def send_heatmap(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await callback.answer("⏳ Генерация графика...")
    
    hourly_data = await db.get_hourly_activity(7)
    chart = generate_heatmap(hourly_data)
    
    await bot.send_photo(
        callback.from_user.id,
        BufferedInputFile(chart.read(), filename="heatmap.png"),
        caption="🔥 Активность по часам (последние 7 дней)"
    )


@router.callback_query(F.data == "chart_weekly")
async def send_weekly_heatmap(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await callback.answer("⏳ Генерация графика...")
    
    weekly_data = await db.get_weekly_hourly_activity(30)
    chart = generate_weekly_heatmap(weekly_data)
    
    await bot.send_photo(
        callback.from_user.id,
        BufferedInputFile(chart.read(), filename="weekly_heatmap.png"),
        caption="📅 Тепловая карта по дням недели (последние 30 дней)"
    )


@router.callback_query(F.data == "chart_sentiment")
async def send_sentiment_chart(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await callback.answer("⏳ Генерация графика...")
    
    sentiment_data = await db.get_sentiment_stats()
    chart = generate_sentiment_chart(sentiment_data)
    
    await bot.send_photo(
        callback.from_user.id,
        BufferedInputFile(chart.read(), filename="sentiment.png"),
        caption="😊 Анализ тональности сообщений"
    )


@router.callback_query(F.data == "chart_trend")
async def send_trend_chart(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await callback.answer("⏳ Генерация графика...")
    
    daily_data = await db.get_daily_activity(30)
    chart = generate_activity_trend(daily_data)
    
    await bot.send_photo(
        callback.from_user.id,
        BufferedInputFile(chart.read(), filename="trend.png"),
        caption="📈 Динамика сообщений (последние 30 дней)"
    )


@router.callback_query(F.data.startswith("block:"))
async def block_user_handler(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    parts = callback.data.split(":")
    user_id = int(parts[1])
    hours = int(parts[2])
    
    await db.block_user(user_id, hours)
    await db.log_mod_action(callback.from_user.id, "block", target_user_id=user_id, details=f"{hours}h")
    
    try:
        await bot.send_message(user_id, f"🚫 Вы заблокированы на {hours} часов.")
    except:
        pass
    
    await callback.answer(f"✅ Пользователь заблокирован на {hours}ч", show_alert=True)


# === DISCUSSIONS ===

@router.callback_query(F.data.startswith("join_discussion:"))
async def join_discussion(callback: CallbackQuery, state: FSMContext):
    message_id = int(callback.data.split(":")[1])
    msg = await db.get_message(message_id)
    
    if not msg:
        await callback.answer("❌ Сообщение не найдено", show_alert=True)
        return
    
    if not msg['channel_message_id']:
        await callback.answer("❌ Сообщение ещё не опубликовано", show_alert=True)
        return
    
    await state.update_data(
        reply_to_message_id=message_id,
        target_id=msg['receiver_id'],
        is_reply=True,
        is_discussion=True
    )
    await state.set_state(SendMessage.waiting_for_reply)
    
    await callback.message.answer(
        "💬 Напишите ваш комментарий к обсуждению.\n"
        "Он будет отправлен на модерацию и опубликован как ответ.",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "cancel")
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "❌ Отменено.",
        reply_markup=get_back_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("read:"))
async def mark_as_read(callback: CallbackQuery, bot: Bot):
    message_id = int(callback.data.split(":")[1])
    msg = await db.get_message(message_id)
    
    if msg and not msg['is_read']:
        await db.mark_message_read(message_id)
        
        pending = await db.get_pending_reply(generate_reply_hash(msg['sender_id'], msg['receiver_id']))
        if pending:
            try:
                await bot.send_message(
                    msg['sender_id'],
                    "👁 Ваше сообщение было прочитано!",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Failed to send read notification: {e}")
    
    await callback.answer("✅ Отмечено как прочитанное")


@router.callback_query(F.data.startswith("reply:"))
async def start_reply(callback: CallbackQuery, state: FSMContext):
    message_id = int(callback.data.split(":")[1])
    msg = await db.get_message(message_id)
    
    if not msg:
        await callback.answer("❌ Сообщение не найдено", show_alert=True)
        return
    
    await state.update_data(
        target_id=msg['sender_id'], 
        is_reply=True,
        reply_to_message_id=message_id
    )
    await state.set_state(SendMessage.waiting_for_reply)
    
    await callback.message.answer(
        "✍️ Напишите ваш ответ.\n"
        "Отправьте текст, фото, видео, голосовое или стикер.",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("approve:"))
async def approve_message(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    message_id = int(callback.data.split(":")[1])
    msg = await db.get_message(message_id)
    
    if not msg:
        await callback.answer("❌ Сообщение не найдено", show_alert=True)
        return
    
    if msg['status'] != 'pending':
        await callback.answer("⚠️ Сообщение уже обработано", show_alert=True)
        return
    
    await db.update_message_status(message_id, 'approved')
    await db.log_mod_action(callback.from_user.id, "approve", message_id, msg['sender_id'])
    
    is_reply = msg['reply_to_id'] is not None
    reply_to_channel_msg_id = None
    
    if is_reply and msg['reply_to_id']:
        original_msg = await db.get_message(msg['reply_to_id'])
        if original_msg and original_msg['channel_message_id']:
            reply_to_channel_msg_id = original_msg['channel_message_id']
    
    try:
        channel_msg_id = await publish_to_channel(
            bot, message_id, msg['content'], msg['media_type'], 
            msg['media_file_id'], msg['caption'], is_reply, reply_to_channel_msg_id
        )
        
        if channel_msg_id:
            await db.set_channel_message_id(message_id, channel_msg_id)
        
        await bot.send_message(
            msg['sender_id'],
            "✅ Ваше сообщение одобрено и опубликовано!",
            reply_markup=get_user_reply_keyboard(message_id)
        )
    except Exception as e:
        logger.error(f"Failed to publish message: {e}")
    
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.reply(
        "✅ Одобрено и опубликовано",
        reply_markup=get_answer_sender_keyboard(message_id)
    )
    await callback.answer("✅ Одобрено")


class AnswerSender(StatesGroup):
    waiting_for_dm = State()
    waiting_for_channel = State()


@router.callback_query(F.data.startswith("answer_dm:"))
async def start_answer_dm(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    message_id = int(callback.data.split(":")[1])
    msg = await db.get_message(message_id)
    
    if not msg:
        await callback.answer("❌ Сообщение не найдено", show_alert=True)
        return
    
    await state.update_data(answer_to_user_id=msg['sender_id'])
    await state.set_state(AnswerSender.waiting_for_dm)
    
    await callback.message.answer(
        "💬 Напишите сообщение для отправителя.\n"
        "Оно будет отправлено в ЛС от имени модератора.",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("answer_channel:"))
async def start_answer_channel(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    message_id = int(callback.data.split(":")[1])
    msg = await db.get_message(message_id)
    
    if not msg:
        await callback.answer("❌ Сообщение не найдено", show_alert=True)
        return
    
    await state.update_data(
        reply_to_message_id=message_id,
        is_admin_reply=True
    )
    await state.set_state(AnswerSender.waiting_for_channel)
    
    await callback.message.answer(
        "📢 Напишите ответ для публикации в канал.\n"
        "Он будет опубликован как ответ от модератора.",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("user_reply:"))
async def start_user_reply(callback: CallbackQuery, state: FSMContext):
    message_id = int(callback.data.split(":")[1])
    msg = await db.get_message(message_id)
    
    if not msg:
        await callback.answer("❌ Сообщение не найдено", show_alert=True)
        return
    
    await state.update_data(
        reply_to_message_id=message_id,
        target_id=msg['receiver_id'],
        is_reply=True
    )
    await state.set_state(SendMessage.waiting_for_reply)
    
    await callback.message.answer(
        "💬 Напишите ваш ответ для канала.\n"
        "Он будет отправлен на модерацию.",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()


@router.message(AnswerSender.waiting_for_dm)
async def send_answer_dm(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    user_id = data.get("answer_to_user_id")
    
    if not user_id:
        await state.clear()
        await message.answer("❌ Ошибка.", reply_markup=get_main_keyboard())
        return
    
    try:
        await bot.send_message(
            user_id,
            f"💬 <b>Сообщение от модератора:</b>\n\n{message.text}",
            parse_mode="HTML"
        )
        await message.answer("✅ Сообщение отправлено в ЛС!", reply_markup=get_main_keyboard())
    except Exception as e:
        logger.error(f"Failed to send answer: {e}")
        await message.answer("❌ Не удалось отправить.", reply_markup=get_main_keyboard())
    
    await state.clear()


@router.message(AnswerSender.waiting_for_channel)
async def send_answer_channel(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    reply_to_message_id = data.get("reply_to_message_id")
    
    if not reply_to_message_id:
        await state.clear()
        await message.answer("❌ Ошибка.", reply_markup=get_main_keyboard())
        return
    
    original_msg = await db.get_message(reply_to_message_id)
    reply_to_channel_msg_id = original_msg['channel_message_id'] if original_msg else None
    
    try:
        channel_msg_id = await publish_to_channel(
            bot, None, message.text, None, None, None, 
            is_reply=True, reply_to_channel_msg_id=reply_to_channel_msg_id,
            is_moderator=True
        )
        await message.answer("✅ Ответ опубликован в канал!", reply_markup=get_main_keyboard())
    except Exception as e:
        logger.error(f"Failed to publish answer: {e}")
        await message.answer("❌ Не удалось опубликовать.", reply_markup=get_main_keyboard())
    
    await state.clear()


@router.callback_query(F.data.startswith("reject:"))
async def reject_message(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    message_id = int(callback.data.split(":")[1])
    msg = await db.get_message(message_id)
    
    if not msg:
        await callback.answer("❌ Сообщение не найдено", show_alert=True)
        return
    
    if msg['status'] != 'pending':
        await callback.answer("⚠️ Сообщение уже обработано", show_alert=True)
        return
    
    await db.update_message_status(message_id, 'rejected')
    await db.log_mod_action(callback.from_user.id, "reject", message_id, msg['sender_id'])
    
    try:
        await bot.send_message(
            msg['sender_id'],
            "❌ Ваше сообщение отклонено модератором."
        )
    except Exception as e:
        logger.error(f"Failed to notify sender: {e}")
    
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.reply(
        "❌ Отклонено",
        reply_markup=get_answer_sender_keyboard(message_id)
    )
    await callback.answer("❌ Отклонено")


async def process_message(message: Message, state: FSMContext, bot: Bot, is_reply: bool = False):
    user_id = message.from_user.id
    
    # Rate limiting (skip for admin)
    if user_id != ADMIN_ID:
        rate_check = await db.check_rate_limit(user_id, RATE_LIMIT_MESSAGES, RATE_LIMIT_WINDOW_MINUTES)
        
        if rate_check.get("blocked"):
            await state.clear()
            await message.answer(
                f"🚫 Вы заблокированы до {rate_check['until'].strftime('%d.%m %H:%M')}",
                reply_markup=get_main_keyboard()
            )
            return
        
        if not rate_check["allowed"]:
            await state.clear()
            await message.answer(
                f"⏳ Достигнут лимит: {rate_check['limit']} сообщений в час.\nПопробуйте позже.",
                reply_markup=get_main_keyboard()
            )
            # Alert if close to spam threshold
            if rate_check["count"] >= SPAM_THRESHOLD - 5:
                await db.create_alert("spam_attempt", user_id, f"Rate limit hit: {rate_check['count']} msgs")
                await send_alert_to_admin(bot, f"⚠️ Подозрительная активность: user {user_id} достиг лимита")
            return
        
        # Check for spam behavior
        if rate_check["count"] >= SPAM_THRESHOLD:
            await db.block_user(user_id, 24)
            await db.create_alert("auto_block", user_id, f"Auto-blocked for spam: {rate_check['count']} msgs")
            await send_alert_to_admin(bot, f"🚫 Авто-блок: user {user_id} за спам ({rate_check['count']} сообщений)")
            await state.clear()
            await message.answer("🚫 Вы заблокированы за спам на 24 часа.", reply_markup=get_main_keyboard())
            return
    
    data = await state.get_data()
    target_id = data.get("target_id")
    reply_to_message_id = data.get("reply_to_message_id") if is_reply else None
    
    if not target_id:
        await state.clear()
        await message.answer("❌ Ошибка. Попробуйте снова.", reply_markup=get_main_keyboard())
        return
    
    content = None
    media_type = None
    media_file_id = None
    caption = None
    
    if message.content_type == ContentType.TEXT:
        content = message.text
    elif message.content_type in MEDIA_TYPES:
        media_type = MEDIA_TYPES[message.content_type]
        caption = message.caption
        
        if message.photo:
            media_file_id = message.photo[-1].file_id
        elif message.video:
            media_file_id = message.video.file_id
        elif message.voice:
            media_file_id = message.voice.file_id
        elif message.video_note:
            media_file_id = message.video_note.file_id
        elif message.audio:
            media_file_id = message.audio.file_id
        elif message.document:
            media_file_id = message.document.file_id
        elif message.sticker:
            media_file_id = message.sticker.file_id
        elif message.animation:
            media_file_id = message.animation.file_id
    else:
        await message.answer("❌ Этот тип сообщения не поддерживается.")
        return
    
    status = 'pending' if MODERATION_ENABLED else 'approved'
    message_id = await db.save_message(
        message.from_user.id, target_id, content, media_type, media_file_id, caption, status,
        reply_to_id=reply_to_message_id
    )
    
    # Analyze sentiment
    text_to_analyze = content or caption or ""
    sentiment_result = analyze_sentiment(text_to_analyze)
    await db.update_message_sentiment(message_id, sentiment_result['sentiment'], sentiment_result['urgent'])
    
    # Alert for urgent messages
    if sentiment_result['urgent']:
        await send_alert_to_admin(bot, f"🔥 <b>СРОЧНОЕ сообщение!</b>\n\nID: {message_id}\n{text_to_analyze[:200]}")
    
    if MODERATION_ENABLED:
        await send_to_moderation(bot, message_id, message.from_user.id, content, 
                                 media_type, media_file_id, caption, is_reply, reply_to_message_id)
        await message.answer(
            "✅ Сообщение отправлено на модерацию.\n"
            "Вы получите уведомление после проверки.",
            reply_markup=get_main_keyboard()
        )
    else:
        try:
            channel_msg_id = await publish_to_channel(
                bot, message_id, content, media_type, media_file_id, caption, is_reply
            )
            if channel_msg_id:
                await db.set_channel_message_id(message_id, channel_msg_id)
            
            await message.answer(
                "✅ Сообщение опубликовано!",
                reply_markup=get_main_keyboard()
            )
        except Exception as e:
            logger.error(f"Failed to publish message: {e}")
            await message.answer(
                "❌ Не удалось опубликовать сообщение.",
                reply_markup=get_main_keyboard()
            )
    
    await state.clear()


@router.message(SendMessage.waiting_for_message)
async def handle_anonymous_message(message: Message, state: FSMContext, bot: Bot):
    await process_message(message, state, bot, is_reply=False)


@router.message(SendMessage.waiting_for_reply)
async def handle_reply_message(message: Message, state: FSMContext, bot: Bot):
    await process_message(message, state, bot, is_reply=True)


@router.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "📖 <b>Как пользоваться AntiCensura:</b>\n\n"
        "1️⃣ Нажмите <b>«Моя ссылка»</b>\n"
        "2️⃣ Отправьте ссылку друзьям\n"
        "3️⃣ Получайте анонимные сообщения\n"
        "4️⃣ Отвечайте через кнопку под сообщением\n\n"
        "📎 Поддерживаются: текст, фото, видео, голосовые, стикеры\n\n"
        "🔐 Анонимность гарантирована!"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_keyboard())


async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is not set!")
        return
    
    await db.init_db()
    
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    
    logger.info("Starting AntiCensura bot...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
