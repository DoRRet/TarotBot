import sqlite3

def create_db():
    conn = sqlite3.connect('tarotbot.db')  
    cursor = conn.cursor()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER UNIQUE NOT NULL,
        username TEXT,
        free_attempts INTEGER DEFAULT 5,
        subscription_status TEXT DEFAULT 'free'
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        subscription_type TEXT,
        start_date TEXT,
        end_date TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tarot_readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        reading_date TEXT,
        spread TEXT,
        interpretation TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    ''')

    conn.commit()
    conn.close()
    
create_db()

def add_user(telegram_id, username):
    conn = sqlite3.connect('tarotbot.db')
    cursor = conn.cursor()

    cursor.execute('''
    INSERT OR IGNORE INTO users (telegram_id, username)
    VALUES (?, ?)
    ''', (telegram_id, username))

    conn.commit()
    conn.close()

def get_user(telegram_id):
    conn = sqlite3.connect('tarotbot.db')
    cursor = conn.cursor()

    cursor.execute('''
    SELECT * FROM users WHERE telegram_id = ?
    ''', (telegram_id,))
    user = cursor.fetchone()

    conn.close()
    return user

def update_free_attempts(telegram_id, new_attempts=None):
    
    conn = sqlite3.connect('tarotbot.db')
    cursor = conn.cursor()

    if new_attempts is None:
        # Уменьшаем попытки на 1
        cursor.execute('''
        UPDATE users SET free_attempts = free_attempts - 1 WHERE telegram_id = ?
        ''', (telegram_id,))
    else:
        # Устанавливаем конкретное количество попыток
        cursor.execute('''
        UPDATE users SET free_attempts = ? WHERE telegram_id = ?
        ''', (new_attempts, telegram_id))

    conn.commit()
    conn.close()

def save_tarot_reading(user_id, spread, interpretation):
    conn = sqlite3.connect('tarotbot.db')
    cursor = conn.cursor()

    cursor.execute('''
    INSERT INTO tarot_readings (user_id, reading_date, spread, interpretation)
    VALUES (?, DATETIME('now'), ?, ?)
    ''', (user_id, spread, interpretation))

    conn.commit()
    conn.close()

def activate_subscription(telegram_id, subscription_type, start_date, end_date):
    conn = sqlite3.connect('tarotbot.db')
    cursor = conn.cursor()

    cursor.execute('''
    INSERT INTO subscriptions (user_id, subscription_type, start_date, end_date)
    VALUES ((SELECT id FROM users WHERE telegram_id = ?), ?, ?, ?)
    ''', (telegram_id, subscription_type, start_date, end_date))

    cursor.execute('''
    UPDATE users SET subscription_status = ? WHERE telegram_id = ?
    ''', (subscription_type, telegram_id))

    conn.commit()
    conn.close()

def get_subscription_status(telegram_id):
    conn = sqlite3.connect('tarotbot.db')
    cursor = conn.cursor()

    cursor.execute('''
    SELECT subscription_status FROM users WHERE telegram_id = ?
    ''', (telegram_id,))
    status = cursor.fetchone()

    conn.close()
    return status[0] if status else None