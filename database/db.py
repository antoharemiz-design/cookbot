import aiosqlite
from pathlib import Path
from datetime import date
import random

DB_PATH = Path(__file__).parent.parent / "cookbot.db"

EXPECTED_COLUMNS = {
    "user_prefs": ["user_id", "name", "diet", "allergies", "dislikes", "skill", "score"]
}

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # user_prefs с миграцией
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_prefs (
                user_id INTEGER PRIMARY KEY
            )
        """)
        cur = await db.execute("PRAGMA table_info(user_prefs)")
        existing_cols = {row[1] for row in await cur.fetchall()}
        for col in EXPECTED_COLUMNS["user_prefs"]:
            if col not in existing_cols:
                await db.execute(f"ALTER TABLE user_prefs ADD COLUMN {col} TEXT")

        # Остальные таблицы
        await db.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                user_id INTEGER NOT NULL,
                recipe_json TEXT NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, recipe_json)
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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cook_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                recipe_json TEXT NOT NULL,
                cooked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS quests (
                user_id INTEGER PRIMARY KEY,
                quest_date DATE NOT NULL,
                quest_type TEXT NOT NULL,
                description TEXT NOT NULL,
                completed INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS achievements (
                user_id INTEGER NOT NULL,
                achievement_key TEXT NOT NULL,
                UNIQUE(user_id, achievement_key)
            )
        """)
        await db.commit()

# ---------- Избранное ----------
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

# ---------- Последний рецепт ----------
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

# ---------- Профиль ----------
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

async def add_score(user_id: int, points: int):
    prefs = await get_user_prefs(user_id)
    current = int(prefs.get("score", 0)) if prefs else 0
    await update_user_prefs(user_id, score=current + points)

async def get_score(user_id: int) -> int:
    prefs = await get_user_prefs(user_id)
    return int(prefs.get("score", 0)) if prefs else 0

# ---------- Подписки ----------
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

# ---------- Оценки ----------
async def add_rating(user_id: int, recipe_title: str, rating: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO ratings (user_id, recipe_title, rating) VALUES (?, ?, ?)", (user_id, recipe_title, rating))
        await db.commit()

# ---------- Дневник ----------
async def add_cook_log(user_id: int, recipe: dict):
    import json
    recipe_str = json.dumps(recipe, ensure_ascii=False)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO cook_log (user_id, recipe_json) VALUES (?, ?)", (user_id, recipe_str))
        await db.commit()

async def get_cook_log(user_id: int, limit: int = 10) -> list[dict]:
    import json
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT recipe_json FROM cook_log WHERE user_id = ? ORDER BY cooked_at DESC LIMIT ?",
            (user_id, limit)
        )
        rows = await cur.fetchall()
        return [json.loads(row[0]) for row in rows]

# ---------- Квесты ----------
QUEST_TYPES = {
    "vegan": "Приготовь веганское блюдо (без мяса, рыбы, яиц, молочки)",
    "three_ingredients": "Используй ровно 3 ингредиента",
    "no_meat": "Приготовь блюдо без мяса",
    "dessert": "Приготовь десерт",
    "red_product": "Используй что-то красное (помидор, перец, клубника, свёкла)",
    "fast": "Приготовь за 20 минут или быстрее",
    "new_cuisine": "Попробуй новую кухню (итальянская, японская, мексиканская)",
}

def get_quest_types():
    return list(QUEST_TYPES.keys())

async def get_or_create_quest(user_id: int) -> dict:
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT * FROM quests WHERE user_id = ? AND quest_date = ?", (user_id, today))
        row = await cur.fetchone()
        if row:
            return {"type": row[2], "description": row[3], "completed": bool(row[4])}
        # Генерируем новый квест
        quest_type = random.choice(get_quest_types())
        description = QUEST_TYPES[quest_type]
        await db.execute("INSERT INTO quests (user_id, quest_date, quest_type, description) VALUES (?, ?, ?, ?)",
                         (user_id, today, quest_type, description))
        await db.commit()
        return {"type": quest_type, "description": description, "completed": False}

async def complete_quest(user_id: int):
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE quests SET completed = 1 WHERE user_id = ? AND quest_date = ?", (user_id, today))
        await db.commit()

async def is_quest_completed_today(user_id: int) -> bool:
    quest = await get_or_create_quest(user_id)
    return quest["completed"]

# ---------- Достижения ----------
ACHIEVEMENTS = {
    "first_recipe": {"name": "Первый рецепт", "desc": "Приготовьте своё первое блюдо", "icon": "🍽️", "points": 10},
    "five_recipes": {"name": "Умелец", "desc": "Приготовьте 5 блюд", "icon": "🥘", "points": 30},
    "ten_recipes": {"name": "Шеф", "desc": "Приготовьте 10 блюд", "icon": "👨‍🍳", "points": 50},
    "first_quest": {"name": "Квестер", "desc": "Выполните первый квест", "icon": "⚔️", "points": 20},
    "five_quests": {"name": "Охотник за квестами", "desc": "Выполните 5 квестов", "icon": "🏹", "points": 50},
    "score_100": {"name": "Сотня", "desc": "Наберите 100 очков", "icon": "💯", "points": 100},
    "fast_chef": {"name": "Быстрый шеф", "desc": "Приготовьте блюдо ≤15 минут", "icon": "⏱️", "points": 20},
}

async def grant_achievement(user_id: int, key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO achievements (user_id, achievement_key) VALUES (?, ?)", (user_id, key))
        await db.commit()
    return ACHIEVEMENTS.get(key)

async def has_achievement(user_id: int, key: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM achievements WHERE user_id = ? AND achievement_key = ?", (user_id, key))
        return (await cur.fetchone()) is not None

async def get_user_achievements(user_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT achievement_key FROM achievements WHERE user_id = ?", (user_id,))
        rows = await cur.fetchall()
        return [ACHIEVEMENTS[r[0]] for r in rows if r[0] in ACHIEVEMENTS]

async def get_cooked_count(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM cook_log WHERE user_id = ?", (user_id,))
        return (await cur.fetchone())[0]

async def get_completed_quests_count(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM quests WHERE user_id = ? AND completed = 1", (user_id,))
        return (await cur.fetchone())[0]

async def check_and_grant_achievements(user_id: int):
    # Вызывается после каждого приготовления
    cooked = await get_cooked_count(user_id)
    completed_quests = await get_completed_quests_count(user_id)
    score = await get_score(user_id)
    new_achievements = []

    if cooked >= 1 and not await has_achievement(user_id, "first_recipe"):
        await grant_achievement(user_id, "first_recipe")
        new_achievements.append(ACHIEVEMENTS["first_recipe"])
    if cooked >= 5 and not await has_achievement(user_id, "five_recipes"):
        await grant_achievement(user_id, "five_recipes")
        new_achievements.append(ACHIEVEMENTS["five_recipes"])
    if cooked >= 10 and not await has_achievement(user_id, "ten_recipes"):
        await grant_achievement(user_id, "ten_recipes")
        new_achievements.append(ACHIEVEMENTS["ten_recipes"])
    if completed_quests >= 1 and not await has_achievement(user_id, "first_quest"):
        await grant_achievement(user_id, "first_quest")
        new_achievements.append(ACHIEVEMENTS["first_quest"])
    if completed_quests >= 5 and not await has_achievement(user_id, "five_quests"):
        await grant_achievement(user_id, "five_quests")
        new_achievements.append(ACHIEVEMENTS["five_quests"])
    if score >= 100 and not await has_achievement(user_id, "score_100"):
        await grant_achievement(user_id, "score_100")
        new_achievements.append(ACHIEVEMENTS["score_100"])

    return new_achievements
