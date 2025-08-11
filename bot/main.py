import sys
sys.path.append('/root/TarotBot')
import asyncio
import logging
import warnings
from telegram.warnings import PTBUserWarning
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ConversationHandler, CallbackQueryHandler
)
from config import Config 
from bot.handlers import *
from database import init_db
import signal


# Игнорировать предупреждения
warnings.filterwarnings("ignore", category=PTBUserWarning)

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def post_init(application: Application) -> None:
    
    """Действия после инициализации бота"""
    await application.bot.set_my_commands([
        ("start", "Запустить бота"),
        ("help", "Помощь")
    ])
    # Загружаем значения карт при старте
    await TarotInterpreter.load_meanings() 
    logger.info("Значения карт успешно загружены")

def setup_handlers(app: Application) -> None:
    """Настройка всех обработчиков"""
    # Обработчики команд
    app.add_handler(CommandHandler("start", StartHandler.start))
    app.add_handler(CommandHandler("help", StartHandler.help))
    app.add_handler(CommandHandler("admin", AdminHandler.admin_menu))
    app.add_handler(CommandHandler("help", HelpHandler.show_help))
    app.add_handler(CallbackQueryHandler(
    AdminHandler.admin_analytics,
    pattern="^admin_analytics$"
))
    app.add_handler(CallbackQueryHandler(
    ReadingHandler.daily_reading,
    pattern="^daily_reading$"
))
    app.add_handler(CallbackQueryHandler(
    ReadingHandler.weekly_reading,
    pattern="^weekly_reading$"
))
    app.add_handler(CallbackQueryHandler(
    ReferralHandler.invite,
    pattern="^referral$"
))


    # Обработчик кнопки помощи
    app.add_handler(CallbackQueryHandler(
        HelpHandler.show_help,
        pattern="^help$"
    ))

    # ConversationHandler для консультаций
    consultation_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                ConsultationHandler.start_consultation,
                pattern="^consultation$"
            ),
            CallbackQueryHandler(
                ConsultationHandler.confirm_consultation,
                pattern="^confirm_consultation$"
            )
        ],
        states={
            "GET_CONSULTATION_DETAILS": [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    ConsultationHandler.get_consultation_details
                )
            ]
        },
        fallbacks=[
            CommandHandler("cancel", ConsultationHandler.cancel_consultation),
            CallbackQueryHandler(
                StartHandler.start,
                pattern="^start_over$"
            )
        ]
    )
    app.add_handler(consultation_conv)

    # ConversationHandler для админ-панели
    admin_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(AdminHandler.admin_users_menu, pattern="^admin_users$"),
            CallbackQueryHandler(AdminHandler.admin_request_user_id, pattern="^admin_(add_attempts|remove_attempts|add_sub)$")
        ],
        states={
            "ADMIN_GET_USER_ID": [MessageHandler(filters.TEXT & ~filters.COMMAND, AdminHandler.admin_get_user_id)],
            "ADMIN_GET_ATTEMPTS": [MessageHandler(filters.TEXT & ~filters.COMMAND, AdminHandler.admin_get_attempts)],
            "ADMIN_GET_SUB_TYPE": [CallbackQueryHandler(AdminHandler.admin_add_subscription, pattern="^admin_sub_")]
        },
        fallbacks=[
            CallbackQueryHandler(AdminHandler.admin_users_menu, pattern="^admin_back$"),
            CallbackQueryHandler(AdminHandler.admin_users_menu, pattern="^admin_users$")
        ],
        per_message=False
    )
    app.add_handler(admin_conv)

    admin_broadcast_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(AdminHandler.admin_broadcast_menu, pattern="^admin_broadcast$")
        ],
        states={
            "ADMIN_BROADCAST": [
                MessageHandler(filters.TEXT | filters.PHOTO, AdminHandler.process_broadcast)
            ]
        },
        fallbacks=[
            CallbackQueryHandler(AdminHandler.admin_menu, pattern="^start_over$"),
            CommandHandler("cancel", AdminHandler.admin_menu)
        ],
        per_message=False
    )
    app.add_handler(admin_broadcast_conv)

    # Обработчик списка пользователей
    app.add_handler(CallbackQueryHandler(
        AdminHandler.admin_list_users,
        pattern="^admin_list_users$"
    ))

    # ConversationHandler для раскладов Таро
    reading_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(ReadingHandler.begin_reading, pattern="^request_reading$")],
        states={
            QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ReadingHandler.process_question)],
            SITUATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ReadingHandler.process_situation)],
            NUM_CARDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ReadingHandler.process_num_cards)],
            CHOOSE_METHOD: [
                CallbackQueryHandler(ReadingHandler.choose_method, pattern="^(random_cards|manual_cards|pick_cards|back)$"),
            ],
            ENTER_CARDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ReadingHandler.process_manual_cards)],
            PICK_CARDS: [
                CallbackQueryHandler(ReadingHandler.pick_cards_process, pattern=r"^pick_card_\d+$"),
                CallbackQueryHandler(lambda update, context: update.callback_query.answer(), pattern="^picked_ignore$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", ReadingHandler.cancel_reading),
            CallbackQueryHandler(StartHandler.start, pattern="^start_over$"),
            CallbackQueryHandler(ReadingHandler.begin_reading, pattern="^back$")
        ]
    )
    app.add_handler(reading_conv)

    # Обработчики значений карт
    app.add_handler(CallbackQueryHandler(
        CardMeaningsHandler.show_categories,
        pattern="^card_meanings$"
    ))
    app.add_handler(CallbackQueryHandler(
        CardMeaningsHandler.show_cards,
        pattern="^(major_arcana|wands|cups|swords|pentacles)$"
    ))
    app.add_handler(CallbackQueryHandler(
        CardMeaningsHandler.show_meaning,
        pattern=r"^meaning_.+_[01]$"
    ))

    # ConversationHandler для поиска карт
    search_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(
            CardMeaningsHandler.start_search, 
            pattern="^search_card$"
        )],
        states={
            "SEARCH_CARD": [MessageHandler(
                filters.TEXT & ~filters.COMMAND, 
                CardMeaningsHandler.process_search
            )]
        },
        fallbacks=[
            CallbackQueryHandler(
                CardMeaningsHandler.show_categories, 
                pattern="^card_meanings$"
            ),
            CommandHandler("cancel", CardMeaningsHandler.cancel_search)
        ]
    )
    app.add_handler(search_conv)

    # Обработчики подписки
    app.add_handler(CallbackQueryHandler(
        SubscriptionHandler.show_subscriptions,
        pattern="^subscription$"
    ))
    app.add_handler(CallbackQueryHandler(
        SubscriptionHandler.handle_subscription,
        pattern="^sub_(monthly|5|10|15)$"
    ))

    # Обработчик заказа админу (ещё один admin conv, не конфликтует)
    admin_order_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                AdminHandler.forward_to_admin,
                pattern="^order_from_admin$"
            )
        ],
        states={
            ASK_QUESTION: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    AdminHandler.process_admin_question
                )
            ]
        },
        fallbacks=[
            CallbackQueryHandler(
                StartHandler.start,
                pattern="^start_over$"
            ),
            CallbackQueryHandler(
                SubscriptionHandler.show_subscriptions,
                pattern="^back$"
            )
        ],
        per_message=False
    )
    app.add_handler(admin_order_conv)

    # Общие обработчики кнопок
    app.add_handler(CallbackQueryHandler(
        StartHandler.start,
        pattern="^start_over$"
    ))
    app.add_handler(CallbackQueryHandler(
        BaseHandler.back_handler,
        pattern="^back$"
    ))

    # Обработчик неизвестных команд (ставьте в самый конец!)
    app.add_handler(MessageHandler(
        filters.ALL,
        StartHandler.start
    ))

async def run_bot() -> None:
    """Основная функция запуска бота"""
    application = None
    try:
        await init_db()
        
        application = Application.builder() \
            .token(Config.TELEGRAM_TOKEN) \
            .post_init(post_init) \
            .build()
        
        setup_handlers(application)
        
        logger.info("Бот запущен и работает...")
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        
        # Бесконечный цикл ожидания
        while True:
            await asyncio.sleep(3600)  # Спим 1 час
            
    except asyncio.CancelledError:
        logger.info("Получен сигнал остановки...")
    except Exception as e:
        logger.exception(f"Ошибка в run_bot: {str(e)}")
    finally:
        if application:
            try:
                logger.info("Остановка бота...")
                if application.updater.running:
                    await application.updater.stop()
                if application.running:
                    await application.stop()
                await application.shutdown()
            except Exception as e:
                logger.error(f"Ошибка при остановке: {str(e)}")
        logger.info("Бот полностью остановлен")

async def shutdown(signal, loop, app):
    """Обработка сигналов завершения"""
    logger.info(f"Получен сигнал {signal.name}...")
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()

def main() -> None:
    """Точка входа"""
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Создаем приложение внутри event loop
        app_task = loop.create_task(run_bot())
        
        # Обработка сигналов
        signals = (signal.SIGINT, signal.SIGTERM)
        for s in signals:
            try:
                loop.add_signal_handler(
                    s,
                    lambda s=s: asyncio.create_task(shutdown(s, loop, app_task)))
            except NotImplementedError:
                logger.warning(f"Signal handlers not supported on this platform for signal {s}")
        
        logger.info("Бот запущен. Ожидание сообщений...")
        loop.run_forever()
        
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем (KeyboardInterrupt)")
    except Exception as e:
        logger.exception(f"Критическая ошибка: {str(e)}")
    finally:
        if loop:
            try:
                # Завершаем все pending tasks
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                
                # Даем задачам время на завершение
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                
                if loop.is_running():
                    loop.stop()
                
                loop.close()
                logger.info("Event loop закрыт")
            except Exception as e:
                logger.error(f"Ошибка при закрытии event loop: {str(e)}")

if __name__ == "__main__":
    main()