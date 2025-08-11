from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from config import Config
import logging
from database import (
    add_user, get_user, get_attempts, update_attempts,
    get_active_subscription, save_reading, add_subscription,
    execute_query
)
from tarot_interpreter import TarotInterpreter
from datetime import datetime
import html
import random
import asyncio
from telegram.error import BadRequest, RetryAfter
import difflib
import unidecode

CARDS_IMAGE = "cards_back.png"
PICK_CARDS = 9000

logger = logging.getLogger(__name__)

(
    CHOOSE_METHOD, QUESTION, SITUATION,
    NUM_CARDS, ENTER_CARDS, ASK_QUESTION
) = range(6)

TAROT_DECK = [
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

# --- Универсальная функция сопоставления ---

def normalize_card_name(name: str) -> str:
    name = name.strip().lower()
    name = name.replace("ё", "е")
    name = unidecode.unidecode(name)
    return name

def match_card_name(user_input, card_list, min_ratio=0.7):
    input_norm = normalize_card_name(user_input)
    deck_norm = [normalize_card_name(c) for c in card_list]
    if input_norm in deck_norm:
        idx = deck_norm.index(input_norm)
        return card_list[idx], True
    matches = difflib.get_close_matches(input_norm, deck_norm, n=1, cutoff=min_ratio)
    if matches:
        idx = deck_norm.index(matches[0])
        return card_list[idx], True
    return user_input, False

class BaseHandler:
    """Базовый класс с общими методами"""
    
    @staticmethod
    async def check_access(telegram_id: int) -> bool:
        """Проверка доступа пользователя к раскладам"""
        if await get_active_subscription(telegram_id):
            return True
        attempts = await get_attempts(telegram_id)
        return attempts > 0 if attempts is not None else False

    @staticmethod
    def create_keyboard(buttons: list, columns: int = 2) -> InlineKeyboardMarkup:
        """Создание inline клавиатуры с автоматическим распределением по колонкам"""
        keyboard = []
        row = []
        
        for i, (text, data) in enumerate(buttons, 1):
            row.append(InlineKeyboardButton(text, callback_data=data))
            if i % columns == 0 or i == len(buttons):
                keyboard.append(row)
                row = []
                
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    async def back_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик кнопки 'Назад' - всегда возвращает в главное меню"""
        query = update.callback_query
        await query.answer()
        context.user_data.clear()
        await StartHandler.start(update, context)
        return ConversationHandler.END

class CardMeaningsHandler(BaseHandler):
    """Обработчик значений карт Таро"""
    
    @staticmethod
    async def process_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка поискового запроса (с нечетким сопоставлением)"""
        search_query = update.message.text
        results = []
        for card in TAROT_DECK:
            matched, found = match_card_name(search_query, [card])
            if found:
                card_data = TarotInterpreter._card_meanings.get(card, {})
                results.append((card, card_data.get("category", "Неизвестно")))
        if not results:
            query_norm = normalize_card_name(search_query)
            for card in TAROT_DECK:
                if query_norm in normalize_card_name(card):
                    card_data = TarotInterpreter._card_meanings.get(card, {})
                    results.append((card, card_data.get("category", "Неизвестно")))
        if not results:
            await update.message.reply_text(
                "🔍 Карты не найдены. Попробуйте другой запрос.",
                reply_markup=BaseHandler.create_keyboard([("🔙 Назад", "card_meanings")])
            )
            return "SEARCH_CARD"

        if len(results) == 1:
            card_name, _ = results[0]
            meaning = await TarotInterpreter.get_card_meaning(card_name)
            buttons = [
                ("🔙 Назад к категориям", "card_meanings"),
                ("🏠 На главную", "start_over")
            ]
            await update.message.reply_text(
                meaning,
                reply_markup=BaseHandler.create_keyboard(buttons),
                parse_mode="Markdown"
            )
            return ConversationHandler.END

        buttons = [
            [InlineKeyboardButton(
                f"{card} ({category})",
                callback_data=f"meaning_{card}_0"
            )] for card, category in results
        ]
        buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="card_meanings")])

        await update.message.reply_text(
            f"🔍 Результаты поиска по запросу '{search_query}':",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return ConversationHandler.END

    @staticmethod
    async def show_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показ категорий карт"""
        query = update.callback_query
        await query.answer()
        
        buttons = [
            ("🃏 Старшие Арканы", "major_arcana"),
            ("🔥 Жезлы", "wands"),
            ("💧 Кубки", "cups"),
            ("⚔️ Мечи", "swords"),
            ("💰 Пентакли", "pentacles"),
            ("🔍 Поиск карты", "search_card"),
            ("🔙 На главную", "start_over")
        ]
        
        try:
            # Пытаемся отредактировать сообщение
            try:
                await query.edit_message_text(
                    text="📜 *Выберите категорию карт для просмотра значений:*",
                    reply_markup=BaseHandler.create_keyboard(buttons, columns=2),
                    parse_mode="Markdown"
                )
            except BadRequest as e:
                if "There is no text in the message to edit" in str(e):
                    # Если сообщение нельзя отредактировать, отправляем новое
                    await context.bot.send_message(
                        chat_id=query.from_user.id,
                        text="📜 *Выберите категорию карт для просмотра значений:*",
                        reply_markup=BaseHandler.create_keyboard(buttons, columns=2),
                        parse_mode="Markdown"
                    )
                else:
                    raise  # Пробрасываем другие ошибки BadRequest
        except Exception as e:
            logger.error(f"Error in show_categories: {e}", exc_info=True)
            try:
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text="⚠️ Произошла ошибка при загрузке категорий. Попробуйте позже.",
                    reply_markup=BaseHandler.create_keyboard([("🏠 На главную", "start_over")])
                )
            except Exception as send_error:
                logger.error(f"Failed to send error message: {send_error}")

    @staticmethod
    async def show_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
    
        # Проверяем загружены ли значения карт
        if not TarotInterpreter._card_meanings:
            await query.edit_message_text("🔄 Загружаю значения карт, попробуйте через 2-3 секунды...")
            await TarotInterpreter.load_meanings()
        
        category_map = {
            "major_arcana": "Старшие Арканы",
            "wands": "Жезлы",
            "cups": "Кубки",
            "swords": "Мечи",
            "pentacles": "Пентакли"
        }
        
        category_key = query.data
        category_name = category_map.get(category_key)
        
        if not category_name:
            await query.answer("Категория не найдена")
            return
        
        # Получаем и сортируем карты по порядку
        cards_in_category = [
            card for card in TAROT_DECK 
            if TarotInterpreter._card_meanings.get(card, {}).get("category") == category_name
        ]
        
        # Сортируем карты по порядку (Туз, 2-10, Паж, Рыцарь, Королева, Король)
        def sort_key(card):
            parts = card.split()
            if parts[0].isdigit():
                return (0, int(parts[0]))
            order = {"Туз": 1, "Паж": 11, "Рыцарь": 12, "Королева": 13, "Король": 14}
            return (0, order.get(parts[0], 99))
        
        cards_in_category.sort(key=sort_key)
        
        if not cards_in_category:
            await query.answer("Карты в этой категории не найдены")
            return
        
        # Создаем компактные названия для кнопок
        def get_short_name(full_name):
            # Для числовых карт оставляем только цифру
            if full_name[0].isdigit():
                return full_name[0]
            # Для придворных карт и Туза оставляем только название
            if full_name.startswith(("Туз", "Паж", "Рыцарь", "Королева", "Король")):
                return full_name.split()[0]
            return full_name
        
        # Создаем специальный формат для Пентаклей
        if category_key == "pentacles":
            buttons = []
            # Числовые карты (1-10)
            for i in range(0, 10, 2):
                row = []
                card1 = cards_in_category[i]
                row.append(InlineKeyboardButton(
                    get_short_name(card1),
                    callback_data=f"meaning_{card1}_0"
                ))
                if i+1 < 10:
                    card2 = cards_in_category[i+1]
                    row.append(InlineKeyboardButton(
                        get_short_name(card2),
                        callback_data=f"meaning_{card2}_0"
                    ))
                buttons.append(row)
            
            # Придворные карты
            court_cards = cards_in_category[10:]
            for i in range(0, len(court_cards), 2):
                row = []
                card1 = court_cards[i]
                row.append(InlineKeyboardButton(
                    get_short_name(card1),
                    callback_data=f"meaning_{card1}_0"
                ))
                if i+1 < len(court_cards):
                    card2 = court_cards[i+1]
                    row.append(InlineKeyboardButton(
                        get_short_name(card2),
                        callback_data=f"meaning_{card2}_0"
                    ))
                buttons.append(row)
        else:
            # Стандартный формат для других категорий
            buttons = []
            for i in range(0, len(cards_in_category), 2):
                row = []
                # Первая кнопка в строке
                card1 = cards_in_category[i]
                row.append(InlineKeyboardButton(
                    get_short_name(card1), 
                    callback_data=f"meaning_{card1}_0"
                ))
                
                # Вторая кнопка в строке (если есть)
                if i+1 < len(cards_in_category):
                    card2 = cards_in_category[i+1]
                    row.append(InlineKeyboardButton(
                        get_short_name(card2),
                        callback_data=f"meaning_{card2}_0"
                    ))
                
                buttons.append(row)
        
        # Добавляем кнопку "Назад"
        buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="card_meanings")])
        
        try:
            await query.edit_message_text(
                text=f"🃏 *{category_name}* - выберите карту:\n",
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Error showing cards: {e}")
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=f"🃏 *{category_name}* - выберите карту:",
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode="Markdown"
            )

    @staticmethod
    async def show_meaning(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отображение значения карты с переключением"""
        query = update.callback_query
        await query.answer()
        
        try:
            data = query.data.split("_")
            card_name = "_".join(data[1:-1])
            is_reversed = data[-1] == "1"
            
            card_data = TarotInterpreter._card_meanings.get(card_name, {})
            if not card_data:
                await query.answer("Информация о карте не найдена")
                return
            
            # Формируем текст
            position = "Перевернутое" if is_reversed else "Прямое"
            text = (
                f"✨ *{card_name}* ({position} положение)\n"
                f"🏷️ Категория: {card_data.get('category', '?')}\n\n"
                f"📖 *Значение:*\n{card_data.get('meaning', 'Нет данных')}\n\n"
                f"🔮 *{position} положение:*\n"
                f"{card_data.get('reversed' if is_reversed else 'upright', 'Нет данных')}"
            )
            
            # Создаем кнопки
            buttons = [
                [
                    InlineKeyboardButton(
                        "🔄 Показать " + ("прямое" if is_reversed else "перевернутое"),
                        callback_data=f"meaning_{card_name}_{1 if not is_reversed else 0}"
                    )
                ],
                [
                    InlineKeyboardButton("🏠 На главную", callback_data="start_over")
                ]
            ]
            
            await query.edit_message_text(
                text=text,
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Error showing card meaning: {e}")
            await query.edit_message_text(
                text="⚠️ Ошибка загрузки значения карты",
                reply_markup=BaseHandler.create_keyboard([("🔙 Назад", "card_meanings")])
            )

    @staticmethod
    async def start_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало поиска карты"""
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            text="🔍 *Введите название карты для поиска:*",
            reply_markup=BaseHandler.create_keyboard([("🔙 Отмена", "card_meanings")]),
            parse_mode="Markdown"
        )
        return "SEARCH_CARD"

    @staticmethod
    async def process_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка поискового запроса"""
        search_query = update.message.text
        results = await TarotInterpreter.search_cards(search_query)
        
        if not results:
            await update.message.reply_text(
                "🔍 Карты не найдены. Попробуйте другой запрос.",
                reply_markup=BaseHandler.create_keyboard([("🔙 Назад", "card_meanings")])
            )
            return "SEARCH_CARD"
        
        if len(results) == 1:
            card_name, _ = results[0]
            meaning = await TarotInterpreter.get_card_meaning(card_name)
            buttons = [
                ("🔙 Назад к категориям", "card_meanings"),
                ("🏠 На главную", "start_over")
            ]
            await update.message.reply_text(
                meaning,
                reply_markup=BaseHandler.create_keyboard(buttons),
                parse_mode="Markdown"
            )
            return ConversationHandler.END
        
        buttons = [
            [InlineKeyboardButton(
                f"{card} ({category})", 
                callback_data=f"meaning_{card}_0"
            )] for card, category in results
        ]
        buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="card_meanings")])
        
        await update.message.reply_text(
            f"🔍 Результаты поиска по запросу '{search_query}':",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return ConversationHandler.END

    @staticmethod
    async def cancel_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отмена поиска"""
        await update.message.reply_text(
            "Поиск отменен.",
            reply_markup=BaseHandler.create_keyboard([("🏠 На главную", "start_over")])
        )
        return ConversationHandler.END

class StartHandler(BaseHandler):
    @staticmethod
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        referrer_id = None
        # Проверяем аргумент (start с id)
        if update.message and update.message.text:
            args = update.message.text.split()
            if len(args) > 1 and args[1].isdigit():
                if int(args[1]) != user.id:   # запрет самореферала
                    referrer_id = int(args[1])
        # Передаем context для отправки бонуса-приглашателю
        await add_user(user.id, user.username, referrer_id, context=context)
        """Обработка команды /start"""
        try:
            user = update.effective_user
            await add_user(user.id, user.username)

            buttons = [
                ("🃏 Дневной расклад", "daily_reading"),
                ("🃏 Недельный расклад", "weekly_reading"),
                ("🃏 Запросить расклад", "request_reading"),
                ("💎 Подписка", "subscription"),
                ("📜 Значения карт", "card_meanings"),
                ("📞 Консультация", "consultation"),
                ("👫 Пригласить друга", "referral"),
                ("ℹ️ Помощь", "help") 
            ]
            
            await context.bot.send_photo(
                chat_id=user.id,
                photo=Config.WELCOME_IMAGE_URL,
                caption="🌟 *Без лишней магии — только ясность!*\n\n"
"Здесь можно быстро навести порядок в мыслях и получить честный совет — карты не льстят и не пугают, а помогают увидеть суть.\n\n"
"Выбери, что тебе нужно прямо сейчас:\n",
                parse_mode="Markdown",
                reply_markup=BaseHandler.create_keyboard(buttons)
            )
        except Exception as e:
            logger.error(f"Start error: {str(e)}")
            await update.message.reply_text("⚠️ Произошла ошибка. Попробуйте позже.")

    @staticmethod
    async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды помощи"""
        await HelpHandler.show_help(update, context)

class HelpHandler(BaseHandler):
    """Обработчик помощи и информации о боте"""
    
    @staticmethod
    async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показ справочной информации с устойчивой обработкой ошибок"""
        query = update.callback_query
        chat_id = update.effective_chat.id
     
        help_text = (
            "📚 <b>Навести порядок в мыслях — просто!</b>\n\n"
            "🔮 <b>Что умеет бот:</b>\n"
            "1. 🃏 <b>Расклад</b> — получи честный разбор твоей ситуации по картам\n"
            "2. 💎 <b>Подписка</b> — неограниченный доступ к раскладам, когда захочешь\n"
            "3. 📜 <b>Значения карт</b> — полная база по каждой карте, без лишних слов\n"
            "4. 📞 <b>Консультация</b> — персональный разбор от опытного таролога\n"
            "5. 👥 <b>Пригласить друга</b> — получай бонусы за рекомендации\n\n"
            "❓ <b>Как использовать:</b>\n"
            "- Выбери нужную функцию в меню\n"
            "- Следуй подсказкам — всё чётко и просто\n"
            "- Для отмены любого действия — /cancel\n\n"
            f"📩 <b>Связаться с поддержкой:</b> @{Config.ADMIN_USERNAME}\n"
            "🕒 <b>Доступен всегда — хоть ночью, хоть днём</b>"
        )
     
        buttons = [
            ("🃏 Попробовать расклад", "request_reading"),
            ("💎 Подписка", "subscription"),
            ("📞 Консультация", "consultation"),
            ("🏠 На главную", "start_over")
        ]
        keyboard = BaseHandler.create_keyboard(buttons, columns=2)
     
        try:
            if query:
                await query.answer()
     
                try:
                    # Пытаемся отредактировать, если есть текст
                    if query.message.text:
                        await query.edit_message_text(
                            text=help_text,
                            reply_markup=keyboard,
                            parse_mode="HTML"
                        )
                    else:
                        raise BadRequest("no text to edit")
                except BadRequest as e:
                    logger.warning(f"Can't edit help message: {e}")
                    # Отправляем новое сообщение, если редактирование не удалось
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=help_text,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
            else:
                # Если это обычное сообщение (не callback)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=help_text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
     
        except Exception as e:
            logger.error(f"Error in show_help: {e}")
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ Не удалось загрузить справочную информацию. Попробуйте позже.",
                reply_markup=BaseHandler.create_keyboard([("🏠 На главную", "start_over")])
            )

class ConsultationHandler(BaseHandler):
    """Обработчик консультаций"""
    
    @staticmethod
    async def start_consultation(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало процесса заказа консультации"""
        query = update.callback_query
        await query.answer()
       
        buttons = [
            ("📞 Заказать консультацию", "confirm_consultation"),
            ("🔙 Назад", "start_over")
        ]
       
        text = (
        "🃏 <b>Разберём твою ситуацию по картам?</b> 🤔\n\n"
        "Это не эзотерика, а <u>инструмент для ясности</u>. Как совет умного друга, только карты не врут и не льстят.\n\n"
        "🔥 <b>Что будет:</b>\n"
        "• Разберём 3-4 вопроса, которые тебя гложут\n"
        "• На каждый — в среднем 25 минут чёткого анализа (без воды)\n"
        "• Никакой «судьбы» — только факты и варианты решений\n\n"
        "💡 <b>Что получишь:</b>\n"
        "→ Объективный взгляд на ситуацию\n"
        "→ Конкретные шаги, а не туманные прогнозы\n"
        "→ Никакой мистики — только логика и психология\n\n"
        "⏱ <b>Время:</b> 60-80 минут — как хороший подкаст, но с фокусом на тебя\n"
        "💸 <b>Цена:</b> 600₽ — дешевле, чем психолог, и быстрее, чем самокопание\n\n"
        "📲 <b>Если хочешь разложить всё по полочкам — жми «Заказать»!</b>\n"
    )
       
        try:
            if query.message and query.message.text:
                await query.edit_message_text(
                    text=text,
                    reply_markup=BaseHandler.create_keyboard(buttons),
                    parse_mode="HTML"
                )
            else:
                # Нет текста в оригинальном сообщении — отправляем новое
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text=text,
                    reply_markup=BaseHandler.create_keyboard(buttons),
                    parse_mode="HTML"
                )
        except BadRequest as e:
            # Логируем и пересылаем как новое сообщение в случае других ошибок
            logger.error(f"Error editing message: {e}")
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=text,
                reply_markup=BaseHandler.create_keyboard(buttons),
                parse_mode="HTML"
            )


    @staticmethod
    async def confirm_consultation(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Подтверждение заказа консультации"""
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            "✍️ *Опишите ваш вопрос или ситуацию*\n\n"
            "Напишите подробно, что вас беспокоит и на какой вопрос вы хотели бы получить ответ.\n\n"
            "После отправки сообщения с вами свяжется наш таролог.",
            reply_markup=BaseHandler.create_keyboard([("🔙 Отмена", "start_over")]),
            parse_mode="Markdown"
        )
        return "GET_CONSULTATION_DETAILS"

    @staticmethod
    async def get_consultation_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Получение деталей консультации"""
        try:
            user = update.effective_user
            question = update.message.text
            
            # Сохраняем вопрос в user_data
            context.user_data['consultation_question'] = question
            
            # Отправляем уведомление админу
            question_html = html.escape(question)
            admin_text = (
                "📞 <b>Новый запрос консультации</b>\n\n"
                f"👤 Пользователь: @{html.escape(user.username) if user.username else 'нет username'} (ID: {user.id})\n"
                f"❓ Вопрос:\n{question_html}\n\n"
                f"Свяжитесь с пользователем для оформления."
            )
            
            await context.bot.send_message(
                chat_id=Config.ADMIN_CHAT_ID,
                text=admin_text,
                parse_mode="HTML"
            )
            
            
            # Подтверждение пользователю
            await update.message.reply_text(
                "✅ Ваш запрос на консультацию отправлен!\n\n"
                "Наш таролог свяжется с вами в ближайшее время для уточнения деталей.",
                reply_markup=BaseHandler.create_keyboard([("🏠 На главную", "start_over")])
            )
            
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Error in consultation: {e}")
            await update.message.reply_text(
                "⚠️ Произошла ошибка при отправке запроса. Попробуйте позже.",
                reply_markup=BaseHandler.create_keyboard([("🏠 На главную", "start_over")])
            )
            return ConversationHandler.END

    @staticmethod
    async def cancel_consultation(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отмена консультации"""
        await update.message.reply_text(
            "❌ Заказ консультации отменен.",
            reply_markup=BaseHandler.create_keyboard([("🏠 На главную", "start_over")])
        )
        return ConversationHandler.END

class SubscriptionHandler(BaseHandler):
    """Обработчики подписки и оплаты"""
    
    SUBSCRIPTION_TYPES = {
        "monthly": (349, 30, "💎 Месячная подписка"),
        "5": (99, 0, "🛒 5 попыток"),
        "10": (149, 0, "🛒 10 попыток"),
        "15": (229, 0, "🛒 15 попыток")
    }

    @staticmethod
    async def notify_admin(user_id: int, username: str, sub_type: str, context: ContextTypes.DEFAULT_TYPE):
        """Отправка уведомления админу о выборе подписки"""
        try:
            sub_info = SubscriptionHandler.SUBSCRIPTION_TYPES.get(sub_type)
            if not sub_info:
                logger.error(f"Unknown subscription type: {sub_type}")
                return
                
            price, days, name = sub_info
            
            admin_text = (
                "🛒 *Новый запрос подписки*\n\n"
                f"👤 Пользователь: @{username if username else 'нет username'} (ID: {user_id})\n"
                f"📝 Тип подписки: {name}\n"
                f"💳 Стоимость: {price}₽\n"
                f"⏳ Срок: {days if days > 0 else 'разовые'} дней\n\n"
                f"Свяжитесь с пользователем для оформления."
            )
            
            await context.bot.send_message(
                chat_id=Config.ADMIN_CHAT_ID,
                text=admin_text,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Error sending admin notification: {e}")

    @staticmethod
    async def show_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Улучшенный обработчик подписки с полным логгированием"""
        try:
            query = update.callback_query
            await query.answer()
            
            user_id = query.from_user.id
            logger.info(f"User {user_id} opened subscriptions menu")
    
            # Получаем данные с обработкой возможных ошибок
            try:
                attempts = await get_attempts(user_id)
                has_sub = bool(await get_active_subscription(user_id))
                logger.info(f"User data loaded - attempts: {attempts}, has_sub: {has_sub}")
            except Exception as db_error:
                logger.error(f"Database error for user {user_id}: {db_error}")
                raise
    
            # Формируем текст сообщения
            status = "активна ✅" if has_sub else "неактивна ❌"
            text = (
                f"💎 <b>Статус подписки:</b>: {status}\n"
                f"🃏 <b>Осталось попыток:</b>: {attempts if attempts is not None else 0}\n\n"
                "<b>Доступные варианты:</b>\n"
                "1.💎 <b>Месяц полной ясности</b> — все расклады без ограничений за 349₽\n"
                "2.🛒 <b>Разовые пакеты</b> — бери столько попыток, сколько нужно\n\n"

                "Решай сам — глубоко и по делу или по чуть-чуть, но всегда по фактам."
            )
    
            # Создаем кнопки
            buttons = [
                ("💎 Месячная (349₽)", "sub_monthly"),
                ("🛒 5 попыток (99₽)", "sub_5"),
                ("🛒 10 попыток (149₽)", "sub_10"),
                ("🛒 15 попыток (229₽)", "sub_15"),
                ("🔙 На главную", "start_over")
            ]
    
            # Пытаемся обновить сообщение
            try:
                await query.edit_message_text(
                    text=text,
                    reply_markup=BaseHandler.create_keyboard(buttons),
                    parse_mode="HTML"
                )
                logger.info(f"Successfully updated menu for user {user_id}")
            except BadRequest as e:
                logger.warning(f"Message edit failed for user {user_id}, sending new: {e}")
                await context.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    reply_markup=BaseHandler.create_keyboard(buttons),
                    parse_mode="HTML"
                )
    
        except Exception as e:
            logger.error(f"Critical error in show_subscriptions: {e}", exc_info=True)
            error_text = "⚠️ Произошла критическая ошибка. Пожалуйста, попробуйте позже."
            try:
                await query.edit_message_text(text=error_text)
            except:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=error_text
                )

    @staticmethod
    async def handle_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик выбора типа подписки"""
        try:
            query = update.callback_query
            await query.answer()
            
            user = query.from_user
            sub_type = query.data.replace("sub_", "")
            
            # Получаем информацию о подписке
            sub_info = SubscriptionHandler.SUBSCRIPTION_TYPES.get(sub_type)
            if not sub_info:
                raise ValueError(f"Unknown subscription type: {sub_type}")
                
            price, days, name = sub_info
    
            # Формируем сообщение для пользователя
            text = (
                f"📝 <b>Вы выбрали: {name}</b>\n\n"
                f"💳 <b>Стоимость:</b> {price}₽\n\n"
                f"Для оформления подписки свяжитесь с @{Config.ADMIN_USERNAME}\n"
                "и укажите выбранный вариант."
            )
    
            buttons = [
                ("🔙 Назад", "subscription")
            ]
    
            # Отправляем сообщение пользователю
            await query.edit_message_text(
                text=text,
                reply_markup=BaseHandler.create_keyboard(buttons),
                parse_mode="HTML"
            )
            
            # Уведомляем админа
            await SubscriptionHandler.notify_admin(
                user_id=user.id,
                username=user.username,
                sub_type=sub_type,
                context=context
            )
    
        except Exception as e:
            logger.error(f"Error in handle_subscription: {e}", exc_info=True)
            error_text = "⚠️ Ошибка при обработке подписки. Попробуйте позже."
            try:
                await query.edit_message_text(text=error_text)
            except:
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text=error_text
                )

class ReadingHandler(BaseHandler):
    """Обработчики раскладов Таро"""
    
    @staticmethod
    async def daily_reading(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id

        # Проверка доступа — есть ли подписка или попытки
        if not await BaseHandler.check_access(user_id):
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ У вас закончились бесплатные попытки.\n"
                     "Приобретите подписку или попытки.",
                reply_markup=BaseHandler.create_keyboard([
                    ("💎 Подписка", "subscription"),
                    ("🔙 На главную", "start_over")
                ])
            )
            return ConversationHandler.END

        # Списываем попытку (даже если есть подписка, чтобы не было ухода в минус)
        await update_attempts(user_id, -1)

        reading = await TarotInterpreter.generate_interpretation("Что меня ждет сегодня?", "", [])
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✨ Ваш дневной расклад:\n\n{reading}"
        )
        return ConversationHandler.END

    @staticmethod
    async def weekly_reading(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id

        # Проверка доступа — есть ли подписка или попытки
        if not await BaseHandler.check_access(user_id):
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ У вас закончились бесплатные попытки.\n"
                     "Приобретите подписку или попытки.",
                reply_markup=BaseHandler.create_keyboard([
                    ("💎 Подписка", "subscription"),
                    ("🔙 На главную", "start_over")
                ])
            )
            return ConversationHandler.END

        # Списываем попытку (даже если есть подписка, чтобы не было ухода в минус)
        await update_attempts(user_id, -1)

        reading = await TarotInterpreter.generate_interpretation("Что меня ждет на этой неделе?", "", [])
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✨ Ваш недельный расклад:\n\n{reading}"
        )
        return ConversationHandler.END

    @staticmethod
    async def begin_reading(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало процесса расклада"""
        query = update.callback_query
        await query.answer()
    
        if not await BaseHandler.check_access(query.from_user.id):
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text="❌ У вас закончились бесплатные попытки.\n"
                     "Приобретите подписку или попытки.",
                reply_markup=BaseHandler.create_keyboard([
                    ("💎 Подписка", "subscription"),
                    ("🔙 На главную", "start_over")
                ])
            )
            return ConversationHandler.END
    
        context.user_data.clear()
        
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text="🔮 *Сформулируй свой вопрос — чётко и по делу*\n\n"
                 "Пример: «Какие реальные шаги помогут мне улучшить отношения?»\n"
                 "Чем конкретнее вопрос, тем полезнее ответ.\n\n",
            parse_mode="Markdown"
        )
        return QUESTION

    @staticmethod
    async def process_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка вопроса пользователя"""
        if update.message.text.lower() == "назад":
            await StartHandler.start(update, context)
            return ConversationHandler.END
            
        context.user_data["question"] = update.message.text
            
        await update.message.reply_text(
            "📖 *Опишите ситуацию подробнее*\n\n"
            "Это необязательно, но поможет сделать интерпретацию точнее.\n"
            "Пример: «Мы в ссоре уже 2 недели, не знаю как помириться»",
            parse_mode="Markdown",
            reply_markup=BaseHandler.create_keyboard([("🔙 На главную", "back")])
        )
        return SITUATION

    @staticmethod
    async def process_situation(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка описания ситуации"""
        if update.message.text.lower() == "назад":
            await StartHandler.start(update, context)
            return ConversationHandler.END
            
        context.user_data["situation"] = update.message.text
            
        await update.message.reply_text(
            "🃏 *Сколько карт вы хотите вытянуть?*\n\n"
            "Введите число от 1 до 5:",
            parse_mode="Markdown",
            reply_markup=BaseHandler.create_keyboard([("🔙 На главную", "back")])
        )
        return NUM_CARDS
    
    @staticmethod
    async def process_num_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка количества карт"""
        if update.message.text.lower() == "назад":
            await StartHandler.start(update, context)
            return ConversationHandler.END
            
        try:
            num = int(update.message.text)
            if not 1 <= num <= 5:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Введите число от 1 до 5")
            return NUM_CARDS
            
        context.user_data["num_cards"] = num
            
        buttons = [
            ("🎲 Автоматически", "random_cards"),
            ("🃏 Написать вручную", "manual_cards"),
            ("👁️ Выбрать карты", "pick_cards"),
            ("🔙 На главную", "start_over")
        ]
            
        await update.message.reply_text(
            "🃏 *Как выбрать карты?*",
            reply_markup=BaseHandler.create_keyboard(buttons),
            parse_mode="Markdown"
        )
        return CHOOSE_METHOD



    @staticmethod
    async def choose_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка выбора метода"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "random_cards":
            num = context.user_data["num_cards"]
            selected = random.sample(TAROT_DECK, num)
            context.user_data["selected_cards"] = selected
            
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=f"✨ Выпали карты: {', '.join(selected)}"
            )
            return await ReadingHandler.finish_reading(update, context)
            
        elif query.data == "manual_cards":
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text="✍️ Введите названия карт через запятую:\n"
                     "Пример: Шут, Императрица, Повешенный"
            )
            return ENTER_CARDS

        elif query.data == "pick_cards":
            return await ReadingHandler.pick_cards_start(update, context)
            
        elif query.data == "back":
            return await BaseHandler.back_handler(update, context)

    @staticmethod
    async def pick_cards_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старт выбора карт по рубашкам"""
        query = update.callback_query
        await query.answer()
        num_cards = context.user_data.get("num_cards", 1)
        # 6 случайных карт для выбора
        deck = random.sample(TAROT_DECK, 6)
        context.user_data["pick_deck"] = deck
        context.user_data["picked_cards"] = []
    
        keyboard = [
            [InlineKeyboardButton(f"🃏 {i+1}", callback_data=f"pick_card_{i}")]
            for i in range(6)
        ]
        await context.bot.send_photo(
            chat_id=query.from_user.id,
            photo=CARDS_IMAGE,
            caption=f"Выберите карту №1 из {num_cards}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return PICK_CARDS

    @staticmethod
    async def pick_cards_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка выбора одной карты из 6"""
        query = update.callback_query
        await query.answer()
        num_cards = context.user_data.get("num_cards", 1)
        deck = context.user_data["pick_deck"]
        picked = context.user_data["picked_cards"]
    
        idx = int(query.data.split("_")[-1])
        card = deck[idx]
        if card in picked:
            await query.answer("Эту карту вы уже выбрали!", show_alert=True)
            return PICK_CARDS
        picked.append(card)
    
        if len(picked) < num_cards:
            # Обновить кнопки: уже выбранные – неактивны
            keyboard = []
            for i, c in enumerate(deck):
                text = f"✅ {i+1}" if c in picked else f"🃏 {i+1}"
                button = (
                    InlineKeyboardButton(text, callback_data="picked_ignore")
                    if c in picked else
                    InlineKeyboardButton(text, callback_data=f"pick_card_{i}")
                )
                keyboard.append([button])
            await query.edit_message_caption(
                caption=f"Выберите карту №{len(picked)+1} из {num_cards}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return PICK_CARDS
        else:
            context.user_data["selected_cards"] = picked
            await query.edit_message_caption(
                caption=f"✨ Вы выбрали: {', '.join(picked)}"
            )
            return await ReadingHandler.finish_reading(update, context)

    @staticmethod
    async def process_manual_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка ручного ввода карт"""
        if update.message.text.lower() == "назад":
            await StartHandler.start(update, context)
            return ConversationHandler.END
            
        input_cards = [c.strip() for c in update.message.text.split(",")]
        valid_cards = []
        invalid = []
            
        for card in input_cards:
            if card in TAROT_DECK:
                valid_cards.append(card)
            else:
                invalid.append(card)
                    
        if invalid:
            await update.message.reply_text(
                f"❌ Неизвестные карты: {', '.join(invalid)}\n"
                "Попробуйте еще раз:"
            )
            return ENTER_CARDS
                
        context.user_data["selected_cards"] = valid_cards
        return await ReadingHandler.finish_reading(update, context)

    @staticmethod
    async def finish_reading(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Завершение расклада и показ результата"""
        user_id = update.effective_user.id
        question = context.user_data.get("question", "")
        situation = context.user_data.get("situation", "")
        cards = context.user_data.get("selected_cards", [])
        
        if not cards:
            logger.error("No cards selected")
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ Произошла ошибка при обработке карт"
            )
            return ConversationHandler.END
        
        try:
            processing_msg = await context.bot.send_message(
                chat_id=user_id,
                text="🔮 Интерпретирую карты..."
            )
            
            interpretation = await asyncio.wait_for(
                TarotInterpreter.generate_interpretation(question, situation, cards),
                timeout=30
            )
            
            if not interpretation:
                raise ValueError("Empty interpretation received")
            
            await save_reading(user_id, question, situation, cards, interpretation)
            await update_attempts(user_id, -1)
            
            result = (
                f"✨ *Ваш расклад*\n\n"
                f"❓ Вопрос: {question}\n"
                f"🃏 Карты: {', '.join(cards)}\n\n"
                f"📖 *Интерпретация:*\n{interpretation}\n\n"
                f"💎 Хотите более подробный разбор? Закажите консультацию!"
            )
            
            buttons = [
                ("📞 Консультация", "consultation"),
                ("🔄 Новый расклад", "request_reading"),
                ("🏠 На главную", "start_over")
            ]
            
            await processing_msg.delete()
            await context.bot.send_message(
                chat_id=user_id,
                text=result,
                reply_markup=BaseHandler.create_keyboard(buttons),
                parse_mode="Markdown"
            )
            
        except asyncio.TimeoutError:
            logger.error("Timeout generating interpretation")
            await context.bot.send_message(
                chat_id=user_id,
                text="⏳ Время генерации истекло. Попробуйте позже."
            )
        except Exception as e:
            logger.error(f"Error in finish_reading: {str(e)}")
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ Произошла ошибка при генерации интерпретации. Попробуйте позже."
            )
        
        return ConversationHandler.END

    @staticmethod
    async def cancel_reading(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отмена расклада"""
        context.user_data.clear()
        await update.message.reply_text(
            "❌ Расклад отменен.",
            reply_markup=BaseHandler.create_keyboard([("🏠 На главную", "start_over")])
        )
        return ConversationHandler.END

    @staticmethod
    async def process_manual_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка ручного ввода карт с проверкой количества и нечетким сопоставлением"""
        if update.message.text.lower() == "назад":
            await StartHandler.start(update, context)
            return ConversationHandler.END
    
        num_needed = context.user_data.get("num_cards", 1)
        input_cards = [c.strip() for c in update.message.text.split(",")]
        valid_cards = []
        invalid = []
    
        for card in input_cards:
            matched, found = match_card_name(card, TAROT_DECK)
            if found:
                valid_cards.append(matched)
            else:
                invalid.append(card)
    
        # Проверка на количество карт
        n_valid = len(valid_cards)
        if n_valid != num_needed or invalid:
            lines = []
            if n_valid < num_needed:
                lines.append(f"❗️ Вы ввели {n_valid} карты, а нужно {num_needed}.")
                if n_valid > 0:
                    lines.append(f"✅ Принятые карты: {', '.join(valid_cards)}")
            elif n_valid > num_needed:
                lines.append(f"❗️ Вы ввели {n_valid} карт, а нужно {num_needed}.")
                lines.append(f"✅ Принятые карты: {', '.join(valid_cards[:num_needed])}")
    
            if invalid:
                lines.append(f"❌ Неизвестные карты: {', '.join(invalid)}")
    
            lines.append(f"Пожалуйста, введите ровно {num_needed} карты через запятую.")
            await update.message.reply_text("\n".join(lines))
            return ENTER_CARDS
    
        context.user_data["selected_cards"] = valid_cards
        return await ReadingHandler.finish_reading(update, context)

class ReferralHandler(BaseHandler):
    @staticmethod
    async def invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        username = update.effective_user.username
        bot_username = context.bot.username

        referral_link = f"https://t.me/{bot_username}?start={user_id}"

        count = await execute_query(
            "SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,), fetch_one=True
        )
        count = count[0] if count else 0

        bonuses = count

        share_buttons = [
            [
                InlineKeyboardButton("📲 Поделиться", url=f"https://t.me/share/url?url={referral_link}&text=Присоединяйся к боту Таро — получи бесплатную попытку!")
            ],
            [InlineKeyboardButton("🏠 На главную", callback_data="start_over")]
        ]

        text = (
            f"👫 <b>Твоя реферальная ссылка:</b>\n"
            f"<code>{referral_link}</code>\n\n"
            f"🎁 Бонусов на счету: <b>{bonuses}</b>\n\n"
            "За каждого друга — +1 попытка к твоим раскладам! Просто поделись ссылкой: быстро, удобно, по-дружески. Чем больше друзей — тем больше шансов разобрать важное."
        )
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(share_buttons)
        )


class AdminHandler(BaseHandler):
    """Обработчики для администратора"""
    
    @staticmethod
    async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Меню администрирования"""
        user_id = str(update.effective_user.id)
        admin_id = str(Config.ADMIN_CHAT_ID)
    
        buttons = [
            ("👤 Управление пользователями", "admin_users"),
            ("📊 Аналитика", "admin_analytics"),
            ("📢 Рассылка", "admin_broadcast"),
            ("🔙 На главную", "start_over")
        ]
    
        # Проверяем, как пришёл запрос
        if hasattr(update, "message") and update.message:
            if user_id != admin_id:
                await update.message.reply_text("❌ Доступ запрещен")
                return
            await update.message.reply_text(
                "⚙️ *Админ-панель*",
                reply_markup=BaseHandler.create_keyboard(buttons),
                parse_mode="Markdown"
            )
        elif hasattr(update, "callback_query") and update.callback_query:
            if user_id != admin_id:
                await update.callback_query.answer("❌ Доступ запрещен", show_alert=True)
                return
            await update.callback_query.edit_message_text(
                "⚙️ *Админ-панель*",
                reply_markup=BaseHandler.create_keyboard(buttons),
                parse_mode="Markdown"
            )
        else:
            # На всякий случай: неизвестный тип апдейта
            logger.warning("admin_menu: Unknown update type")


    @staticmethod
    async def admin_broadcast_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Меню рассылки"""
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            "📢 Отправьте текст рассылки или фото с подписью. Можно приложить изображение.",
            reply_markup=BaseHandler.create_keyboard([("🔙 Назад", "start_over")])
        )
        return "ADMIN_BROADCAST"

    @staticmethod
    async def process_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
        import asyncio
        from telegram.error import RetryAfter
    
        text = update.message.text or (update.message.caption if update.message.caption else "")
        photo = update.message.photo[-1].file_id if update.message.photo else None
        users = await execute_query("SELECT telegram_id FROM users")
        errors = 0
        sent = 0
    
        for idx, (user_id,) in enumerate(users):
            try:
                if photo:
                    await context.bot.send_photo(
                        chat_id=user_id,
                        photo=photo,
                        caption=text if text else None
                    )
                else:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=text
                    )
                sent += 1
            except RetryAfter as e:
                logger.warning(f"FloodWait: сплю {e.retry_after} секунд...")
                await asyncio.sleep(e.retry_after)
                continue
            except Exception as e:
                errors += 1
                logger.error(f"Не удалось отправить сообщение {user_id}: {e}")
            await asyncio.sleep(1.2)  # Задержка между отправкой
    
        await update.message.reply_text(
            f"✅ Рассылка завершена!\n\n"
            f"Успешно: {sent}\n"
            f"Ошибок: {errors}",
            reply_markup=BaseHandler.create_keyboard([("🔙 В меню", "start_over")])
        )
        return ConversationHandler.END

    @staticmethod
    async def admin_users_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Меню управления пользователями"""
        query = update.callback_query
        await query.answer()
        
        buttons = [
            ("➕ Добавить попытки", "admin_add_attempts"),
            ("➖ Удалить попытки", "admin_remove_attempts"),
            ("💎 Добавить подписку", "admin_add_sub"),
            ("📋 Список пользователей", "admin_list_users"),
            ("🔙 Назад", "start_over")
        ]
        
        await query.edit_message_text(
            "👥 *Управление пользователями*",
            reply_markup=BaseHandler.create_keyboard(buttons, columns=2),
            parse_mode="Markdown"
        )

    @staticmethod
    async def admin_request_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Запрос ID пользователя"""
        query = update.callback_query
        await query.answer()
        
        action = query.data.replace("admin_", "")
        context.user_data["admin_action"] = action
        
        await query.edit_message_text(
            "📝 Введите ID пользователя:",
            reply_markup=BaseHandler.create_keyboard([("🔙 Назад", "admin_users")])
        )
        return "ADMIN_GET_USER_ID"

    @staticmethod
    async def admin_get_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Получение ID пользователя"""
        try:
            user_id = int(update.message.text)
            context.user_data["admin_user_id"] = user_id
            
            action = context.user_data["admin_action"]
            
            if action in ["add_attempts", "remove_attempts"]:
                await update.message.reply_text(
                    "🔢 Введите количество попыток:",
                    reply_markup=BaseHandler.create_keyboard([("🔙 Назад", "admin_users")])
                )
                return "ADMIN_GET_ATTEMPTS"
            elif action == "add_sub":
                buttons = [
                    ("💎 Месячная (30 дней)", "admin_sub_monthly"),
                    ("🔙 Назад", "admin_users")
                ]
                await update.message.reply_text(
                    "📅 Выберите тип подписки:",
                    reply_markup=BaseHandler.create_keyboard(buttons)
                )
                return "ADMIN_GET_SUB_TYPE"

        except ValueError:
            await update.message.reply_text("❌ Неверный ID пользователя. Введите число:")
            return "ADMIN_GET_USER_ID"

    @staticmethod
    async def admin_get_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Получение количества попыток"""
        try:
            attempts = int(update.message.text)
            user_id = context.user_data["admin_user_id"]
            action = context.user_data["admin_action"]
            
            if action == "add_attempts":
                await update_attempts(user_id, attempts)
                msg = f"✅ Пользователю {user_id} добавлено {attempts} попыток"
            else:
                await update_attempts(user_id, -attempts)
                msg = f"✅ У пользователя {user_id} списано {attempts} попыток"
                
            await update.message.reply_text(
                msg,
                reply_markup=BaseHandler.create_keyboard([("🔙 В меню", "admin_users")])
            )
            
        except ValueError:
            await update.message.reply_text("❌ Введите число:")
            return "ADMIN_GET_ATTEMPTS"
            
        return ConversationHandler.END

    @staticmethod
    async def admin_add_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Добавление подписки"""
        query = update.callback_query
        await query.answer()
        
        sub_type = query.data.replace("admin_sub_", "")
        user_id = context.user_data["admin_user_id"]
        
        if sub_type == "monthly":
            await add_subscription(user_id, "premium", 30)
            msg = f"✅ Пользователю {user_id} добавлена месячная подписка"
        else:
            msg = "❌ Неизвестный тип подписки"
            
        await query.edit_message_text(
            msg,
            reply_markup=BaseHandler.create_keyboard([("🔙 В меню", "admin_users")])
        )
        return ConversationHandler.END

    @staticmethod
    async def admin_list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Список пользователей с актуальными данными о попытках"""
        query = update.callback_query
        await query.answer()
        
        try:
            users = await execute_query("""
                SELECT 
                    u.telegram_id, 
                    u.username, 
                    COALESCE(a.remaining, 0) as attempts,
                    MAX(s.end_date) as sub_end
                FROM users u
                LEFT JOIN attempts a ON u.telegram_id = a.user_id
                LEFT JOIN subscriptions s ON u.telegram_id = s.user_id AND s.end_date > datetime('now')
                GROUP BY u.telegram_id
                ORDER BY u.created_at DESC
                LIMIT 50
            """)
            
            if not users:
                text = "📂 База данных пользователей пуста"
            else:
                text = "👥 Последние 50 пользователей:\n\n"
                for user in users:
                    user_id, username, attempts, sub_end = user
                    sub_status = "✅" if sub_end else "❌"
                    username_display = f"@{username}" if username else "нет username"
                    
                    text += (
                        f"🆔 {user_id} | 👤 {username_display}\n"
                        f"🃏 Попыток: {attempts} | Подписка: {sub_status}\n"
                        f"————————————————\n"
                    )
            
            await query.edit_message_text(
                text=text,
                reply_markup=BaseHandler.create_keyboard([("🔙 Назад", "admin_users")]),
                parse_mode=None
            )
        except Exception as e:
            logger.error(f"Error in admin_list_users: {e}")
            await query.edit_message_text(
                "❌ Ошибка при получении списка пользователей",
                reply_markup=BaseHandler.create_keyboard([("🔙 Назад", "admin_users")])
            )

    @staticmethod
    async def forward_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Пересылка вопроса администратору"""
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            "✍️ Напишите ваш вопрос администратору:",
            reply_markup=BaseHandler.create_keyboard([("🔙 Назад", "back")])
        )
        return ASK_QUESTION

    @staticmethod
    async def process_admin_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка вопроса для администратора"""
        if update.message.text.lower() == "назад":
            await StartHandler.start(update, context)
            return ConversationHandler.END
            
        user = update.effective_user
        question = update.message.text
            
        await context.bot.send_message(
            chat_id=Config.ADMIN_CHAT_ID,
            text=f"📨 Вопрос от @{user.username} (ID: {user.id}):\n\n{question}"
        )
            
        await update.message.reply_text(
            "✅ Ваш вопрос отправлен! Администратор ответит в ближайшее время.",
            reply_markup=BaseHandler.create_keyboard([("🏠 На главную", "start_over")])
        )
        return ConversationHandler.END

    @staticmethod
    async def admin_analytics(update, context):
        """Аналитика для администратора"""
        query = getattr(update, "callback_query", None)
        if query:
            await query.answer()
        try:
            # Собираем статистику
            stats = await execute_query("""
                SELECT
                    (SELECT COUNT(*) FROM users),                               -- всего пользователей
                    (SELECT COUNT(*) FROM readings),                            -- всего раскладов
                    (SELECT COUNT(*) FROM subscriptions WHERE end_date > datetime('now')),  -- активные подписки
                    (SELECT SUM(remaining) FROM attempts),                      -- всего оставшихся попыток
                    (SELECT COUNT(*) FROM readings WHERE created_at >= datetime('now', '-1 day')),   -- раскладов за сутки
                    (SELECT COUNT(*) FROM readings WHERE created_at >= datetime('now', '-7 day'))    -- за неделю
            """)
            (
                total_users,
                total_readings,
                active_subs,
                total_attempts,
                readings_day,
                readings_week
            ) = stats[0]
    
            # Формируем сообщение
            text = (
                "📊 <b>Аналитика бота</b>\n\n"
                f"👥 Пользователей: <b>{total_users}</b>\n"
                f"🃏 Всего раскладов: <b>{total_readings}</b>\n"
                f"📅 За 24ч: <b>{readings_day}</b>\n"
                f"📆 За неделю: <b>{readings_week}</b>\n"
                f"💎 Активных подписок: <b>{active_subs}</b>\n"
                f"🧮 Оставшихся попыток: <b>{total_attempts}</b>\n"
            )
            if query:
                await query.edit_message_text(
                    text=text,
                    parse_mode="HTML",
                    reply_markup=BaseHandler.create_keyboard([("🔙 Назад", "start_over")])
                )
            else:
                await update.message.reply_text(
                    text,
                    parse_mode="HTML",
                    reply_markup=BaseHandler.create_keyboard([("🔙 Назад", "start_over")])
                )
        except Exception as e:
            logger.error(f"Error in admin_analytics: {e}")
            err_text = "❌ Ошибка при получении аналитики"
            if query:
                await query.edit_message_text(
                    err_text,
                    reply_markup=BaseHandler.create_keyboard([("🔙 Назад", "start_over")])
                )
            else:
                await update.message.reply_text(
                    err_text,
                    reply_markup=BaseHandler.create_keyboard([("🔙 Назад", "start_over")])
                )
    
    