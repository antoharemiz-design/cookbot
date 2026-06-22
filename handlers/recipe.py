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
    add_to_fridge, remove_from_fridge, get_fridge,
    update_taste_prefs, get_taste_summary
)
import logging
import re
import hashlib
import asyncio

COLLECTION_PROMPTS = {
    "new_year": "Составь меню на один день в стиле новогоднего стола. Блюда должны быть праздничными, с традиционными новогодними ингредиентами (оливье, мандарины, шампанское и т.д.).",
    "vegan_week": "Составь веганское меню на один день (завтрак, обед, ужин). Все блюда должны быть без мяса, рыбы, яиц и молочных продуктов.",
    "fast_breakfast": "Составь меню на один день, где каждый завтрак, обед и ужин готовятся не дольше 15 минут.",
    "italian_dinner": "Составь меню на один день в итальянском стиле (паста, ризотто, брускетты, тирамису и т.д.).",
    "kids": "Составь детское меню на один день (завтрак, обед, ужин). Блюда должны нравиться детям, быть простыми и безопасными.",
    "soups": "Составь меню на один день, состоящее из разных супов (завтрак — лёгкий суп, обед — сытный, ужин — суп-пюре или холодный).",
    "meat": "Составь меню на один день с акцентом на мясные блюда (стейки, котлеты, гуляш и т.д.).",
    "asian": "Составь меню на один день в азиатском стиле (суши, вок, том-ям, лапша и т.д.).",
}

router = Router()
logging.basicConfig(level=logging.INFO)

# Состояния
class FridgeAdd(StatesGroup):
    waiting_for_product = State()

class PlanWaiting(StatesGroup):
    waiting_for_prefs = State()
    waiting_for_options = State()

# ---------- Главное меню ----------
def make_main_kb(user_id: int):
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🍳 Придумать рецепт"), KeyboardButton(text="⭐ Мои избранные")],
            [KeyboardButton(text="🧊 Мой холодильник"), [KeyboardButton(text="⏱ Быстрый ужин"), 
            [KeyboardButton(text="📖 Дневник"), KeyboardButton(text="🔔 Блюдо дня")],
            [KeyboardButton(text="🏆 Статистика"), KeyboardButton(text="🗡 Квест дня")],
            [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="🎯 Коллекции")],
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
    # Персональные предпочтения
    taste_summary = await get_taste_summary(user_id)
    if taste_summary:
        extra += taste_summary
    user_input = ", ".join(products)
    return await get_recipe(user_input, extra_context=extra)

# ---------- Общая функция планировщика ----------
async def generate_plan(message: types.Message, period: str, preferences: str = "",
                        specific_day: str = None, silent: bool = False,
                        add_wine: bool = False, add_kbju: bool = False,
                        rotate_cuisines: bool = False):
    if not silent:
        if specific_day:
            display_name = specific_day
        elif period in ["day", "week"]:
            display_name = "день" if period == "day" else "неделю"
        else:
            display_name = period
        await message.answer(f"📅 Генерирую меню на {display_name}...")

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
    if preferences and not preferences.startswith("Составь меню"):
        extra += f"Дополнительные пожелания: {preferences}. "

    fridge_products = await get_fridge(message.from_user.id)
    if fridge_products:
        extra += f"В холодильнике есть: {', '.join(fridge_products)}. "

    if add_wine:
        extra += "К каждому ужину предложи подходящее вино. "
    if add_kbju:
        extra += "Для каждого рецепта укажи примерную калорийность и БЖУ (белки, жиры, углеводы). "
    if rotate_cuisines and period == "week":
        extra += "Каждый день должен быть посвящён разной кухне: итальянская, японская, мексиканская, индийская, французская, тайская, русская, грузинская. Не повторяй кухни. "

    if preferences and preferences.startswith("Составь меню"):
        base_prompt = preferences
    else:
        base_prompt = None

    if specific_day or period == "day":
        if specific_day:
            day_names = [specific_day]
        else:
            day_names = [] if base_prompt else ["Сегодня"]

        prompts = []
        if base_prompt:
            prompt = base_prompt + " " + extra
            prompt += (
                'Ответь в формате JSON: { "days": [ { "day": "Название дня", "meals": [ '
                '{ "type": "завтрак/обед/ужин", "recipe": { "title": "...", "cooking_time": "...", '
                '"difficulty": "...", "ingredients": ["..."], "steps": ["..."], "tip": "...", '
                '"wine": "рекомендованное вино (только если запрошено)", '
                '"nutrition": { "calories": "...", "protein": "...", "fat": "...", "carbs": "..." } } } ] } ] }'
            )
            prompts.append(prompt)
        else:
            for day in day_names:
                prompt = f"Составь меню на {day} (завтрак, обед, ужин). Для каждого приёма пищи предложи полноценный рецепт. "
                prompt += extra
                prompt += (
                    'Ответь в формате JSON: { "days": [ { "day": "Название дня", "meals": [ '
                    '{ "type": "завтрак/обед/ужин", "recipe": { "title": "...", "cooking_time": "...", '
                    '"difficulty": "...", "ingredients": ["..."], "steps": ["..."], "tip": "...", '
                    '"wine": "рекомендованное вино (только если запрошено)", '
                    '"nutrition": { "calories": "...", "protein": "...", "fat": "...", "carbs": "..." } } } ] } ] }'
                )
                prompts.append(prompt)
        await process_prompts(message, prompts)

    elif period == "week":
        days_of_week = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
        cuisines = ["итальянская", "японская", "мексиканская", "индийская", "французская", "тайская", "русская"]
        day_cuisines = {}
        if rotate_cuisines:
            for i, day in enumerate(days_of_week):
                day_cuisines[day] = cuisines[i % len(cuisines)]

        prompts = []
        for day in days_of_week:
            if base_prompt:
                prompt = base_prompt + " " + extra
            else:
                prompt = f"Составь меню на {day} (завтрак, обед, ужин). Для каждого приёма пищи предложи полноценный рецепт. "
                prompt += extra
                if day_cuisines:
                    prompt += f" Кухня дня: {day_cuisines[day]}. "
            prompt += (
                'Ответь в формате JSON: { "days": [ { "day": "Название дня", "meals": [ '
                '{ "type": "завтрак/обед/ужин", "recipe": { "title": "...", "cooking_time": "...", '
                '"difficulty": "...", "ingredients": ["..."], "steps": ["..."], "tip": "...", '
                '"wine": "рекомендованное вино (только если запрошено)", '
                '"nutrition": { "calories": "...", "protein": "...", "fat": "...", "carbs": "..." } } } ] } ] }'
            )
            prompts.append(prompt)
        await process_prompts(message, prompts)
    else:
        if base_prompt:
            prompt = base_prompt + " " + extra
        else:
            prompt = f"Составь меню на {period} (завтрак, обед, ужин). " + extra
        prompt += (
            'Ответь в формате JSON: { "days": [ { "day": "Название дня", "meals": [ '
            '{ "type": "завтрак/обед/ужин", "recipe": { "title": "...", "cooking_time": "...", '
            '"difficulty": "...", "ingredients": ["..."], "steps": ["..."], "tip": "...", '
            '"wine": "рекомендованное вино (только если запрошено)", '
            '"nutrition": { "calories": "...", "protein": "...", "fat": "...", "carbs": "..." } } } ] } ] }'
        )
        await process_prompts(message, [prompt])


async def process_prompts(message: types.Message, prompts: list[str]):
    """Обрабатывает список промптов, генерирует меню и выводит результат."""
    all_ingredients = []
    for prompt in prompts:
        recipe, raw_response = await get_recipe(prompt)
        if recipe is None:
            await message.answer(f"😔 Не удалось сгенерировать меню для одного из дней.\nОтвет модели:\n<pre>{safe_str(raw_response)[:1000]}</pre>", parse_mode="HTML")
            continue

        try:
            days = recipe.get("days", [])
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
                        day_text += f"Ингредиенты: {ingr_text}\n"

                        if meal_type.lower() == "ужин" and rec.get("wine"):
                            day_text += f"🍷 Вино: {safe_str(rec['wine'])}\n"

                        nutrition = rec.get("nutrition")
                        if nutrition:
                            cal = safe_str(nutrition.get("calories", ""))
                            prot = safe_str(nutrition.get("protein", ""))
                            fat = safe_str(nutrition.get("fat", ""))
                            carb = safe_str(nutrition.get("carbs", ""))
                            if cal or prot or fat or carb:
                                day_text += f"📊 КБЖУ: {cal} ккал, Б: {prot}, Ж: {fat}, У: {carb}\n"

                        day_text += "\n"
                        all_ingredients.extend([safe_str(i).lower() for i in ingredients])
                    else:
                        day_text += f"🍽 <i>{meal_type}</i>: (нет данных)\n"
                await message.answer(day_text, parse_mode="HTML")
        except Exception as e:
            await message.answer(f"Меню для одного из дней повреждено:\n<pre>{safe_str(raw_response)[:1000]}</pre>", parse_mode="HTML")

    # Генерация общего списка покупок (после всех дней)
    if all_ingredients:
        cleaned = []
            normalize = {
                "помидора": "помидор", "помидоры": "помидор", "помидору": "помидор",
                "огурца": "огурец", "огурцы": "огурец", "огурцу": "огурец",
                "яйца": "яйца", "яйцо": "яйцо", "яйцу": "яйцо",
                "картофелины": "картофель", "картофеля": "картофель", "картофелю": "картофель",
                "средних картофелины": "картофель",
                "луковицы": "лук", "луковица": "лук", "лука": "лук", "луку": "лук",
                "чеснока": "чеснок", "чеснок": "чеснок", "чесноку": "чеснок",
                "базилика": "базилик", "базилик": "базилик", "базилику": "базилик",
                "зелени": "зелень", "зелень": "зелень",
                "рыбы": "рыба", "рыба": "рыба", "рыбу": "рыба",
                "курицы": "курица", "курица": "курица", "курицу": "курица",
                "говядины": "говядина", "говядина": "говядина", "говядину": "говядина",
                "свинины": "свинина", "свинина": "свинина", "свинину": "свинина",
                "сыра": "сыр", "сыр": "сыр", "сыру": "сыр",
                "риса": "рис", "рис": "рис", "рису": "рис",
                "моркови": "морковь", "морковь": "морковь",
                "масла": "масло", "масло": "масло", "маслу": "масло",
                "соли": "соль", "соль": "соль",
                "перца": "перец", "перец": "перец",
                "воды": "вода", "вода": "вода",
                "бульона": "бульон", "бульон": "бульон",
                "муки": "мука", "мука": "мука",
                "сахара": "сахар", "сахар": "сахар",
                "меда": "мёд", "мед": "мёд", "меду": "мёд",
                "овощей": "овощи", "овощи": "овощи",
                "фруктов": "фрукты", "фрукты": "фрукты",
                "орехов": "орехи", "орехи": "орехи",
                "соуса карри": "соус карри",
                "овсяных хлопьев": "овсяные хлопья",
                "куриная грудка": "курица", "куриной грудки": "курица",
                "филе рыбы": "рыба",
                "шампиньонов": "шампиньоны", "шампиньоны": "шампиньоны",
            }
        for ing in all_ingredients:
            ing = re.sub(r'\([^)]*\)', '', ing)
            ing = re.sub(r'\d+[\s,]*', '', ing)
            ing = re.sub(r'\b(г|кг|мл|л|ст\.?\s*л|ч\.?\s*л|шт|зуб|пуч|щеп|по вкусу|зубчик|зубчика|веточка|веточки|пучок|пучка|щепотка|щепотки|средних|больших|маленьких|для взбивания|размягчённого)\b', '', ing, flags=re.IGNORECASE)
            ing = re.sub(r'[\/\.\,\-\d]+', ' ', ing)
            ing = ing.strip()
            ing = normalize.get(ing, ing)
            if ing and len(ing) > 1 and ing not in ["средний", "большой", "маленький"]:
                cleaned.append(ing)

        unique = sorted(set(cleaned))
        if unique:
            shop_text = "🛒 <b>Список покупок:</b>\n" + "\n".join(f"• {i}" for i in unique)
            await message.answer(shop_text, parse_mode="HTML")

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

@router.message(F.text == "⏱ Быстрый ужин")
async def quick_dinner(message: types.Message):
    await message.answer("👨‍🍳 Ищу быстрый рецепт...")
    fridge_products = await get_fridge(message.from_user.id)
    if fridge_products:
        user_input = ", ".join(fridge_products) + " приготовь быстрое блюдо до 20 минут"
    else:
        user_input = "придумай быстрый ужин до 20 минут из простых продуктов"

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
    taste_summary = await get_taste_summary(message.from_user.id)
    if taste_summary:
        extra += taste_summary

    recipe, raw_response = await get_recipe(user_input, extra_context=extra)
    if recipe is None:
        await message.answer("😔 Не удалось найти быстрый рецепт. Попробуйте позже.")
        return

    await set_last_recipe(message.from_user.id, recipe)

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
    builder.row(
        InlineKeyboardButton(text="📝 Я приготовил!", callback_data="cook_done")
    )
    await message.answer(response_text, parse_mode="HTML", reply_markup=builder.as_markup())

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
        "📅 План на день", "📅 План на неделю", "🎯 Коллекции", "ℹ️ О боте",
        "⏱ Быстрый ужин"
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
        # Добавляем персональные предпочтения
        taste_summary = await get_taste_summary(message.from_user.id)
        if taste_summary:
            extra += taste_summary
        recipe, raw_response = await get_recipe(user_input, extra_context=extra)

    if recipe is None:
        if raw_response == "RATE_LIMIT":
            await message.answer("⏳ Слишком много запросов. Попробуйте через минуту.")
        else:
            await message.answer("😔 Не удалось создать рецепт. Попробуйте изменить запрос.")
        return

    await set_last_recipe(message.from_user.id, recipe)

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
    builder.row(
        InlineKeyboardButton(text="📝 Я приготовил!", callback_data="cook_done")
    )
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
    # Обновляем предпочтения пользователя
    await update_taste_prefs(callback.from_user.id, recipe, rating)
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

    # Персональные предпочтения
    taste_prefs = await get_user_prefs(message.from_user.id)
    taste_text = ""
    if taste_prefs:
        import json
        fav_cuisines = json.loads(taste_prefs.get("favorite_cuisines", "{}") or "{}")
        fav_ingredients = json.loads(taste_prefs.get("favorite_ingredients", "{}") or "{}")
        if fav_cuisines or fav_ingredients:
            taste_text = "\n\n<b>🍽 Ваши предпочтения:</b>\n"
            if fav_cuisines:
                sorted_c = sorted(fav_cuisines.items(), key=lambda x: x[1], reverse=True)[:3]
                taste_text += "Кухни: " + ", ".join(f"{c} ({v})" for c, v in sorted_c) + "\n"
            if fav_ingredients:
                sorted_i = sorted(fav_ingredients.items(), key=lambda x: x[1], reverse=True)[:5]
                taste_text += "Ингредиенты: " + ", ".join(f"{i} ({v})" for i, v in sorted_i)

    text = (
        f"🏆 <b>Ваш уровень:</b> {level}\n"
        f"⭐ Очки: <b>{score}</b> / {points_needed}\n"
        f"[{bar}] {progress:.0f}%\n\n"
        f"🍳 Приготовлено блюд: <b>{count}</b>\n"
        f"⚔️ Выполнено квестов: <b>{completed_quests}</b>\n\n"
        f"<b>Достижения:</b>\n{ach_text}"
        f"{taste_text}"
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
    await state.clear()  # очищаем старые данные
    await state.set_state(PlanWaiting.waiting_for_prefs)
    await state.update_data(period="day")
    await message.answer(
        "📅 <b>План на день</b>\n\n"
        "Напишите ваши пожелания (например, <i>без рыбы, больше овощей</i>) или нажмите <b>«🚫 Без пожеланий»</b>.",
        parse_mode="HTML",
        reply_markup=plan_waiting_kb()
    )

@router.message(F.text == "📅 План на неделю")
async def plan_week_button(message: types.Message):
    builder = InlineKeyboardBuilder()
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    for day in days:
        builder.row(InlineKeyboardButton(text=day, callback_data=f"plan_day:{day}"))
    await message.answer(
        "📅 <b>План на неделю</b>\n\nВыберите день недели, на который составить меню:",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data.startswith("plan_day:"))
async def plan_specific_day(callback: types.CallbackQuery, state: FSMContext):
    day = callback.data.split(":")[1]
    await state.set_state(PlanWaiting.waiting_for_prefs)
    await state.update_data(period="day", specific_day=day)
    await callback.message.answer(
        f"📅 <b>План на {day}</b>\n\n"
        "Напишите ваши пожелания или нажмите «🚫 Без пожеланий».",
        parse_mode="HTML",
        reply_markup=plan_waiting_kb()
    )
    await callback.answer()

@router.message(PlanWaiting.waiting_for_prefs, F.text == "🚫 Без пожеланий")
async def plan_no_prefs(message: types.Message, state: FSMContext):
    data = await state.get_data()
    period = data.get("period", "day")
    await state.update_data(preferences="", period=period,
                            add_wine=False, add_kbju=False, rotate_cuisines=False)
    await state.set_state(PlanWaiting.waiting_for_options)
    await show_options_message(message, state, period)

@router.message(PlanWaiting.waiting_for_prefs, F.text)
async def plan_with_prefs(message: types.Message, state: FSMContext):
    preferences = message.text.strip()
    data = await state.get_data()
    period = data.get("period", "day")
    await state.update_data(preferences=preferences, period=period,
                            add_wine=False, add_kbju=False, rotate_cuisines=False)
    await state.set_state(PlanWaiting.waiting_for_options)
    await show_options_message(message, state, period)

async def show_options_message(message: types.Message, state: FSMContext, period: str):
    data = await state.get_data()
    add_wine = data.get("add_wine", False)
    add_kbju = data.get("add_kbju", False)
    rotate = data.get("rotate_cuisines", False)

    wine_text = "✅ Вино" if add_wine else "🍷 Вино"
    kbju_text = "✅ КБЖУ" if add_kbju else "📊 КБЖУ"
    rotate_text = "✅ Чередовать кухни" if rotate else "🌍 Чередовать кухни"

    buttons = [
        [InlineKeyboardButton(text=wine_text, callback_data="toggle_wine")],
        [InlineKeyboardButton(text=kbju_text, callback_data="toggle_kbju")],
    ]
    if period == "week":
        buttons.append([InlineKeyboardButton(text=rotate_text, callback_data="toggle_rotate")])
    buttons.append([InlineKeyboardButton(text="▶️ Продолжить", callback_data="start_plan")])

    await message.answer("Выберите дополнительные опции:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

async def update_options_message(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    add_wine = data.get("add_wine", False)
    add_kbju = data.get("add_kbju", False)
    rotate = data.get("rotate_cuisines", False)
    period = data.get("period", "day")

    wine_text = "✅ Вино" if add_wine else "🍷 Вино"
    kbju_text = "✅ КБЖУ" if add_kbju else "📊 КБЖУ"
    rotate_text = "✅ Чередовать кухни" if rotate else "🌍 Чередовать кухни"

    buttons = [
        [InlineKeyboardButton(text=wine_text, callback_data="toggle_wine")],
        [InlineKeyboardButton(text=kbju_text, callback_data="toggle_kbju")],
    ]
    if period == "week":
        buttons.append([InlineKeyboardButton(text=rotate_text, callback_data="toggle_rotate")])
    buttons.append([InlineKeyboardButton(text="▶️ Продолжить", callback_data="start_plan")])

    await callback.message.edit_text("Выберите дополнительные опции:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data == "toggle_wine")
async def toggle_wine(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    new_val = not data.get("add_wine", False)
    await state.update_data(add_wine=new_val)
    await update_options_message(callback, state)
    await callback.answer()

@router.callback_query(F.data == "toggle_kbju")
async def toggle_kbju(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    new_val = not data.get("add_kbju", False)
    await state.update_data(add_kbju=new_val)
    await update_options_message(callback, state)
    await callback.answer()

@router.callback_query(F.data == "toggle_rotate")
async def toggle_rotate(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    new_val = not data.get("rotate_cuisines", False)
    await state.update_data(rotate_cuisines=new_val)
    await update_options_message(callback, state)
    await callback.answer()

@router.callback_query(F.data == "start_plan")
async def start_plan(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    period = data.get("period", "day")
    specific_day = data.get("specific_day")
    preferences = data.get("preferences", "")
    add_wine = data.get("add_wine", False)
    add_kbju = data.get("add_kbju", False)
    rotate_cuisines = data.get("rotate_cuisines", False)

    await state.clear()
    await callback.message.edit_text("Запускаю генерацию плана...")
    await generate_plan(callback.message, period, preferences=preferences,
                        specific_day=specific_day,
                        add_wine=add_wine, add_kbju=add_kbju,
                        rotate_cuisines=rotate_cuisines,
                        silent=True)
    await callback.message.answer("Главное меню", reply_markup=make_main_kb(callback.from_user.id))
    await callback.answer()

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

@router.callback_query(F.data == "cook_done")
async def mark_as_cooked(callback: types.CallbackQuery):
    recipe = await get_last_recipe(callback.from_user.id)
    if recipe is None:
        await callback.answer("Рецепт не найден.", show_alert=True)
        return

    await add_cook_log(callback.from_user.id, recipe)
    await add_score(callback.from_user.id, 10)

    quest = await get_or_create_quest(callback.from_user.id)
    bonus_earned = False
    if not quest["completed"] and match_quest(recipe, quest["type"]):
        await complete_quest(callback.from_user.id)
        await add_score(callback.from_user.id, 50)
        bonus_earned = True

    if not await has_achievement(callback.from_user.id, "fast_chef"):
        raw_time = recipe.get("cooking_time", "")
        cooking_time = safe_str(raw_time).lower()
        match = re.search(r'(\d+)\s*мин', cooking_time)
        if match:
            mins = int(match.group(1))
            if mins <= 15:
                await grant_achievement(callback.from_user.id, "fast_chef")

    new_achievements = await check_and_grant_achievements(callback.from_user.id)

    notifications = []
    if bonus_earned:
        notifications.append("🎉 <b>Квест дня выполнен! +50 очков.</b>")
    if new_achievements:
        for ach in new_achievements:
            notifications.append(f"🏆 Новое достижение: {ach['icon']} {ach['name']} – {ach['desc']}")
    if not quest["completed"] and not bonus_earned:
        notifications.append(f"📌 <b>Квест дня:</b> {quest['description']} (не выполнен)")

    if notifications:
        await callback.message.answer("\n".join(notifications), parse_mode="HTML")

    await callback.answer("Записано в дневник! 📖", show_alert=True)
    await callback.message.edit_reply_markup(reply_markup=None)

# ---------- Коллекции ----------
@router.message(F.text == "🎯 Коллекции")
async def collections_menu(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎄 Новогодний стол", callback_data="collection:new_year")],
        [InlineKeyboardButton(text="🥗 Веганская неделя", callback_data="collection:vegan_week")],
        [InlineKeyboardButton(text="⏱️ Завтраки за 15 минут", callback_data="collection:fast_breakfast")],
        [InlineKeyboardButton(text="🍝 Итальянский ужин", callback_data="collection:italian_dinner")],
        [InlineKeyboardButton(text="🧒 Детское меню", callback_data="collection:kids")],
        [InlineKeyboardButton(text="🍲 Супы со всего мира", callback_data="collection:soups")],
        [InlineKeyboardButton(text="🥩 Мясные блюда", callback_data="collection:meat")],
        [InlineKeyboardButton(text="🍣 Азиатская кухня", callback_data="collection:asian")],
    ])
    await message.answer("🎯 <b>Тематические коллекции</b>\n\nВыберите подборку, и я составлю меню на день:", parse_mode="HTML", reply_markup=kb)

@router.callback_query(F.data.startswith("collection:"))
async def handle_collection(callback: types.CallbackQuery):
    key = callback.data.split(":")[1]
    base_prompt = COLLECTION_PROMPTS.get(key, "Составь меню на один день.")
    prompt = base_prompt + " Верни JSON ровно с одним днём (без названия дня или с названием темы)."
    await callback.message.answer("📅 Генерирую тематическое меню...")
    await generate_plan(callback.message, "day", preferences=prompt, silent=True)
    await callback.answer()

# ---------- Инлайн-режим ----------
@router.inline_query()
async def inline_recipe(inline_query: types.InlineQuery):
    query = inline_query.query.strip()
    if not query or len(query) < 3:
        return

    recipes = []
    for attempt in range(3):
        extra_context = f"Вариант {attempt+1}. Предложи блюдо, отличное от предыдущих: "
        recipe, _ = await get_recipe(query, extra_context=extra_context)
        if recipe and recipe not in recipes:
            recipes.append(recipe)
        if len(recipes) >= 5:
            break

    if not recipes:
        return

    results = []
    for recipe in recipes:
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
        result_id = hashlib.md5(f"{query}_{title}".encode()).hexdigest()
        results.append(
            InlineQueryResultArticle(
                id=result_id,
                title=title,
                description=description,
                input_message_content=input_content
            )
        )

    await inline_query.answer(results, cache_time=5)
