from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from services.ai import get_recipe
from database.db import (
    add_favorite, get_favorites, remove_favorite,
    set_last_recipe, get_last_recipe, get_user_prefs,
    add_subscriber, remove_subscriber, get_all_subscribers, add_rating
)

router = Router()

# Главное меню (улучшенное)
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🍳 Придумать рецепт")],
        [KeyboardButton(text="⭐ Мои избранные")],
        [KeyboardButton(text="🔔 Блюдо дня"), KeyboardButton(text="📅 Меню на неделю")],
        [KeyboardButton(text="⚙️ Профиль"), KeyboardButton(text="❓ Помощь")]
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие"
)

back_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🔙 Главное меню")]],
    resize_keyboard=True
)

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    prefs = await get_user_prefs(message.from_user.id)
    name = prefs.get("name") if prefs else None
    greeting = f"👋 Привет, {name}!" if name else "👋 Привет!"
    await message.answer(
        f"{greeting} Я твой личный шеф-помощник.\n"
        "Выбери действие в меню или просто напиши список продуктов.\n\n"
        "🔹 Если ещё не заполнил профиль, нажми ⚙️ Профиль — рецепты станут персональными!",
        reply_markup=main_kb
    )

@router.message(F.text == "🔙 Главное меню")
async def back_to_main(message: types.Message):
    await message.answer("Главное меню", reply_markup=main_kb)

@router.message(F.text == "🍳 Придумать рецепт")
async def prompt_products(message: types.Message):
    await message.answer(
        "Напиши список продуктов через запятую.\n"
        "Например: <i>курица, лук, сметана, гречка</i>\n\n"
        "Или можешь просто сказать: «хочу итальянский ужин»",
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
    await message.answer("⭐ Ваши избранные рецепты (нажмите для деталей):", reply_markup=builder.as_markup())

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

# Обработка текстовых запросов (генерация рецепта)
@router.message(
    StateFilter(None),  # только если нет активного состояния
    lambda msg: msg.text and not msg.text.startswith('/') and msg.text not in [
        "🍳 Придумать рецепт", "⭐ Мои избранные", "🔔 Блюдо дня", "📅 Меню на неделю",
        "⚙️ Профиль", "❓ Помощь", "🔙 Главное меню"
    ]
)
async def generate_recipe(message: types.Message):
    user_input = message.text.strip()
    if len(user_input) < 3:
        await message.answer("Пожалуйста, напиши хотя бы пару продуктов или запрос.")
        return

    await message.answer("Готовлю рецепт...")

    # Загружаем профиль
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
            await message.answer("Слишком много запросов. Попробуйте через минуту.")
        else:
            debug_info = ""
            if raw_response:
                debug_info = f"\n\nОтладка (ответ модели):\n<pre>{raw_response[:1500]}</pre>"
            await message.answer(
                f"Не удалось создать рецепт.{debug_info}\nПопробуйте другой запрос.",
                parse_mode="HTML"
            )
        return

    # Сохраняем последний рецепт
    await set_last_recipe(message.from_user.id, recipe)

    response_text = format_recipe(recipe)
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⭐ В избранное", callback_data="save_last"),
        InlineKeyboardButton(text="📤 Поделиться", switch_inline_query=recipe.get("title", ""))
    )
    builder.row(
        InlineKeyboardButton(text="👍 Вкусно", callback_data=f"rate:{recipe['title']}:1"),
        InlineKeyboardButton(text="👎 Не очень", callback_data=f"rate:{recipe['title']}:0")
    )
    await message.answer(response_text, parse_mode="HTML", reply_markup=builder.as_markup())

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
        emoji = "👍" if rating else "👎"
        await callback.answer(f"Спасибо за оценку! {emoji}", show_alert=False)
        await callback.message.edit_reply_markup(reply_markup=None)
    else:
        await callback.answer()

@router.message(F.text == "🔔 Блюдо дня")
async def toggle_daily(message: types.Message):
    subs = await get_all_subscribers()
    if message.from_user.id in subs:
        await remove_subscriber(message.from_user.id)
        await message.answer("Вы отписались от ежедневных рецептов.")
    else:
        await add_subscriber(message.from_user.id)
        await message.answer("Теперь вы будете получать блюдо дня в 10:00 UTC! 🍽️")

@router.message(F.text == "📅 Меню на неделю")
async def week_menu_placeholder(message: types.Message):
    await message.answer("🚧 Планировщик меню на неделю появится в ближайшее время. Следите за обновлениями!")

@router.message(F.text == "❓ Помощь")
async def help_cmd(message: types.Message):
    await message.answer(
        "Я могу:\n"
        "• Придумать рецепт из твоих продуктов\n"
        "• Учесть диету и аллергии (заполни ⚙️ Профиль)\n"
        "• Сохранить рецепт в избранное\n"
        "• Оценить рецепт и поделиться им\n"
        "• Присылать блюдо дня (подпишись 🔔)\n\n"
        "Просто нажми на кнопку или напиши запрос!",
        reply_markup=main_kb
    )

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
