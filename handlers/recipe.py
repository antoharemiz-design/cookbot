from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardButton, InlineKeyboardMarkup,
    InlineQueryResultArticle, InputTextMessageContent
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from services.ai import get_recipe
from database.db import (
    add_favorite, get_favorites, remove_favorite,
    set_last_recipe, get_last_recipe, get_user_prefs, update_user_prefs,
    add_subscriber, remove_subscriber, get_all_subscribers, add_rating,
    add_cook_log, get_cook_log, get_or_create_quest, complete_quest, is_quest_completed_today,
    check_and_grant_achievements, get_user_achievements, get_cooked_count, get_score, add_score,
    grant_achievement, has_achievement, ACHIEVEMENTS, QUEST_TYPES, get_completed_quests_count,
    add_to_fridge, remove_from_fridge, get_fridge
)
import logging
import re
import hashlib
import asyncio

router = Router()
logging.basicConfig(level=logging.INFO)

# Состояния
class FridgeAdd(StatesGroup):
    waiting_for_product = State()

class PlanWaiting(StatesGroup):
    waiting_for_prefs = State()

class WeekDaySelect(StatesGroup):
    waiting_for_day = State()

# ---------- Главное меню ----------
def make_main_kb(user_id: int):
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🍳 Придумать рецепт"), KeyboardButton(text="⭐ Мои избранные")],
            [KeyboardButton(text="🧊 Мой холодильник"), KeyboardButton(text="📖 Дневник")],
            [KeyboardButton(text="🏆 Статистика"), KeyboardButton(text="🔔 Блюдо дня")],
            [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="🗡 Квест дня")],
            [KeyboardButton(text="📅 План на день"), KeyboardButton(text="📅 План на неделю")],
            [KeyboardButton(text="ℹ️ О боте")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Что хотите приготовить?"
    )

def plan_waiting_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🚫 Без пожеланий")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def week_days_kb():
    """Клавиатура для выбора дня недели."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Понедельник")],
            [KeyboardButton(text="Вторник")],
            [KeyboardButton(text="Среда")],
            [KeyboardButton(text="Четверг")],
            [KeyboardButton(text="Пятница")],
            [KeyboardButton(text="Суббота")],
            [KeyboardButton(text="Воскресенье")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

# ---------- Вспомогательные функции ----------
def safe_str(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    return ""

def format_recipe(recipe: dict) -> str:
    title = safe_str(recipe.get('title', 'Блюдо'))
    time = safe_str(recipe.get('cooking_time', 'не указано'))
    difficulty = safe_str(recipe.get('difficulty', 'не указана'))
    ingredients = [safe_str(ing) for ing in recipe.get('ingredients', [])]
    steps = [safe_str(step) for step in recipe.get('steps', [])]
    tip = safe_str(recipe.get('tip', ''))
    text = (
        f"🍽 <b>{title}</b>\n"
        f"⏱ Время: {time}\n"
        f"📊 Сложность: {difficulty}\n\n"
        f"<b>Ингредиенты:</b>\n" + "\n".join(f"• {ing}" for ing in ingredients) + "\n\n"
        f"<b>Приготовление:</b>\n" + "\n".join(f"{i+1}. {step}" for i, step in enumerate(steps))
    )
    if tip:
        text += f"\n\n💡 <i>Совет: {tip}</i>"
    return text

def match_quest(recipe: dict, quest_type: str) -> bool:
    title = safe_str(recipe.get("title", "")).lower()
    ingredients = [safe_str(ing).lower() for ing in recipe.get("ingredients", [])]
    raw_time = recipe.get("cooking_time", "")
    cooking_time_str = raw_time.lower() if isinstance(raw_time, str) else str(raw_time)
    minutes = 999
    match = re.search(r'(\d+)\s*мин', cooking_time_str)
    if match:
        minutes = int(match.group(1))
    else:
        numbers = re.findall(r'\d+', cooking_time_str)
        if numbers:
            minutes = min(map(int, numbers))

    if quest_type == "vegan":
        forbidden = ["мясо", "курица", "свинина", "говядина", "рыба", "яйцо", "яйца",
                     "молоко", "сливки", "сыр", "сметана", "масло сливочное", "креветки", "морепродукты"]
        for ing in ingredients:
            for f in forbidden:
                if f in ing:
                    return False
        return True
    elif quest_type == "three_ingredients":
        return len(recipe.get("ingredients", [])) == 3
    elif quest_type == "no_meat":
        forbidden = ["мясо", "курица", "свинина", "говядина", "рыба", "креветки", "морепродукты"]
        for ing in ingredients:
            for f in forbidden:
                if f in ing:
                    return False
        return True
    elif quest_type == "dessert":
        dessert_keywords = ["сахар", "мёд", "шоколад", "фрукты", "десерт", "сладкий", "крем", "варенье", "мороженое"]
        return any(kw in title for kw in dessert_keywords) or any(kw in " ".join(ingredients) for kw in dessert_keywords)
    elif quest_type == "red_product":
        reds = ["помидор", "перец красный", "клубника", "свёкла", "красная рыба", "красный", "томат"]
        return any(any(r in ing for r in reds) for ing in ingredients)
    elif quest_type == "fast":
        return minutes <= 20
    elif quest_type == "new_cuisine":
        cuisines = ["итальянск", "японск", "мексиканск", "китайск", "французск", "тайск", "индийск"]
        return any(c in title for c in cuisines)
    return False

async def generate_recipe_from_list(user_id: int, products: list[str]) -> tuple[dict | None, str | None]:
    prefs = await get_user_prefs(user_id)
    extra = ""
    if prefs:
        if prefs.get("diet") and prefs["diet"] != "Без ограничений":
            extra += f"Диета: {prefs['diet']}. "
        if prefs.get("allergies") and prefs["allergies"] != "Нет":
            extra += f"Аллергии: {prefs['allergies']}. "
        if prefs.get("dislikes") and prefs["dislikes"] != "Нет":
            extra += f"Не любит: {prefs['dislikes']}. "
        if prefs.get("skill"):
            extra += f"Уровень готовки: {prefs['skill']}. "
    user_input = ", ".join(products)
    return await get_recipe(user_input, extra_context=extra)

# ---------- Общая функция планировщика ----------
async def generate_plan(message: types.Message, period: str, preferences: str = "", specific_day: str = None):
    if specific_day:
        # Генерация на один конкретный день
        await message.answer(f"📅 Генерирую меню на {specific_day}...")
        prompt = f"Составь меню на {specific_day} (завтрак, обед, ужин). Для каждого приёма пищи предложи полноценный рецепт. "
    else:
        if period == "day":
            await message.answer(f"📅 Генерирую меню на день...")
            prompt = "Составь меню на один день (завтрак, обед, ужин). Для каждого приёма пищи предложи полноценный рецепт. "
        else:
            await message.answer(f"📅 Генерирую меню на неделю...")
            prompt = "Составь меню на неделю (понедельник, вторник, среда, четверг, пятница, суббота, воскресенье). Для каждого дня предложи завтрак, обед и ужин с полноценными рецептами. "

    prefs = await get_user_prefs(message.from_user.id)
    extra = ""
    if prefs:
        if prefs.get("diet") and prefs["diet"] != "Без ограничений":
            extra += f"Диета: {prefs['diet']}. "
        if prefs.get("allergies") and prefs["allergies"] != "Нет":
            extra += f"Аллергии: {prefs['allergies']}. "
        if prefs.get("dislikes") and prefs["dislikes"] != "Нет":
            extra += f"Не любит: {prefs['dislikes']}. "
        if prefs.get("skill"):
            extra += f"Уровень готовки: {prefs['skill']}. "
    if preferences:
        extra += f"Дополнительные пожелания: {preferences}. "

    fridge_products = await get_fridge(message.from_user.id)
    if fridge_products:
        extra += f"В холодильнике есть: {', '.join(fridge_products)}. "

    prompt += extra
    prompt += (
        'Ответь в формате JSON: { "days": [ { "day": "Название дня", "meals": [ '
        '{ "type": "завтрак/обед/ужин", "recipe": { "title": "...", "cooking_time": "...", '
        '"difficulty": "...", "ingredients": ["..."], "steps": ["..."], "tip": "..." } } ] } ] }'
    )

    recipe, raw_response = await get_recipe(prompt)

    if recipe is None:
        await message.answer("😔 Не удалось сгенерировать меню. Попробуйте позже.")
        return

    try:
        days = recipe.get("days", [])
        if not days:
            raise ValueError("Пустое меню")

        all_ingredients = []

        for day in days:
            day_name = day.get("day", "День")
            meals = day.get("meals", [])
            day_text = f"<b>{day_name}</b>\n\n"
            for meal in meals:
                meal_type = meal.get("type", "Приём пищи")
                rec = meal.get("recipe", {})
                if rec:
                    title = safe_str(rec.get("title", "Блюдо"))
                    time = safe_str(rec.get("cooking_time", "?"))
                    diff = safe_str(rec.get("difficulty", ""))
                    ingredients = rec.get("ingredients", [])
                    ingr_text = ", ".join([safe_str(i) for i in ingredients[:5]])
                    if len(ingredients) > 5:
                        ingr_text += "..."
                    day_text += f"🍽 <i>{meal_type}</i>: <b>{title}</b>\n"
                    day_text += f"⏱ {time} | {diff}\n"
                    day_text += f"Ингредиенты: {ingr_text}\n\n"

                    all_ingredients.extend([safe_str(i).lower() for i in ingredients])
                else:
                    day_text += f"🍽 <i>{meal_type}</i>: (нет данных)\n"
            await message.answer(day_text, parse_mode="HTML")

        # Список покупок
        if all_ingredients:
            cleaned = []
            for ing in all_ingredients:
                ing = re.sub(r'\([^)]*\)', '', ing)
                ing = re.sub(r'\d+[\s,]*(г|кг|мл|л|ст\.?\s*л|ч\.?\s*л|шт|зуб|пуч|щеп|по вкусу)?', '', ing)
                ing = re.sub(r'[\/\.\-\d]+', '', ing)
                ing = ing.strip()
                if ing and len(ing) > 1:
                    cleaned.append(ing)
            unique = sorted(set(cleaned))
            if unique:
                shop_text = "🛒 <b>Список покупок:</b>\n" + "\n".join(f"• {i}" for i in unique)
                await message.answer(shop_text, parse_mode="HTML")

    except Exception as e:
        await message.answer(
            f"Меню сгенерировано, но не удалось отобразить:\n<pre>{raw_response[:3000]}</pre>",
            parse_mode="HTML"
        )

# ---------- Команды и кнопки ----------
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    prefs = await get_user_prefs(message.from_user.id)
    name = prefs.get("name") if prefs else None
    greeting = f"👋 С возвращением, {name}!" if name else "👋 Добро пожаловать в CookBot!"
    quest = await get_or_create_quest(message.from_user.id)
    quest_text = ""
    if not quest["completed"]:
        quest_text = f"\n\n🗡 <b>Квест дня:</b> {quest['description']}\n<i>Просто введите продукты, и если рецепт подойдёт, вы получите 50 очков!</i>"

    await message.answer(
        f"{greeting}\n\n"
        "Я твой личный шеф-помощник. Я умею:\n"
        "• Придумывать рецепты из твоих продуктов\n"
        "• Учитывать диету, аллергии и предпочтения\n"
        "• Сохранять любимые рецепты\n"
        "• Присылать блюдо дня\n"
        "• Давать ежедневные задания с наградами 🏆\n"
        "• Вести твой виртуальный холодильник 🧊\n"
        "• Составлять меню на день и неделю 📅"
        f"{quest_text}",
        parse_mode="HTML",
        reply_markup=make_main_kb(message.from_user.id)
    )

@router.message(F.text == "🍳 Придумать рецепт")
async def prompt_products(message: types.Message):
    quest = await get_or_create_quest(message.from_user.id)
    hint = ""
    if not quest["completed"]:
        hint = f"\n\n💡 <b>Квест дня:</b> {quest['description']}"
    await message.answer(
        "Напиши список продуктов через запятую.\n"
        "<i>Например: курица, лук, сметана, гречка</i>"
        f"{hint}",
        parse_mode="HTML"
    )

@router.message(F.text == "⭐ Мои избранные")
async def show_favorites(message: types.Message):
    favs = await get_favorites(message.from_user.id)
    if not favs:
        await message.answer("У вас пока нет избранных рецептов.", reply_markup=make_main_kb(message.from_user.id))
        return
    builder = InlineKeyboardBuilder()
    for i, rec in enumerate(favs):
        title = rec.get('title', f'Рецепт {i+1}')
        short_title = safe_str(title)[:30] + '…' if len(safe_str(title)) > 30 else safe_str(title)
        builder.row(InlineKeyboardButton(text=short_title, callback_data=f"view_fav:{i}"))
    builder.adjust(1)
    await message.answer("⭐ <b>Ваши избранные рецепты</b> (нажмите для деталей):", parse_mode="HTML", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("view_fav:"))
async def view_favorite(callback: types.CallbackQuery):
    index = int(callback.data.split(":")[1])
    favs = await get_favorites(callback.from_user.id)
    if index >= len(favs):
        await callback.answer("Рецепт не найден.", show_alert=True)
        return
    recipe = favs[index]
    text = format_recipe(recipe)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🗑 Удалить из избранного", callback_data=f"del_fav:{index}"))
    await callback.message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

@router.callback_query(F.data.startswith("del_fav:"))
async def delete_favorite(callback: types.CallbackQuery):
    index = int(callback.data.split(":")[1])
    favs = await get_favorites(callback.from_user.id)
    if index >= len(favs):
        await callback.answer("Рецепт уже удалён.", show_alert=True)
        return
    title = favs[index].get('title', '')
    success = await remove_favorite(callback.from_user.id, safe_str(title))
    if success:
        await callback.answer("Удалено!", show_alert=True)
        await callback.message.delete()
    else:
        await callback.answer("Ошибка удаления.", show_alert=True)

# ---------- Генератор рецептов ----------
@router.message(
    StateFilter(None),
    lambda msg: msg.text and not msg.text.startswith('/') and msg.text not in [
        "🍳 Придумать рецепт", "⭐ Мои избранные", "🧊 Мой холодильник", "📖 Дневник",
        "🏆 Статистика", "🔔 Блюдо дня", "⚙️ Настройки", "🗡 Квест дня",
        "📅 План на день", "📅 План на неделю", "ℹ️ О боте"
    ]
)
async def generate_recipe(message: types.Message):
    user_input = message.text.strip()
    if len(user_input) < 3:
        await message.answer("Пожалуйста, напиши хотя бы пару продуктов или запрос.")
        return

    fridge_triggers = [
        "из холодильника", "что приготовить из холодильника",
        "что есть в холодильнике", "из моих продуктов",
        "из того что есть", "приготовь из холодильника",
        "готовь из холодильника", "блюдо из холодильника",
        "что можно приготовить из холодильника", "используй холодильник",
        "из того, что в холодильнике", "из имеющихся продуктов",
        "из продуктов в холодильнике", "из доступных продуктов"
    ]
    use_fridge = any(trigger in user_input.lower() for trigger in fridge_triggers)

    if use_fridge:
        products = await get_fridge(message.from_user.id)
        if not products:
            await message.answer("Ваш холодильник пуст. Добавьте продукты через меню «🧊 Мой холодильник».")
            return
        await message.answer(f"👨‍🍳 Готовлю рецепт из: {', '.join(products)}...")
        recipe, raw_response = await generate_recipe_from_list(message.from_user.id, products)
    else:
        await message.answer("👨‍🍳 Готовлю рецепт...")
        prefs = await get_user_prefs(message.from_user.id)
        extra = ""
        if prefs:
            if prefs.get("diet") and prefs["diet"] != "Без ограничений":
                extra += f"Диета: {prefs['diet']}. "
            if prefs.get("allergies") and prefs["allergies"] != "Нет":
                extra += f"Аллергии: {prefs['allergies']}. "
            if prefs.get("dislikes") and prefs["dislikes"] != "Нет":
                extra += f"Не любит: {prefs['dislikes']}. "
            if prefs.get("skill"):
                extra += f"Уровень готовки: {prefs['skill']}. "
        recipe, raw_response = await get_recipe(user_input, extra_context=extra)

    if recipe is None:
        if raw_response == "RATE_LIMIT":
            await message.answer("⏳ Слишком много запросов. Попробуйте через минуту.")
        else:
            await message.answer("😔 Не удалось создать рецепт. Попробуйте изменить запрос.")
        return

    await set_last_recipe(message.from_user.id, recipe)
    await add_cook_log(message.from_user.id, recipe)
    await add_score(message.from_user.id, 10)

    quest = await get_or_create_quest(message.from_user.id)
    bonus_earned = False
    if not quest["completed"] and match_quest(recipe, quest["type"]):
        await complete_quest(message.from_user.id)
        await add_score(message.from_user.id, 50)
        bonus_earned = True

    if not await has_achievement(message.from_user.id, "fast_chef"):
        raw_time = recipe.get("cooking_time", "")
        cooking_time = safe_str(raw_time).lower()
        match = re.search(r'(\d+)\s*мин', cooking_time)
        if match:
            mins = int(match.group(1))
            if mins <= 15:
                await grant_achievement(message.from_user.id, "fast_chef")

    new_achievements = await check_and_grant_achievements(message.from_user.id)

    response_text = format_recipe(recipe)
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⭐ В избранное", callback_data="save_last"),
        InlineKeyboardButton(text="📤 Поделиться", switch_inline_query=safe_str(recipe.get("title", "")))
    )
    builder.row(
        InlineKeyboardButton(text="👍", callback_data="rate:1"),
        InlineKeyboardButton(text="👎", callback_data="rate:0")
    )
    await message.answer(response_text, parse_mode="HTML", reply_markup=builder.as_markup())

    notifications = []
    if bonus_earned:
        notifications.append("🎉 <b>Квест дня выполнен! +50 очков.</b>")
    if new_achievements:
        for ach in new_achievements:
            notifications.append(f"🏆 Новое достижение: {ach['icon']} {ach['name']} – {ach['desc']}")
    if not quest["completed"] and not bonus_earned:
        notifications.append(f"📌 <b>Квест дня:</b> {quest['description']} (не выполнен)")

    if notifications:
        await message.answer("\n".join(notifications), parse_mode="HTML")

@router.callback_query(F.data == "save_last")
async def save_last_recipe(callback: types.CallbackQuery):
    recipe = await get_last_recipe(callback.from_user.id)
    if recipe is None:
        await callback.answer("Не найден рецепт для сохранения.", show_alert=True)
        return
    await add_favorite(callback.from_user.id, recipe)
    await callback.answer("Добавлено в избранное! ⭐", show_alert=True)
    await callback.message.edit_reply_markup(reply_markup=None)

@router.callback_query(F.data.startswith("rate:"))
async def handle_rate(callback: types.CallbackQuery):
    recipe = await get_last_recipe(callback.from_user.id)
    if recipe is None:
        await callback.answer("Рецепт не найден.", show_alert=True)
        return
    rating_str = callback.data.split(":")[1]
    if rating_str not in ("1", "0"):
        await callback.answer()
        return
    rating = int(rating_str)
    title = recipe.get("title", "Без названия")
    await add_rating(callback.from_user.id, safe_str(title), rating)
    emoji = "👍" if rating else "👎"
    await callback.answer(f"Спасибо за оценку! {emoji}", show_alert=False)
    await callback.message.edit_reply_markup(reply_markup=None)

# ---------- Холодильник ----------
@router.message(F.text == "🧊 Мой холодильник")
async def fridge_menu(message: types.Message):
    products = await get_fridge(message.from_user.id)
    if products:
        text = "<b>Ваш холодильник:</b>\n" + "\n".join(f"• {p}" for p in products)
    else:
        text = "Ваш холодильник пуст. Добавьте продукты с помощью кнопки ниже."
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Добавить", callback_data="fridge_add"),
        InlineKeyboardButton(text="❌ Удалить", callback_data="fridge_remove")
    )
    await message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())

@router.callback_query(F.data == "fridge_add")
async def fridge_add_prompt(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Напишите название продукта (можно несколько через запятую):")
    await state.set_state(FridgeAdd.waiting_for_product)
    await callback.answer()

@router.callback_query(F.data == "fridge_remove")
async def fridge_remove_prompt(callback: types.CallbackQuery):
    products = await get_fridge(callback.from_user.id)
    if not products:
        await callback.answer("Холодильник пуст.", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    for p in products:
        builder.row(InlineKeyboardButton(text=f"❌ {p}", callback_data=f"fridge_del:{p}"))
    await callback.message.answer("Выберите продукт для удаления:", reply_markup=builder.as_markup())
    await callback.answer()

@router.callback_query(F.data.startswith("fridge_del:"))
async def fridge_delete(callback: types.CallbackQuery):
    product = callback.data.split(":", 1)[1]
    await remove_from_fridge(callback.from_user.id, product)
    await callback.answer(f"Удалено: {product}")
    products = await get_fridge(callback.from_user.id)
    if products:
        text = "<b>Ваш холодильник:</b>\n" + "\n".join(f"• {p}" for p in products)
    else:
        text = "Холодильник пуст."
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Добавить", callback_data="fridge_add"),
        InlineKeyboardButton(text="❌ Удалить", callback_data="fridge_remove")
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())

@router.message(FridgeAdd.waiting_for_product, F.text)
async def process_fridge_product(message: types.Message, state: FSMContext):
    text = message.text.strip().lower()
    if not text:
        await message.answer("Вы не ввели продукт. Попробуйте ещё раз.")
        return
    products = [p.strip() for p in text.split(",") if p.strip()]
    if not products:
        await message.answer("Не удалось распознать продукт.")
        return
    added = []
    for p in products:
        await add_to_fridge(message.from_user.id, p)
        added.append(p)
    await message.answer(f"✅ Добавлено в холодильник: {', '.join(added)}")
    await state.clear()
    await message.answer("Главное меню", reply_markup=make_main_kb(message.from_user.id))

# ---------- Дневник ----------
@router.message(F.text == "📖 Дневник")
async def show_diary(message: types.Message):
    log = await get_cook_log(message.from_user.id, limit=5)
    if not log:
        await message.answer("Ваш дневник пуст. Приготовьте что-нибудь!")
        return
    text = "<b>📖 Последние приготовленные блюда:</b>\n\n"
    for rec in log:
        title = rec.get('title', 'Без названия')
        text += f"• {safe_str(title)}\n"
    await message.answer(text, parse_mode="HTML")

# ---------- Статистика ----------
@router.message(F.text == "🏆 Статистика")
async def show_stats(message: types.Message):
    count = await get_cooked_count(message.from_user.id)
    score = await get_score(message.from_user.id)
    achievements = await get_user_achievements(message.from_user.id)
    completed_quests = await get_completed_quests_count(message.from_user.id)

    level = "Новичок"
    points_needed = 50
    if score >= 100:
        level = "Шеф"
        points_needed = 200
    elif score >= 50:
        level = "Умелец"
        points_needed = 100

    progress = min(score / points_needed * 100, 100) if points_needed > 0 else 100
    bar = "▓" * int(progress // 10) + "░" * (10 - int(progress // 10))

    ach_text = "\n".join([f"{a['icon']} {a['name']} – {a['desc']}" for a in achievements]) if achievements else "Нет достижений"
    text = (
        f"🏆 <b>Ваш уровень:</b> {level}\n"
        f"⭐ Очки: <b>{score}</b> / {points_needed}\n"
        f"[{bar}] {progress:.0f}%\n\n"
        f"🍳 Приготовлено блюд: <b>{count}</b>\n"
        f"⚔️ Выполнено квестов: <b>{completed_quests}</b>\n\n"
        f"<b>Достижения:</b>\n{ach_text}"
    )
    await message.answer(text, parse_mode="HTML")

# ---------- Квест дня ----------
@router.message(F.text == "🗡 Квест дня")
async def quest_command(message: types.Message):
    quest = await get_or_create_quest(message.from_user.id)
    if quest["completed"]:
        await message.answer("🎉 Вы уже выполнили сегодняшний квест! Приходите завтра за новым.")
    else:
        await message.answer(
            f"🗡 <b>Квест дня:</b> {quest['description']}\n\n"
            f"Приготовьте блюдо, соответствующее условию, и получите <b>50 очков</b>!\n"
            f"Просто введите продукты, и если рецепт подойдёт, квест засчитается автоматически.",
            parse_mode="HTML"
        )

# ---------- Блюдо дня ----------
@router.message(F.text == "🔔 Блюдо дня")
async def toggle_daily(message: types.Message):
    subs = await get_all_subscribers()
    if message.from_user.id in subs:
        await remove_subscriber(message.from_user.id)
        await message.answer("🔕 Вы отписались от блюда дня.")
    else:
        await add_subscriber(message.from_user.id)
        await message.answer("🔔 Теперь вы будете получать блюдо дня в 10:00 UTC! 🍽️")

# ---------- Настройки ----------
@router.message(F.text == "⚙️ Настройки")
async def settings_button(message: types.Message):
    await set_prefs_start(message)

# ---------- О боте ----------
@router.message(F.text == "ℹ️ О боте")
async def about_bot(message: types.Message):
    await message.answer(
        "🤖 <b>CookBot</b> — твой персональный шеф-помощник.\n\n"
        "Я использую искусственный интеллект, чтобы превратить твои продукты в изысканные блюда.\n"
        "Просто напиши мне список ингредиентов, и я пришлю пошаговый рецепт!\n\n"
        "🛠 Команды:\n"
        "/start – главное меню\n"
        "/setprefs – настройка диеты, аллергий, уровня\n"
        "/plan – планировщик меню\n"
        "/help – помощь\n\n"
        "Приятного аппетита! 🍽️",
        parse_mode="HTML",
        reply_markup=make_main_kb(message.from_user.id)
    )

# ---------- Планировщик ----------
@router.message(F.text == "📅 План на день")
async def plan_day_button(message: types.Message, state: FSMContext):
    await state.set_state(PlanWaiting.waiting_for_prefs)
    await state.update_data(period="day")
    await message.answer(
        "📅 <b>План на день</b>\n\n"
        "Напишите ваши пожелания (например, <i>без рыбы, больше овощей</i>) или нажмите <b>«🚫 Без пожеланий»</b>.",
        parse_mode="HTML",
        reply_markup=plan_waiting_kb()
    )

@router.message(F.text == "📅 План на неделю")
async def plan_week_button(message: types.Message, state: FSMContext):
    await state.set_state(WeekDaySelect.waiting_for_day)
    await state.update_data(period="week")
    await message.answer(
        "📅 <b>План на неделю</b>\n\n"
        "Выберите день недели, на который составить меню:",
        reply_markup=week_days_kb()
    )

# Обработчик выбора дня недели
@router.message(WeekDaySelect.waiting_for_day, F.text.in_(
    ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
))
async def week_day_selected(message: types.Message, state: FSMContext):
    day = message.text
    await state.update_data(specific_day=day)
    await state.set_state(PlanWaiting.waiting_for_prefs)
    await message.answer(
        f"📅 <b>План на {day}</b>\n\n"
        "Напишите ваши пожелания или нажмите <b>«🚫 Без пожеланий»</b>.",
        parse_mode="HTML",
        reply_markup=plan_waiting_kb()
    )

# Обработчики пожеланий
@router.message(PlanWaiting.waiting_for_prefs, F.text == "🚫 Без пожеланий")
async def plan_no_prefs(message: types.Message, state: FSMContext):
    data = await state.get_data()
    period = data.get("period", "day")
    specific_day = data.get("specific_day")
    await state.clear()
    await generate_plan(message, period, specific_day=specific_day)
    await message.answer("Главное меню", reply_markup=make_main_kb(message.from_user.id))

@router.message(PlanWaiting.waiting_for_prefs, F.text)
async def plan_with_prefs(message: types.Message, state: FSMContext):
    preferences = message.text.strip()
    data = await state.get_data()
    period = data.get("period", "day")
    specific_day = data.get("specific_day")
    await state.clear()
    await generate_plan(message, period, preferences, specific_day)
    await message.answer("Главное меню", reply_markup=make_main_kb(message.from_user.id))

# Команда /plan
@router.message(Command("plan"))
async def plan_command(message: types.Message):
    args = message.text.split()
    period = "day"
    preferences = ""
    if len(args) > 1:
        if args[1] in ["day", "week"]:
            period = args[1]
            preferences = " ".join(args[2:])
        else:
            preferences = " ".join(args[1:])
    await generate_plan(message, period, preferences)

# ---------- /setprefs ----------
@router.message(Command("setprefs"))
async def set_prefs_start(message: types.Message):
    prefs = await get_user_prefs(message.from_user.id) or {}
    current = (
        f"👤 <b>Мои настройки</b>\n"
        f"🥗 Диета: {prefs.get('diet', 'не задана')}\n"
        f"⚠️ Аллергии: {prefs.get('allergies', 'не заданы')}\n"
        f"🚫 Не любишь: {prefs.get('dislikes', 'не задано')}\n"
        f"👨‍🍳 Уровень: {prefs.get('skill', 'не задан')}\n\n"
        "Что хотите изменить?"
    )
    await message.answer(current, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🥗 Диета", callback_data="pref:diet"),
         InlineKeyboardButton(text="⚠️ Аллергии", callback_data="pref:allergies")],
        [InlineKeyboardButton(text="🚫 Нелюбимые", callback_data="pref:dislikes"),
         InlineKeyboardButton(text="👨‍🍳 Уровень", callback_data="pref:skill")]
    ]))

@router.callback_query(F.data.startswith("pref:"))
async def pref_callback(callback: types.CallbackQuery):
    field = callback.data.split(":")[1]
    if field == "diet":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Без ограничений", callback_data="set_diet:none")],
            [InlineKeyboardButton(text="Кето", callback_data="set_diet:keto")],
            [InlineKeyboardButton(text="Веган", callback_data="set_diet:vegan")],
            [InlineKeyboardButton(text="Вегетарианская", callback_data="set_diet:vegetarian")],
            [InlineKeyboardButton(text="Низкоуглеводная", callback_data="set_diet:lowcarb")]
        ])
        await callback.message.answer("Выбери диету:", reply_markup=kb)
    elif field == "allergies":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Нет", callback_data="set_allergies:none")],
            [InlineKeyboardButton(text="Орехи", callback_data="set_allergies:nuts")],
            [InlineKeyboardButton(text="Молочка", callback_data="set_allergies:dairy")],
            [InlineKeyboardButton(text="Глютен", callback_data="set_allergies:gluten")],
            [InlineKeyboardButton(text="Морепродукты", callback_data="set_allergies:seafood")]
        ])
        await callback.message.answer("Выбери аллергены:", reply_markup=kb)
    elif field == "dislikes":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Нет", callback_data="set_dislikes:none")],
            [InlineKeyboardButton(text="Лук", callback_data="set_dislikes:onion")],
            [InlineKeyboardButton(text="Рыба", callback_data="set_dislikes:fish")],
            [InlineKeyboardButton(text="Брокколи", callback_data="set_dislikes:broccoli")],
            [InlineKeyboardButton(text="Чеснок", callback_data="set_dislikes:garlic")]
        ])
        await callback.message.answer("Что не любишь?", reply_markup=kb)
    elif field == "skill":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Новичок", callback_data="set_skill:beginner")],
            [InlineKeyboardButton(text="Средний", callback_data="set_skill:intermediate")],
            [InlineKeyboardButton(text="Продвинутый", callback_data="set_skill:advanced")]
        ])
        await callback.message.answer("Твой уровень:", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data.startswith("set_diet:"))
async def set_diet(callback: types.CallbackQuery):
    key = callback.data.split(":", 1)[1]
    diet_map = {"none": "Без ограничений", "keto": "Кето", "vegan": "Веган", "vegetarian": "Вегетарианская", "lowcarb": "Низкоуглеводная"}
    diet = diet_map.get(key, key)
    await update_user_prefs(callback.from_user.id, diet=diet)
    await callback.answer(f"Диета сохранена: {diet}")
    await callback.message.edit_text("✅ Настройки обновлены! Используй /setprefs для просмотра.", reply_markup=None)

@router.callback_query(F.data.startswith("set_allergies:"))
async def set_allergies(callback: types.CallbackQuery):
    key = callback.data.split(":", 1)[1]
    allergies_map = {"none": "Нет", "nuts": "Орехи", "dairy": "Молочка", "gluten": "Глютен", "seafood": "Морепродукты"}
    value = allergies_map.get(key, key)
    await update_user_prefs(callback.from_user.id, allergies=value)
    await callback.answer(f"Аллергии сохранены: {value}")
    await callback.message.edit_text("✅ Настройки обновлены! Используй /setprefs для просмотра.", reply_markup=None)

@router.callback_query(F.data.startswith("set_dislikes:"))
async def set_dislikes(callback: types.CallbackQuery):
    key = callback.data.split(":", 1)[1]
    dislikes_map = {"none": "Нет", "onion": "Лук", "fish": "Рыба", "broccoli": "Брокколи", "garlic": "Чеснок"}
    value = dislikes_map.get(key, key)
    await update_user_prefs(callback.from_user.id, dislikes=value)
    await callback.answer(f"Нелюбимые сохранены: {value}")
    await callback.message.edit_text("✅ Настройки обновлены! Используй /setprefs для просмотра.", reply_markup=None)

@router.callback_query(F.data.startswith("set_skill:"))
async def set_skill(callback: types.CallbackQuery):
    key = callback.data.split(":", 1)[1]
    skill_map = {"beginner": "Новичок", "intermediate": "Средний", "advanced": "Продвинутый"}
    skill = skill_map.get(key, key)
    await update_user_prefs(callback.from_user.id, skill=skill)
    await callback.answer(f"Уровень сохранён: {skill}")
    await callback.message.edit_text("✅ Настройки обновлены! Используй /setprefs для просмотра.", reply_markup=None)

# ---------- Инлайн-режим ----------
@router.inline_query()
async def inline_recipe(inline_query: types.InlineQuery):
    query = inline_query.query.strip()
    if not query or len(query) < 3:
        return

    recipe, _ = await get_recipe(query)
    if recipe is None:
        return

    title = safe_str(recipe.get("title", "Рецепт"))
    time = safe_str(recipe.get("cooking_time", "? мин"))
    description = f"⏱ {time} | {safe_str(recipe.get('difficulty', ''))}"
    ingredients = "\n".join(f"• {safe_str(ing)}" for ing in recipe.get("ingredients", []))
    steps = "\n".join(f"{i+1}. {safe_str(step)}" for i, step in enumerate(recipe.get("steps", [])))
    full_text = f"🍽 <b>{title}</b>\n⏱ {time}\n\n<b>Ингредиенты:</b>\n{ingredients}\n\n<b>Приготовление:</b>\n{steps}"
    tip = safe_str(recipe.get("tip", ""))
    if tip:
        full_text += f"\n\n💡 {tip}"

    input_content = InputTextMessageContent(full_text, parse_mode="HTML")
    result_id = hashlib.md5(query.encode()).hexdigest()

    result = InlineQueryResultArticle(
        id=result_id,
        title=title,
        description=description,
        input_message_content=input_content
    )

    await inline_query.answer([result], cache_time=10)
