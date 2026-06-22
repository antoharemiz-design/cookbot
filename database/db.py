import aiosqlite
from pathlib import Path
from datetime import date
import random
import re

DB_PATH = Path(__file__).parent.parent / "cookbot.db"

EXPECTED_COLUMNS = {
    "user_prefs": [
        "user_id", "name", "diet", "allergies", "dislikes", "skill",
        "score", "favorite_cuisines", "favorite_ingredients"
    ]
}

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Создаём базовую таблицу user_prefs, если её нет
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_prefs (
                user_id INTEGER PRIMARY KEY
            )
        """)

        # Добавляем недостающие колонки, игнорируя ошибку дублирования
        cur = await db.execute("PRAGMA table_info(user_prefs)")
        existing_cols = {row[1] for row in await cur.fetchall()}
        for col in EXPECTED_COLUMNS["user_prefs"]:
            if col not in existing_cols:
                try:
                    await db.execute(f"ALTER TABLE user_prefs ADD COLUMN {col} TEXT")
                except:
                    pass  # колонка уже есть (гонка состояний)

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
                # Таблица для виртуального холодильника
        await db.execute("""
            CREATE TABLE IF NOT EXISTS fridge (
                user_id INTEGER NOT NULL,
                product TEXT NOT NULL,
                UNIQUE(user_id, product)
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
    # Безопасно получаем текущее значение score, убирая None
    current = int(prefs.get("score") or 0) if prefs else 0
    await update_user_prefs(user_id, score=current + points)

async def get_score(user_id: int) -> int:
    prefs = await get_user_prefs(user_id)
    return int(prefs.get("score") or 0) if prefs else 0

async def add_to_fridge(user_id: int, product: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO fridge (user_id, product) VALUES (?, ?)", (user_id, product.lower()))
        await db.commit()

async def remove_from_fridge(user_id: int, product: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM fridge WHERE user_id = ? AND product = ?", (user_id, product.lower()))
        await db.commit()

async def get_fridge(user_id: int) -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT product FROM fridge WHERE user_id = ?", (user_id,))
        rows = await cur.fetchall()
        return [r[0] for r in rows]

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

# ---------- Вкусовые предпочтения ----------
async def update_taste_prefs(user_id: int, recipe: dict, rating: int):
    import json
    title = recipe.get("title", "").lower()
    cuisines_found = []
    cuisine_keywords = {
        "итальянск": "итальянская",
        "японск": "японская",
        "мексиканск": "мексиканская",
        "французск": "французская",
        "китайск": "китайская",
        "тайск": "тайская",
        "индийск": "индийская",
        "русск": "русская",
        "украинск": "украинская",
        "грузинск": "грузинская",
        "азиатск": "азиатская",
    }
    for key, name in cuisine_keywords.items():
        if key in title:
            cuisines_found.append(name)

    ingredients_raw = [ing.lower().strip() for ing in recipe.get("ingredients", [])]
    # Глубокая очистка: удаляем числа, единицы измерения, скобки, знаки препинания
    ingredients_clean = []
    for ing in ingredients_raw:
        # Удаляем всё в скобках
        ing = re.sub(r'\([^)]*\)', '', ing)
        # Удаляем числа и единицы измерения (г, кг, мл, л, ст.л, ч.л, шт, зубчик и т.д.)
        ing = re.sub(r'\d+[\s,]*', '', ing)
        ing = re.sub(r'\b(г|кг|мл|л|ст\.?\s*л|ч\.?\s*л|шт|зуб|зубчик|пуч|щеп|по вкусу|веточка|пучок|щепотка)\b', '', ing, flags=re.IGNORECASE)
        # Удаляем оставшиеся знаки препинания и лишние пробелы
        ing = re.sub(r'[\/\.\,\-\d]+', ' ', ing)
        ing = ing.strip()
        if ing and len(ing) > 1:
            # Простейшая нормализация окончаний
            ing = ing.replace('курицы', 'курица').replace('лука', 'лук').replace('сметаны', 'сметана')
            ing = ing.replace('гречки', 'гречка').replace('масла', 'масло').replace('соли', 'соль')
            ingredients_clean.append(ing)

    async with aiosqlite.connect(DB_PATH) as db:
        prefs = await get_user_prefs(user_id) or {}
        fav_cuisines = json.loads(prefs.get("favorite_cuisines", "{}") or "{}")
        fav_ingredients = json.loads(prefs.get("favorite_ingredients", "{}") or "{}")

        delta = 1 if rating == 1 else -1
        for cuisine in cuisines_found:
            fav_cuisines[cuisine] = fav_cuisines.get(cuisine, 0) + delta
            if fav_cuisines[cuisine] <= 0:
                del fav_cuisines[cuisine]

        for ing in ingredients_clean:
            fav_ingredients[ing] = fav_ingredients.get(ing, 0) + delta
            if fav_ingredients[ing] <= 0:
                del fav_ingredients[ing]

        await update_user_prefs(user_id,
                                favorite_cuisines=json.dumps(fav_cuisines, ensure_ascii=False),
                                favorite_ingredients=json.dumps(fav_ingredients, ensure_ascii=False))


async def get_taste_summary(user_id: int) -> str:
    """Возвращает текстовую строку с предпочтениями для включения в промпт."""
    import json
    prefs = await get_user_prefs(user_id) or {}
    fav_cuisines = json.loads(prefs.get("favorite_cuisines", "{}") or "{}")
    fav_ingredients = json.loads(prefs.get("favorite_ingredients", "{}") or "{}")

    parts = []
    if fav_cuisines:
        top_cuisines = sorted(fav_cuisines.items(), key=lambda x: x[1], reverse=True)[:3]
        parts.append("Любимые кухни: " + ", ".join(f"{c} ({v})" for c, v in top_cuisines))
    if fav_ingredients:
        top_ingr = sorted(fav_ingredients.items(), key=lambda x: x[1], reverse=True)[:5]
        parts.append("Любимые ингредиенты: " + ", ".join(f"{i} ({v})" for i, v in top_ingr))
    return ". ".join(parts) + ". " if parts else ""
    
    return new_achievements
