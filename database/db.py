import aiosqlite
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "cookbot.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Существующие таблицы
        await db.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                user_id INTEGER NOT NULL,
                recipe_json TEXT NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, recipe_json)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_prefs (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                diet TEXT,
                allergies TEXT,
                dislikes TEXT,
                skill TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS last_recipe (
                user_id INTEGER PRIMARY KEY,
                recipe_json TEXT NOT NULL
            )
        """)
        # Новые таблицы
        await db.execute("""
            CREATE TABLE IF NOT EXISTS subscribers (
                user_id INTEGER PRIMARY KEY,
                active INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ratings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                recipe_json TEXT,
                rating INTEGER
            )
        """)
        await db.commit()

# ... остальные функции (добавим новые)
async def update_user_prefs(user_id: int, **kwargs):
    """Обновить или создать профиль"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Проверим, существует ли запись
        cur = await db.execute("SELECT user_id FROM user_prefs WHERE user_id = ?", (user_id,))
        if await cur.fetchone():
            # Update
            sets = ", ".join(f"{k} = ?" for k in kwargs)
            await db.execute(f"UPDATE user_prefs SET {sets} WHERE user_id = ?", (*kwargs.values(), user_id))
        else:
            # Insert
            cols = ", ".join(kwargs.keys())
            placeholders = ", ".join("?" for _ in kwargs)
            await db.execute(f"INSERT INTO user_prefs (user_id, {cols}) VALUES (?, {placeholders})", (user_id, *kwargs.values()))
        await db.commit()

async def get_user_prefs(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT * FROM user_prefs WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cur.description]
        return dict(zip(columns, row))

async def add_subscriber(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO subscribers (user_id, active) VALUES (?, 1)", (user_id,))
        await db.commit()

async def remove_subscriber(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM subscribers WHERE user_id = ?", (user_id,))
        await db.commit()

async def get_all_subscribers():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM subscribers WHERE active = 1")
        rows = await cur.fetchall()
        return [r[0] for r in rows]
