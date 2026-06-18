from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from services.ai import get_recipe
from database.db import add_favorite, get_favorites, remove_favorite, set_last_recipe, get_last_recipe
import json

router = Router()

# Главное меню
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🍳 Придумать рецепт")],
        [KeyboardButton(text="⭐ Мои избранные")],
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
    await message.answer(
        "👋 Привет! Я твой личный шеф-помощник.\n"
        "Выбери действие в меню или просто напиши список продуктов.\n\n"
        "Если хочешь, чтобы я учёл твои предпочтения (диета, аллергии), "
        "заполни профиль в разделе ⚙️ Профиль.",
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
    await message.answer(
        "⭐ Ваши избранные рецепты (нажмите для деталей):",
        reply_markup=builder.as_markup()
    )

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
    builder.row(InlineKeyboardButton(
        text="🗑 Удалить из избранного",
        callback_data=f"del_fav:{index}"
    ))
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

# Обработка текстовых запросов
@router.message(lambda msg: msg.text and not msg.text.startswith('/') and msg.text not in [
    "🍳 Придумать рецепт", "⭐ Мои избранные", "⚙️ Профиль", "❓ Помощь", "🔙 Главное меню"
])
async def generate_recipe(message: types.Message):
    user_input = message.text.strip()
    if len(user_input) < 3:
        await message.answer("Пожалуйста, напиши хотя бы пару продуктов или запрос.")
        return

    await message.answer("Готовлю рецепт...")
    recipe = await get_recipe(user_input)  # extra_context пока не передаём

    if recipe is None:
        await message.answer("Не удалось создать рецепт. Попробуй другой запрос.")
        return

    # Сохраняем последний сгенерированный рецепт в БД
    await set_last_recipe(message.from_user.id, recipe)

    response_text = format_recipe(recipe)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="⭐ В избранное",
        callback_data="save_last"
    ))
    await message.answer(response_text, parse_mode="HTML", reply_markup=builder.as_markup())

@router.callback_query(F.data == "save_last")
async def save_last_recipe(callback: types.CallbackQuery):
    recipe = await get_last_recipe(callback.from_user.id)
    if recipe is None:
        await callback.answer("Не найден рецепт для сохранения.", show_alert=True)
        return
    await add_favorite(callback.from_user.id, recipe)
    await callback.answer("Добавлено в избранное! ⭐", show_alert=True)
    # Убираем кнопку, чтобы не смущать
    await callback.message.edit_reply_markup(reply_markup=None)

@router.message(F.text == "❓ Помощь")
async def help_cmd(message: types.Message):
    await message.answer(
        "Я могу:\n"
        "• Придумать рецепт из твоих продуктов\n"
        "• Учесть диету и аллергии (заполни ⚙️ Профиль)\n"
        "• Сохранить рецепт в избранное\n\n"
        "Просто нажми на кнопку или напиши запрос!",
        reply_markup=main_kb
    )

@router.message(F.text == "⚙️ Профиль")
async def profile_menu(message: types.Message):
    await message.answer(
        "Здесь можно настроить твои предпочтения.\n"
        "Пока эта функция в разработке. Хочешь помочь? Напиши /setprefs",
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
