import os
import random
import asyncio
from telegram import InputFile
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import TimedOut
from datetime import datetime, timedelta  
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackContext,
    CallbackQueryHandler,
)
from dotenv import load_dotenv
from tarot_interpreter import generate_tarot_interpretation
from database import (
    add_user, get_user, update_free_attempts, save_tarot_reading,
    activate_subscription, get_subscription_status
)

# Загрузка конфигураций из .env
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")  # ID чата администратора
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")  # Telegram администратора

# Состояния ConversationHandler
CHOOSE_METHOD, QUESTION, SITUATION, NUM_CARDS, ENTER_CARDS, ASK_QUESTION = range(6)

# Определение колоды Таро
tarot_deck = [
    # Старшие Арканы (22 карты)
    "Шут", "Маг", "Верховная Жрица", "Императрица", "Император", 
    "Иерофант", "Влюбленные", "Колесница", "Сила", "Отшельник", 
    "Колесо Фортуны", "Справедливость", "Повешенный", "Смерть", 
    "Умеренность", "Дьявол", "Башня", "Звезда", "Луна", "Солнце", 
    "Суд", "Мир",
    # Младшие Арканы: Жезлы (14 карт)
    "Туз Жезлов", "Двойка Жезлов", "Тройка Жезлов", "Четверка Жезлов", 
    "Пятерка Жезлов", "Шестерка Жезлов", "Семерка Жезлов", "Восьмерка Жезлов", 
    "Девятка Жезлов", "Десятка Жезлов", "Паж Жезлов", "Рыцарь Жезлов", 
    "Королева Жезлов", "Король Жезлов",
    # Младшие Арканы: Кубки (14 карт)
    "Туз Кубков", "Двойка Кубков", "Тройка Кубков", "Четверка Кубков", 
    "Пятерка Кубков", "Шестерка Кубков", "Семерка Кубков", "Восьмерка Кубков", 
    "Девятка Кубков", "Десятка Кубков", "Паж Кубков", "Рыцарь Кубков", 
    "Королева Кубков", "Король Кубков",
    # Младшие Арканы: Мечи (14 карт)
    "Туз Мечей", "Двойка Мечей", "Тройка Мечей", "Четверка Мечей", 
    "Пятерка Мечей", "Шестерка Мечей", "Семерка Мечей", "Восьмерка Мечей", 
    "Девятка Мечей", "Десятка Мечей", "Паж Мечей", "Рыцарь Мечей", 
    "Королева Мечей", "Король Мечей",
    # Младшие Арканы: Пентакли (14 карт)
    "Туз Пентаклей", "Двойка Пентаклей", "Тройка Пентаклей", "Четверка Пентаклей", 
    "Пятерка Пентаклей", "Шестерка Пентаклей", "Семерка Пентаклей", "Восьмерка Пентаклей", 
    "Девятка Пентаклей", "Десятка Пентаклей", "Паж Пентаклей", "Рыцарь Пентаклей", 
    "Королева Пентаклей", "Король Пентаклей"
]

bot = Application.builder().token(TELEGRAM_TOKEN).read_timeout(30).write_timeout(30).build()

# Проверка количества попыток
def check_free_attempts(telegram_id: int) -> int:
    user = get_user(telegram_id)
    if user is None:
        print(f"Ошибка: пользователь {telegram_id} не найден в базе.")
        return 0
    return user[3]

def decrease_attempts(telegram_id: int) -> bool:
    user = get_user(telegram_id)
    if user is None:
        return False
    if get_subscription_status(telegram_id) == "active":
        return True  
    attempts = user[3]
    if attempts > 0:
        update_free_attempts(telegram_id, attempts - 1)
        return True
    return False

WELCOME_IMAGE_URL = "https://postimg.cc/SXqjBSWY"

async def start(update: Update, context: CallbackContext) -> None:
    try:
        telegram_id = update.message.from_user.id
        username = update.message.from_user.username
        add_user(telegram_id, username)

        # Отправка изображения с приветствием
        await update.message.reply_photo(
            photo=WELCOME_IMAGE_URL,
            caption="🌟 *Добро пожаловать в мир Таро!* 🌟\n\n"
                    "Я — ваш личный бот-таролог, готовый помочь вам найти ответы на важные вопросы. "
                    "Выберите действие, чтобы начать:",
            parse_mode="Markdown"
        )

        keyboard = [
            [InlineKeyboardButton("🃏 Запросить расклад", callback_data="request_reading")],
            [InlineKeyboardButton("💼 Подписка", callback_data="subscription")],
            [InlineKeyboardButton("📜 Значения карт", callback_data="card_meanings")],
            [InlineKeyboardButton("📖 Расклады", callback_data="spreads")],
            [InlineKeyboardButton("📞 Заказать у администратора", callback_data="order_from_admin")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Выберите действие:", reply_markup=reply_markup)
    except TimedOut:
        await update.message.reply_text("Произошла ошибка: время ожидания истекло. Пожалуйста, попробуйте снова.")

async def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "request_reading":
        telegram_id = query.from_user.id
        # Проверяем, есть ли попытки
        attempts = check_free_attempts(telegram_id)
        if attempts <= 0:
            await query.edit_message_text(
                "❌ *У вас закончились бесплатные попытки.*\n\n"
                "Чтобы продолжить, оформите подписку или закажите расклад у администратора.",
                parse_mode="Markdown"
            )
            return ConversationHandler.END
        await query.edit_message_text(
            "🔮 <b>Задайте ваш вопрос.</b>\n\n"
            "Чем точнее вы сформулируете вопрос, тем более точным будет ответ. "
            "Например: «Что меня ждет в отношениях в ближайшие 3 месяца?»",
            parse_mode="HTML"
        )
        return QUESTION
    elif query.data == "subscription":
        await subscription_handler(update, context)
    elif query.data == "card_meanings":
        await query.edit_message_text(
            "📚 <b>Значения карт Таро</b>\n\n"
            "Здесь вы можете узнать значение каждой карты Таро. "
            "Выберите карту из списка, чтобы узнать больше.",
            parse_mode="HTML"
        )
    elif query.data == "spreads":
        await query.edit_message_text(
            "📜 <b>Доступные расклады</b>\n\n"
            "1. Расклад на день.\n"
            "2. Расклад на отношения.\n"
            "3. Расклад на карьеру.\n\n"
            "Выберите расклад, чтобы начать.",
            parse_mode="HTML"
        )
    elif query.data == "order_from_admin":
        await query.edit_message_text(
            "📝 <b>Заказ у администратора</b>\n\n"
            "Напишите ваш вопрос, и администратор свяжется с вами для уточнения деталей. "
            "Пример вопроса: «Мне нужен подробный расклад на любовь и отношения.»",
            parse_mode="HTML"
        )
        return ASK_QUESTION
    else:
        await query.edit_message_text("Неизвестная команда.")

async def subscription_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()

    user = get_user(query.from_user.id)
    free_attempts = user[3] if user else 0
    subscription_status = get_subscription_status(query.from_user.id)

    keyboard = [
        [InlineKeyboardButton("💎 Месячная подписка", callback_data="monthly_subscription")],
        [InlineKeyboardButton("🛒 Разовая покупка (5 попыток)", callback_data="one_time_purchase_5")],
        [InlineKeyboardButton("🛒 Разовая покупка (10 попыток)", callback_data="one_time_purchase_10")],
        [InlineKeyboardButton("🛒 Разовая покупка (15 попыток)", callback_data="one_time_purchase_15")],
        [InlineKeyboardButton("🔙 Назад", callback_data="start_over")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    subscription_text = (
        f"💎 *Премиум-подписка и разовые покупки*\n\n"
        f"1. 💎 *Месячная подписка:*\n"
        f"   - Неограниченное количество раскладов.\n"
        f"   - Доступ к эксклюзивным раскладам.\n"
        f"   - Персональные консультации от администратора.\n"
        f"   - Стоимость: *349₽/месяц*.\n\n"
        f"2. 🛒 *Разовая покупка:*\n"
        f"   - Получите дополнительные попытки для запросов раскладов.\n"
        f"   - Стоимость: 5 попыток - *99₽*, 10 попыток - *149₽*, 15 попыток - *229₽*.\n\n"
        f"Ваш текущий статус подписки: <b>{subscription_status}</b>\n"
        f"Осталось бесплатных запросов: <b>{free_attempts}</b>\n\n"
        f"Выберите опцию:"
    )
    await query.edit_message_text(subscription_text, reply_markup=reply_markup, parse_mode="HTML")

async def monthly_subscription_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("💳 Оплатить подписку", callback_data="pay_monthly_subscription")],
        [InlineKeyboardButton("🔙 Назад", callback_data="subscription")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "💎 *Месячная подписка*\n\n"
        "Вы получите:\n"
        "✅ Неограниченное количество раскладов.\n"
        "✅ Доступ к эксклюзивным раскладам.\n"
        "✅ Персональные консультации от администратора.\n\n"
        "Стоимость: *349₽/месяц*.\n\n"
        "Нажмите *«Оплатить подписку»* для оплаты.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def one_time_purchase_5_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("💳 Оплатить 5 попыток", callback_data="pay_one_time_purchase_5")],
        [InlineKeyboardButton("🔙 Назад", callback_data="subscription")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "🛒 *Разовая покупка (5 попыток)*\n\n"
        "Вы получите:\n"
        "✅ 5 дополнительных попыток для запросов раскладов.\n\n"
        "Стоимость: *99₽*.\n\n"
        "Нажмите *«Оплатить 5 попыток»* для оплаты.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def one_time_purchase_10_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("💳 Оплатить 10 попыток", callback_data="pay_one_time_purchase_10")],
        [InlineKeyboardButton("🔙 Назад", callback_data="subscription")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "🛒 *Разовая покупка (10 попыток)*\n\n"
        "Вы получите:\n"
        "✅ 10 дополнительных попыток для запросов раскладов.\n\n"
        "Стоимость: *149₽*.\n\n"
        "Нажмите *«Оплатить 10 попыток»* для оплаты.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def one_time_purchase_15_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("💳 Оплатить 15 попыток", callback_data="pay_one_time_purchase_15")],
        [InlineKeyboardButton("🔙 Назад", callback_data="subscription")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "🛒 *Разовая покупка (15 попыток)*\n\n"
        "Вы получите:\n"
        "✅ 15 дополнительных попыток для запросов раскладов.\n\n"
        "Стоимость: *229₽*.\n\n"
        "Нажмите *«Оплатить 15 попыток»* для оплаты.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def send_admin_contacts(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()

    admin_contacts = (
        "📞 <b>Контакты администратора:</b>\n\n"
        "Для оплаты и уточнения деталей свяжитесь с администратором:\n"
        f"- Telegram: {ADMIN_USERNAME}\n"
        "Напишите администратору, и он поможет вам с оплатой."
    )

    await query.edit_message_text(admin_contacts, parse_mode="HTML")

async def pay_monthly_subscription_handler(update: Update, context: CallbackContext) -> None:
    await send_admin_contacts(update, context)

async def pay_one_time_purchase_5_handler(update: Update, context: CallbackContext) -> None:
    await send_admin_contacts(update, context)

async def pay_one_time_purchase_10_handler(update: Update, context: CallbackContext) -> None:
    await send_admin_contacts(update, context)

async def pay_one_time_purchase_15_handler(update: Update, context: CallbackContext) -> None:
    await send_admin_contacts(update, context)

async def start_over_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    await start(query, context)

async def tarot_reading(update: Update, context: CallbackContext) -> int:
    if update.message:
        telegram_id = update.message.from_user.id
        response_target = update.message
    elif update.callback_query and update.callback_query.message:
        telegram_id = update.callback_query.from_user.id
        response_target = update.callback_query.message
    else:
        return ConversationHandler.END

    await response_target.reply_text(
        "🔮 *Задайте ваш вопрос.*\n\n"
        "Чем точнее вы сформулируете вопрос, тем более точным будет ответ. "
        "Например: «Что меня ждет в отношениях в ближайшие 3 месяца?»",
        parse_mode="Markdown"
    )
    return QUESTION

async def question_handler(update: Update, context: CallbackContext) -> int:
    context.user_data["previous_state"] = QUESTION  # Сохраняем текущее состояние
    context.user_data["question"] = update.message.text
    await update.message.reply_text(
        "📖 *Опишите предысторию.*\n\n"
        "Это не обязательно, но поможет сделать интерпретацию более точной. "
        "Например: «Мы с партнером в ссоре уже месяц, и я не знаю, как быть.»",
        parse_mode="Markdown"
    )
    return SITUATION

async def situation_handler(update: Update, context: CallbackContext) -> int:
    context.user_data["previous_state"] = SITUATION  # Сохраняем текущее состояние
    context.user_data["situation"] = update.message.text
    await update.message.reply_text(
        "🃏 *Сколько карт вы хотите выбрать для расклада?*\n\n"
        "Введите число от 1 до 5. Например: 3",
        parse_mode="Markdown"
    )
    return NUM_CARDS

async def num_cards_handler(update: Update, context: CallbackContext) -> int:
    context.user_data["previous_state"] = NUM_CARDS  # Сохраняем текущее состояние
    try:
        num_cards = int(update.message.text)
        if num_cards <= 0 or num_cards > 5:  # Ограничение на 5 карт
            await update.message.reply_text(
                f"❌ *Ошибка.*\n\n"
                f"Введите число от 1 до 5.",
                parse_mode="Markdown"
            )
            return NUM_CARDS
        context.user_data["num_cards"] = num_cards
    except ValueError:
        await update.message.reply_text(
            "❌ *Ошибка.*\n\n"
            "Пожалуйста, введите количество карт в числовом формате.",
            parse_mode="Markdown"
        )
        return NUM_CARDS

    # Предлагаем пользователю выбрать метод выбора карт
    keyboard = [
        [InlineKeyboardButton("🎲 Рандомный выбор", callback_data="random_selection")],
        [InlineKeyboardButton("🃏 Ввести карты вручную", callback_data="manual_selection")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back")],  # Добавляем кнопку "назад"
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🃏 *Выберите метод выбора карт:*",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return CHOOSE_METHOD

async def choose_method_handler(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "random_selection":
        num_cards = context.user_data["num_cards"]
        await query.edit_message_text("🃏 *Перемешиваю колоду...*", parse_mode="Markdown")
        await asyncio.sleep(2)  # Задержка для эффекта перемешивания

        selected_cards = []
        for i in range(num_cards):
            await query.edit_message_text(f"🎴 *Выбираю карту {i + 1}...*", parse_mode="Markdown")
            await asyncio.sleep(2)  # Задержка для эффекта выбора карты

            card = random.choice([c for c in tarot_deck if c not in selected_cards])
            selected_cards.append(card)

            # Эффект "открытия" карты
            await query.edit_message_text(f"🎴 *Карта {i + 1}...*\n\n✨ **Открываю карту:** ✨", parse_mode="Markdown")
            await asyncio.sleep(1)  # Задержка для эффекта открытия
            await query.edit_message_text(f"🎴 *Карта {i + 1}:*\n\n🃏 **{card}**", parse_mode="Markdown")
            await asyncio.sleep(1)  # Задержка после показа карты

        context.user_data["selected_cards"] = selected_cards

        # Кнопка для подтверждения
        keyboard = [[InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_cards")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"🃏 *Вытянуты карты:* {', '.join(selected_cards)}\n\n"
            "Нажмите *«Подтвердить»*, чтобы увидеть интерпретацию.",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return CHOOSE_METHOD
    elif query.data == "manual_selection":
        await query.edit_message_text(
            "🖋 *Введите названия карт через запятую.*\n\n"
            "Например: Шут, Маг, Императрица",
            parse_mode="Markdown"
        )
        return ENTER_CARDS
    elif query.data == "confirm_cards":
        return await generate_interpretation(update, context)
    elif query.data == "back":
        return await back_handler(update, context)  # Обработка кнопки "назад"
    else:
        await query.edit_message_text("Неизвестная команда.")
        return ConversationHandler.END

async def generate_interpretation(update: Update, context: CallbackContext) -> int:
    # Получаем данные пользователя из CallbackQuery
    if update.callback_query:
        user_id = update.callback_query.from_user.id
    else:
        user_id = update.message.from_user.id

    selected_cards = context.user_data["selected_cards"]
    question = context.user_data.get("question", "Неизвестный вопрос")
    situation = context.user_data.get("situation", "Нет информации о ситуации")
    interpretation = generate_tarot_interpretation(question, situation, selected_cards)

    # Уменьшаем количество попыток
    decrease_attempts(user_id)

    # Сохраняем расклад
    save_tarot_reading(user_id, "Таро расклад", interpretation)

    # Красивое оформление результата
    result_text = (
        f"✨ *Ваши карты:*\n"
        f"{', '.join(selected_cards)}\n\n"
        f"📖 *Интерпретация:*\n"
        f"{interpretation}\n\n"
        f"🌟 *Хотите получить более подробный и персонализированный расклад?*\n\n"
        f"📞 *Закажите личную консультацию у нашего администратора!* "
        f"Он поможет вам глубже понять ситуацию и даст рекомендации, основанные на вашем уникальном раскладе."
    )

    # Кнопки для выбора дальнейших действий
    keyboard = [
        [InlineKeyboardButton("📞 Заказать у администратора", callback_data="order_from_admin")],
        [InlineKeyboardButton("🔄 Вернуться в начало", callback_data="start_over")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(result_text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(result_text, reply_markup=reply_markup, parse_mode="Markdown")

    return ConversationHandler.END

async def enter_cards_handler(update: Update, context: CallbackContext) -> int:
    user_input = update.message.text
    selected_cards = [card.strip() for card in user_input.split(",")]

    # Проверяем, что все введенные карты есть в колоде
    invalid_cards = [card for card in selected_cards if card not in tarot_deck]
    if invalid_cards:
        await update.message.reply_text(
            f"❌ *Ошибка.*\n\n"
            f"Следующие карты не найдены в колоде: {', '.join(invalid_cards)}. "
            f"Пожалуйста, введите корректные названия карт.",
            parse_mode="Markdown"
        )
        return ENTER_CARDS

    context.user_data["selected_cards"] = selected_cards
    return await generate_interpretation(update, context)

async def ask_question_handler(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    username = update.message.from_user.username
    question = update.message.text

    if not ADMIN_CHAT_ID:
        await update.message.reply_text(
            "❌ *Ошибка.*\n\n"
            "Администратор не найден. Пожалуйста, попробуйте позже.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    # Пересылаем вопрос администратору
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"📨 *Новый вопрос от пользователя:*\n\n"
        f"👤 Пользователь: @{username} (ID: {user_id})\n"
        f"❓ Вопрос: {question}",
        parse_mode="Markdown"
    )
    await update.message.reply_text(
        "✅ *Ваш вопрос отправлен администратору!*\n\n"
        "Ожидайте ответа в ближайшее время. Спасибо за ваше доверие!",
        parse_mode="Markdown"
    )

    return ConversationHandler.END

async def cancel(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text(
        "❌ *Расклад отменен.*\n\n"
        "Если у вас есть вопросы, вы всегда можете начать заново.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def back_handler(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()

    # Возврат на предыдущий шаг
    previous_state = context.user_data.get("previous_state", CHOOSE_METHOD)
    return previous_state

# Обновляем ConversationHandler
bot.add_handler(CallbackQueryHandler(monthly_subscription_handler, pattern="^monthly_subscription$"))
bot.add_handler(CallbackQueryHandler(one_time_purchase_5_handler, pattern="^one_time_purchase_5$"))
bot.add_handler(CallbackQueryHandler(one_time_purchase_10_handler, pattern="^one_time_purchase_10$"))
bot.add_handler(CallbackQueryHandler(one_time_purchase_15_handler, pattern="^one_time_purchase_15$"))
bot.add_handler(CallbackQueryHandler(pay_monthly_subscription_handler, pattern="^pay_monthly_subscription$"))
bot.add_handler(CallbackQueryHandler(pay_one_time_purchase_5_handler, pattern="^pay_one_time_purchase_5$"))
bot.add_handler(CallbackQueryHandler(pay_one_time_purchase_10_handler, pattern="^pay_one_time_purchase_10$"))
bot.add_handler(CallbackQueryHandler(pay_one_time_purchase_15_handler, pattern="^pay_one_time_purchase_15$"))

# Обновляем ConversationHandler
conversation_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start), CallbackQueryHandler(button_handler)],
    states={
        CHOOSE_METHOD: [CallbackQueryHandler(choose_method_handler)],
        QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, question_handler)],
        SITUATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, situation_handler)],
        NUM_CARDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, num_cards_handler)],
        ENTER_CARDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_cards_handler)],
        ASK_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_question_handler)],
    },
    fallbacks=[
        CommandHandler("cancel", cancel),
        CallbackQueryHandler(start_over_handler, pattern="^start_over$"),
        CallbackQueryHandler(back_handler, pattern="^back$"),  # Обработчик кнопки "назад"
    ],
    per_message=False,
)

# Добавляем ConversationHandler
bot.add_handler(conversation_handler)

if __name__ == "__main__":
    print("Бот запущен...")
    bot.run_polling()