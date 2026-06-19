import aiosqlite
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "cookbot.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
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
                recipe_title TEXT,
                rating INTEGER
            )
        """)
        await db.commit()

# Существующие функции (favorites)
async def add_favorite(user_id: int, recipe: dict):
    import json
    recipe_str = json.dumps(recipe, ensure_ascii=False)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO favorites (user_id, recipe_json) VALUES (?, ?)",
            (user_id, recipe_str)
        )
        await db.commit()

async def get_favorites(user_id: int) -> list[dict]:
    import json
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT recipe_json FROM favorites WHERE user_id = ? ORDER BY added_at DESC",
            (user_id,)
        )
        rows = await cursor.fetchall()
        return [json.loads(row[0]) for row in rows]

async def remove_favorite(user_id: int, recipe_title: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT rowid FROM favorites WHERE user_id = ? AND recipe_json LIKE ? LIMIT 1",
            (user_id, f'%{recipe_title}%')
        )
        row = await cursor.fetchone()
        if row:
            await db.execute("DELETE FROM favorites WHERE rowid = ?", (row[0],))
            await db.commit()
            return True
    return False

async def set_last_recipe(user_id: int, recipe: dict):
    import json
    recipe_str = json.dumps(recipe, ensure_ascii=False)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO last_recipe (user_id, recipe_json) VALUES (?, ?)",
            (user_id, recipe_str)
        )
        await db.commit()

async def get_last_recipe(user_id: int) -> dict | None:
    import json
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT recipe_json FROM last_recipe WHERE user_id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()
        return json.loads(row[0]) if row else None

# Профиль
async def update_user_prefs(user_id: int, **kwargs):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM user_prefs WHERE user_id = ?", (user_id,))
        if await cur.fetchone():
            sets = ", ".join(f"{k} = ?" for k in kwargs)
            await db.execute(f"UPDATE user_prefs SET {sets} WHERE user_id = ?", (*kwargs.values(), user_id))
        else:
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

# Подписки
async def add_subscriber(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO subscribers (user_id, active) VALUES (?, 1)", (user_id,))
        await db.commit()

async def remove_subscriber(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM subscribers WHERE user_id = ?", (user_id,))
        await db.commit()

async def get_all_subscribers() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM subscribers WHERE active = 1")
        rows = await cur.fetchall()
        return [r[0] for r in rows]

# Оценки
async def add_rating(user_id: int, recipe_title: str, rating: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO ratings (user_id, recipe_title, rating) VALUES (?, ?, ?)", (user_id, recipe_title, rating))
        await db.commit()
