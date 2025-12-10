from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_main_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📩 Моя ссылка", callback_data="my_link")],
        [InlineKeyboardButton(text="📬 История сообщений", callback_data="history:0")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")]
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
    ])


def get_reply_keyboard(message_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="↩️ Ответить", callback_data=f"reply:{message_id}"),
            InlineKeyboardButton(text="✅ Прочитано", callback_data=f"read:{message_id}")
        ]
    ])


def get_moderation_keyboard(message_id: int, sender_id: int = None) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve:{message_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{message_id}")
        ]
    ]
    if sender_id:
        buttons.append([
            InlineKeyboardButton(text="🚫 Блок 24ч", callback_data=f"block:{sender_id}:24"),
            InlineKeyboardButton(text="⛔ Блок 7д", callback_data=f"block:{sender_id}:168")
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_history_keyboard(page: int, has_more: bool) -> InlineKeyboardMarkup:
    buttons = []
    nav_row = []
    
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"history:{page - 1}"))
    
    if has_more:
        nav_row.append(InlineKeyboardButton(text="▶️ Далее", callback_data=f"history:{page + 1}"))
    
    if nav_row:
        buttons.append(nav_row)
    
    buttons.append([InlineKeyboardButton(text="🏠 Меню", callback_data="back")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Ожидают модерации", callback_data="pending")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="back")]
    ])


def get_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])


def get_answer_sender_keyboard(message_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Ответить в ЛС", callback_data=f"answer_dm:{message_id}")],
        [InlineKeyboardButton(text="📢 Ответить в канал", callback_data=f"answer_channel:{message_id}")]
    ])


def get_user_reply_keyboard(message_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Ответить в канал", callback_data=f"user_reply:{message_id}")]
    ])


def get_admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Аналитика", callback_data="analytics")],
        [InlineKeyboardButton(text="📋 Журнал модерации", callback_data="mod_log")],
        [InlineKeyboardButton(text="🚨 Алерты", callback_data="alerts")],
        [InlineKeyboardButton(text="🔥 Срочные", callback_data="urgent_messages")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
    ])


def get_analytics_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 Тепловая карта", callback_data="chart_heatmap")],
        [InlineKeyboardButton(text="📈 Динамика", callback_data="chart_trend")],
        [InlineKeyboardButton(text="😊 Тональность", callback_data="chart_sentiment")],
        [InlineKeyboardButton(text="📅 По дням недели", callback_data="chart_weekly")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
    ])


def get_discussion_keyboard(message_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Присоединиться к обсуждению", callback_data=f"join_discussion:{message_id}")]
    ])


def get_block_user_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🚫 Блок 24ч", callback_data=f"block:{user_id}:24"),
            InlineKeyboardButton(text="🚫 Блок 7д", callback_data=f"block:{user_id}:168")
        ],
        [InlineKeyboardButton(text="⛔ Блок навсегда", callback_data=f"block:{user_id}:8760")]
    ])
