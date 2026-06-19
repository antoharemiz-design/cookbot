from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from services.ai import get_recipe
from database.db import (
    add_favorite, get_favorites, remove_favorite,
    set_last_recipe, get_last_recipe, get_user_prefs, update_user_prefs,
    add_subscriber, remove_subscriber, get_all_subscribers, add_rating,
    add_cook_log, get_cook_log, get_or_create_quest, complete_quest,
    check_and_grant_achievements, get_user_achievements, get_cooked_count,
    grant_achievement, ACHIEVEMENTS
)
import logging

router = Router()
logging.basicConfig(level=logging.INFO)

# Главное меню (добавлены Дневник и Статистика)
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🍳 Придумать рецепт"), KeyboardButton(text="⭐ Мои избранные")],
        [KeyboardButton(text="📖 Дневник"), KeyboardButton(text="🏆 Статистика")],
        [KeyboardButton(text="🔔 Блюдо дня"), KeyboardButton(text="⚙️ Настройки")],
        [KeyboardButton(text="🗡 Квест дня"), KeyboardButton(text="ℹ️ О боте")]
    ],
    resize_keyboard=True,
    input_field_placeholder="Что хотите приготовить?"
)

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    prefs = await get_user_prefs(message.from_user.id)
    name = prefs.get("name") if prefs else None
    if name:
        greeting = f"👋 С возвращением, {name}!"
    else:
        greeting = "👋 Добро пожаловать в CookBot!"
    await message.answer(
        f"{greeting}\n\n"
        "Я твой личный шеф-помощник. Я умею:\n"
        "• Придумывать рецепты из твоих продуктов\n"
        "• Учитывать диету, аллергии и предпочтения\n"
        "• Сохранять любимые рецепты\n"
        "• Присылать блюдо дня\n"
        "• Давать ежедневные задания и награды 🏆\n\n"
        "Чтобы я знал твои вкусы, нажми <b>⚙️ Настройки</b> или просто напиши, что есть в холодильнике!\n"
        "<i>Например: курица, лук, сметана, гречка</i>",
        parse_mode="HTML",
        reply_markup=main_kb
    )

@router.message(F.text == "🍳 Придумать рецепт")
async def prompt_products(message: types.Message):
    await message.answer(
        "Напиши список продуктов через запятую.\n"
        "<i>Например: курица, лук, сметана, гречка</i>\n\n"
        "Или просто скажи: «хочу итальянский ужин»",
        parse_mode="HTML"
    )

@router.message(F.text == "⭐ Мои избранные")
async def show_favorites(message: types.Message):
    favs = await get_favorites(message.from_user.id)
    if not favs:
        await message.answer("У вас пока нет избранных рецептов.", reply_markup=main_kb)
        return
    builder = InlineKeyboardBuilder()
    for i, rec in enumerate(favs):
        title = rec.get('title', f'Рецепт {i+1}')
        short_title = title[:30] + '…' if len(title) > 30 else title
        builder.row(InlineKeyboardButton(
            text=short_title,
            callback_data=f"view_fav:{i}"
        ))
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
    success = await remove_favorite(callback.from_user.id, title)
    if success:
        await callback.answer("Удалено!", show_alert=True)
        await callback.message.delete()
    else:
        await callback.answer("Ошибка удаления.", show_alert=True)

# Генератор рецептов
@router.message(
    lambda msg: msg.text and not msg.text.startswith('/') and msg.text not in [
        "🍳 Придумать рецепт", "⭐ Мои избранные", "📖 Дневник", "🏆 Статистика",
        "🔔 Блюдо дня", "⚙️ Настройки", "🗡 Квест дня", "ℹ️ О боте"
    ]
)
async def generate_recipe(message: types.Message):
    user_input = message.text.strip()
    if len(user_input) < 3:
        await message.answer("Пожалуйста, напиши хотя бы пару продуктов или запрос.")
        return
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
    # Сохраняем в last_recipe, cook_log
    await set_last_recipe(message.from_user.id, recipe)
    await add_cook_log(message.from_user.id, recipe)
    # Проверяем квест
    quest = await get_or_create_quest(message.from_user.id)
    quest_completed_today = quest["completed"]
    # Проверяем достижения
    new_ach = await check_and_grant_achievements(message.from_user.id)
    response_text = format_recipe(recipe)
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⭐ В избранное", callback_data="save_last"),
        InlineKeyboardButton(text="📤 Поделиться", switch_inline_query=recipe.get("title", ""))
    )
    builder.row(
        InlineKeyboardButton(text="👍", callback_data=f"rate:{recipe['title']}:1"),
        InlineKeyboardButton(text="👎", callback_data=f"rate:{recipe['title']}:0")
    )
    await message.answer(response_text, parse_mode="HTML", reply_markup=builder.as_markup())
    # Если квест не выполнен, напомним
    if not quest_completed_today:
        await message.answer(f"📌 <b>Квест дня:</b> {quest['description']}\nНажми <b>🗡 Квест дня</b> после выполнения, чтобы получить баллы!", parse_mode="HTML")

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
    parts = callback.data.split(":")
    if len(parts) >= 3:
        title = parts[1]
        rating = int(parts[2])
        await add_rating(callback.from_user.id, title, rating)
        await callback.answer("Спасибо за оценку! 🙏", show_alert=False)
        await callback.message.edit_reply_markup(reply_markup=None)
    else:
        await callback.answer()

@router.message(F.text == "📖 Дневник")
async def show_diary(message: types.Message):
    log = await get_cook_log(message.from_user.id, limit=5)
    if not log:
        await message.answer("Ваш дневник пуст. Приготовьте что-нибудь!")
        return
    text = "<b>📖 Последние приготовленные блюда:</b>\n\n"
    for rec in log:
        title = rec.get('title', 'Без названия')
        text += f"• {title}\n"
    await message.answer(text, parse_mode="HTML")

@router.message(F.text == "🏆 Статистика")
async def show_stats(message: types.Message):
    count = await get_cooked_count(message.from_user.id)
    achievements = await get_user_achievements(message.from_user.id)
    ach_text = "\n".join([f"{a['icon']} {a['name']} – {a['desc']}" for a in achievements]) if achievements else "Нет достижений"
    level = "Новичок"
    if count >= 10:
        level = "Шеф"
    elif count >= 5:
        level = "Умелец"
    text = (
        f"🏆 <b>Ваш уровень:</b> {level}\n"
        f"🍳 Приготовлено блюд: <b>{count}</b>\n\n"
        f"<b>Достижения:</b>\n{ach_text}"
    )
    await message.answer(text, parse_mode="HTML")

@router.message(F.text == "🗡 Квест дня")
async def quest_command(message: types.Message):
    quest = await get_or_create_quest(message.from_user.id)
    if quest["completed"]:
        await message.answer("🎉 Вы уже выполнили сегодняшний квест! Приходите завтра за новым.")
    else:
        await message.answer(
            f"🗡 <b>Квест дня:</b> {quest['description']}\n\n"
            "Как только приготовите подходящее блюдо, нажмите кнопку ниже.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Я выполнил!", callback_data="complete_quest")]
            ])
        )

@router.callback_query(F.data == "complete_quest")
async def complete_quest_callback(callback: types.CallbackQuery):
    quest = await get_or_create_quest(callback.from_user.id)
    if quest["completed"]:
        await callback.answer("Квест уже выполнен.", show_alert=True)
        return
    await complete_quest(callback.from_user.id)
    # Начисляем бонусные баллы (просто отмечаем)
    await callback.answer("Квест выполнен! +50 очков!", show_alert=True)
    await callback.message.answer("🎉 Отлично! Вы заработали бонусные очки. Завтра ждите новый квест.")

@router.message(F.text == "🔔 Блюдо дня")
async def toggle_daily(message: types.Message):
    subs = await get_all_subscribers()
    if message.from_user.id in subs:
        await remove_subscriber(message.from_user.id)
        await message.answer("🔕 Вы отписались от блюда дня.")
    else:
        await add_subscriber(message.from_user.id)
        await message.answer("🔔 Теперь вы будете получать блюдо дня в 10:00 UTC! 🍽️")

@router.message(F.text == "⚙️ Настройки")
async def settings_button(message: types.Message):
    await set_prefs_start(message)

@router.message(F.text == "ℹ️ О боте")
async def about_bot(message: types.Message):
    await message.answer(
        "🤖 <b>CookBot</b> — твой персональный шеф-помощник.\n\n"
        "Я использую искусственный интеллект, чтобы превратить твои продукты в изысканные блюда.\n"
        "Просто напиши мне список ингредиентов, и я пришлю пошаговый рецепт!\n\n"
        "🛠 Команды:\n"
        "/start – главное меню\n"
        "/setprefs – настройка диеты, аллергий, уровня\n"
        "/help – помощь\n\n"
        "Приятного аппетита! 🍽️",
        parse_mode="HTML",
        reply_markup=main_kb
    )

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

def format_recipe(recipe: dict) -> str:
    text = (
        f"🍽 <b>{recipe.get('title', 'Блюдо')}</b>\n"
        f"⏱ Время: {recipe.get('cooking_time', 'не указано')}\n"
        f"📊 Сложность: {recipe.get('difficulty', 'не указана')}\n\n"
        f"<b>Ингредиенты:</b>\n" + "\n".join(f"• {ing}" for ing in recipe.get('ingredients', [])) + "\n\n"
        f"<b>Приготовление:</b>\n" + "\n".join(f"{i+1}. {step}" for i, step in enumerate(recipe.get('steps', [])))
    )
    if recipe.get('tip'):
        text += f"\n\n💡 <i>Совет: {recipe['tip']}</i>"
    return text
