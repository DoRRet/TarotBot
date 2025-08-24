import aiosqlite
from pathlib import Path
from config import Config
import logging
from typing import Optional
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

def _utcnow_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

async def init_db():
    """Инициализация базы данных"""
    Path(Config.DB_PATH.parent).mkdir(exist_ok=True)
    
    async with aiosqlite.connect(Config.DB_PATH) as conn:
        await conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY NOT NULL,
            username TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            start_date TIMESTAMP NOT NULL,
            end_date TIMESTAMP NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(telegram_id)
        );
        
        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            remaining INTEGER NOT NULL DEFAULT 0,
            last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(telegram_id)
        );
        
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            question TEXT,
            situation TEXT,
            cards TEXT NOT NULL,
            interpretation TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(telegram_id)
        );
        ''')
        try:
            cur = await conn.execute("PRAGMA table_info(users)")
            cols = [row[1] for row in await cur.fetchall()]
            if "referrer_id" not in cols:
                await conn.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER")
                await conn.commit()
        except Exception as e:
            logger.warning(f"Schema check/migration failed: {e}")
        
        # Индексы для ускорения поиска активных подписок
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_user_end ON subscriptions(user_id, end_date)")
        await conn.commit()

async def execute_query(query: str, params: tuple = (), fetch_one: bool = False):
    """Универсальная функция для выполнения запросов"""
    try:
        async with aiosqlite.connect(Config.DB_PATH) as conn:
            cursor = await conn.execute(query, params)
            await conn.commit()
            return await cursor.fetchone() if fetch_one else await cursor.fetchall()
    except Exception as e:
        logger.error(f"Database error: {e}")
        raise

async def add_user(telegram_id: int, username: str = None, referrer_id: Optional[int] = None, context=None):
    user = await get_user(telegram_id)
    if not user:
        # Первый вход — добавляем
        await execute_query(
            "INSERT INTO users (telegram_id, username, referrer_id) VALUES (?, ?, ?)",
            (telegram_id, username, referrer_id)
        )
        # Новый пользователь по умолчанию получает 5 попыток
        await execute_query(
            "INSERT OR IGNORE INTO attempts (user_id, remaining) VALUES (?, ?)",
            (telegram_id, 5)
        )
        # Если есть реферал и не сам себе, начисляем по 1 бонусу обоим
        if referrer_id and referrer_id != telegram_id:
            await update_attempts(referrer_id, 1)
            await update_attempts(telegram_id, 1)  # <-- Новый пользователь получает +1
            # Сообщаем пригласителю
            if context:
                try:
                    await context.bot.send_message(
                        chat_id=referrer_id,
                        text=f"🎉 По вашей ссылке зарегистрировался @{username or telegram_id}! Вам начислена 1 попытка."
                    )
                except Exception:
                    pass
            # Сообщаем новому пользователю
            if context:
                try:
                    await context.bot.send_message(
                        chat_id=telegram_id,
                        text=f"🎁 Добро пожаловать! Вы зарегистрировались по реферальной ссылке и получили дополнительную попытку."
                    )
                except Exception:
                    pass
    else:
        await execute_query(
            "UPDATE users SET username = ? WHERE telegram_id = ?",
            (username, telegram_id)
        )

async def get_user(telegram_id: int):
    """Получение информации о пользователе"""
    return await execute_query(
        "SELECT * FROM users WHERE telegram_id = ?", 
        (telegram_id,), 
        fetch_one=True
    )

async def get_attempts(telegram_id: int):
    """Получение попыток с обработкой ошибок"""
    try:
        async with aiosqlite.connect(Config.DB_PATH) as conn:
            cursor = await conn.execute(
                "SELECT remaining FROM attempts WHERE user_id = ?",
                (telegram_id,)
            )
            result = await cursor.fetchone()
            return result[0] if result else 0
    except Exception as e:
        logger.error(f"Error getting attempts for {telegram_id}: {e}")
        return None

async def get_active_subscription(telegram_id: int):
    """Получение подписки с обработкой ошибок"""
    try:
        async with aiosqlite.connect(Config.DB_PATH) as conn:
            cursor = await conn.execute(
                "SELECT * FROM subscriptions WHERE user_id = ? AND end_date > datetime('now')",
                (telegram_id,)
            )
            return await cursor.fetchone()
    except Exception as e:
        logger.error(f"Error getting subscription for {telegram_id}: {e}")
        return None

async def update_attempts(telegram_id: int, change: int):
    """Обновление количества попыток с защитой от отрицательных значений при подписке"""
    async with aiosqlite.connect(Config.DB_PATH) as conn:
        # Проверяем есть ли активная подписка
        has_sub = await conn.execute(
            "SELECT 1 FROM subscriptions WHERE user_id = ? AND end_date > datetime('now')",
            (telegram_id,)
        )
        has_sub = await has_sub.fetchone()

        if has_sub and change < 0:
            # Если есть подписка, не даем уйти в минус
            await conn.execute(
                "UPDATE attempts SET remaining = MAX(remaining + ?, 0) WHERE user_id = ?",
                (change, telegram_id)
            )
        else:
            # Иначе обычное обновление
            await conn.execute(
                "UPDATE attempts SET remaining = remaining + ? WHERE user_id = ?",
                (change, telegram_id)
            )
        await conn.commit()


async def add_subscription(telegram_id: int, sub_type: str, duration_days: int):
    """Добавление подписки (UTC-таймстемпы)"""
    start_dt = datetime.now(timezone.utc)
    end_dt = start_dt + timedelta(days=duration_days)
    start = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    end = end_dt.strftime("%Y-%m-%d %H:%M:%S")
    await execute_query(
        "INSERT INTO subscriptions (user_id, type, start_date, end_date) VALUES (?, ?, ?, ?)",
        (telegram_id, sub_type, start, end)
    )

async def cancel_subscription(user_id: int) -> int:
    """Аннулировать активные подписки пользователя, вернуть число отменённых"""
    async with aiosqlite.connect(Config.DB_PATH) as conn:
        cursor = await conn.execute(
            """
            UPDATE subscriptions
               SET end_date = datetime('now')
             WHERE user_id = ?
               AND end_date > datetime('now')
            """,
            (user_id,)
        )
        await conn.commit()
        return cursor.rowcount

async def save_reading(telegram_id: int, question: str, situation: str, cards: list, interpretation: str):
    """Сохранение расклада"""
    await execute_query(
        "INSERT INTO readings (user_id, question, situation, cards, interpretation) VALUES (?, ?, ?, ?, ?)",
        (telegram_id, question, situation, ",".join(cards), interpretation)
    )

