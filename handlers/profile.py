from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database.db import update_user_prefs, get_user_prefs

router = Router()

# Обычное меню
main_kb = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text="🍳 Придумать рецепт")],
        [types.KeyboardButton(text="⭐ Мои избранные")],
        [types.KeyboardButton(text="🔔 Блюдо дня"), types.KeyboardButton(text="📅 Меню на неделю")],
        [types.KeyboardButton(text="⚙️ Профиль"), types.KeyboardButton(text="❓ Помощь")]
    ],
    resize_keyboard=True
)

# ---------- Инлайн-клавиатуры ----------
def diet_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Без ограничений", callback_data="set_diet:Без ограничений")],
        [InlineKeyboardButton(text="Кето", callback_data="set_diet:Кето")],
        [InlineKeyboardButton(text="Веган", callback_data="set_diet:Веган")],
        [InlineKeyboardButton(text="Вегетарианская", callback_data="set_diet:Вегетарианская")],
        [InlineKeyboardButton(text="Низкоуглеводная", callback_data="set_diet:Низкоуглеводная")]
    ])

def skill_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Новичок", callback_data="set_skill:Новичок")],
        [InlineKeyboardButton(text="Средний", callback_data="set_skill:Средний")],
        [InlineKeyboardButton(text="Продвинутый", callback_data="set_skill:Продвинутый")]
    ])

def allergies_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Нет", callback_data="set_allergies:Нет")],
        [InlineKeyboardButton(text="Орехи", callback_data="set_allergies:Орехи")],
        [InlineKeyboardButton(text="Молочка", callback_data="set_allergies:Молочка")],
        [InlineKeyboardButton(text="Глютен", callback_data="set_allergies:Глютен")],
        [InlineKeyboardButton(text="Морепродукты", callback_data="set_allergies:Морепродукты")]
    ])

def dislikes_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Нет", callback_data="set_dislikes:Нет")],
        [InlineKeyboardButton(text="Лук", callback_data="set_dislikes:Лук")],
        [InlineKeyboardButton(text="Рыба", callback_data="set_dislikes:Рыба")],
        [InlineKeyboardButton(text="Брокколи", callback_data="set_dislikes:Брокколи")],
        [InlineKeyboardButton(text="Чеснок", callback_data="set_dislikes:Чеснок")]
    ])

def finalize_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Сохранить", callback_data="save_profile")]
    ])

# ---------- Команды и кнопки ----------
@router.message(Command("profile"))
@router.message(F.text == "⚙️ Профиль")
async def profile_start(message: types.Message):
    prefs = await get_user_prefs(message.from_user.id)
    if prefs and prefs.get("name"):
        await message.answer(
            f"Твой профиль:\n"
            f"👤 Имя: {prefs.get('name', '-')}\n"
            f"🥗 Диета: {prefs.get('diet', '-')}\n"
            f"⚠️ Аллергии: {prefs.get('allergies', '-')}\n"
            f"🚫 Не любишь: {prefs.get('dislikes', '-')}\n"
            f"👨‍🍳 Уровень: {prefs.get('skill', '-')}\n\n"
            "Чтобы изменить, нажми кнопку ниже.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✏️ Изменить имя", callback_data="edit_name")],
                [InlineKeyboardButton(text="🥗 Изменить диету", callback_data="edit_diet")],
                [InlineKeyboardButton(text="⚠️ Аллергии", callback_data="edit_allergies")],
                [InlineKeyboardButton(text="🚫 Нелюбимые", callback_data="edit_dislikes")],
                [InlineKeyboardButton(text="👨‍🍳 Уровень", callback_data="edit_skill")]
            ])
        )
        return

    # Новый пользователь: просим имя
    await message.answer("Привет! Давай заполним твой профиль.\nНапиши своё имя:")
    # Временно сохраним состояние в user_prefs с пустым именем, чтобы знать, что ждём имя
    await update_user_prefs(message.from_user.id, name="в ожидании...")

@router.message(lambda msg: msg.text and not msg.text.startswith('/') and msg.text not in [
    "🍳 Придумать рецепт", "⭐ Мои избранные", "🔔 Блюдо дня", "📅 Меню на неделю",
    "⚙️ Профиль", "❓ Помощь", "🔙 Главное меню"
])
async def handle_name_input(message: types.Message):
    # Проверим, ждём ли мы имя (поле name == "в ожидании...")
    prefs = await get_user_prefs(message.from_user.id)
    if prefs and prefs.get("name") == "в ожидании...":
        # Сохраняем имя
        await update_user_prefs(message.from_user.id, name=message.text.strip())
        await message.answer(f"Отлично, {message.text.strip()}! Теперь выбери диету:", reply_markup=diet_inline())
    else:
        # Если не ждём имя, значит это обычный запрос рецепта — передадим управление в recipe.py
        # Но чтобы не усложнять, просто проигнорируем (в recipe.py всё равно стоит этот же фильтр, он обработает)
        pass

# ---------- Callback-обработчики ----------
@router.callback_query(F.data.startswith("set_diet:"))
async def set_diet(callback: types.CallbackQuery):
    diet = callback.data.split(":", 1)[1]
    await update_user_prefs(callback.from_user.id, diet=diet)
    await callback.answer(f"Диета сохранена: {diet}")
    await callback.message.answer("Есть ли у тебя аллергии?", reply_markup=allergies_inline())

@router.callback_query(F.data.startswith("set_allergies:"))
async def set_allergies(callback: types.CallbackQuery):
    value = callback.data.split(":", 1)[1]
    await update_user_prefs(callback.from_user.id, allergies=value)
    await callback.answer(f"Аллергии сохранены: {value}")
    await callback.message.answer("Какие продукты не любишь?", reply_markup=dislikes_inline())

@router.callback_query(F.data.startswith("set_dislikes:"))
async def set_dislikes(callback: types.CallbackQuery):
    value = callback.data.split(":", 1)[1]
    await update_user_prefs(callback.from_user.id, dislikes=value)
    await callback.answer(f"Нелюбимые сохранены: {value}")
    await callback.message.answer("Какой у тебя уровень готовки?", reply_markup=skill_inline())

@router.callback_query(F.data.startswith("set_skill:"))
async def set_skill(callback: types.CallbackQuery):
    skill = callback.data.split(":", 1)[1]
    await update_user_prefs(callback.from_user.id, skill=skill)
    await callback.answer(f"Уровень сохранён: {skill}")
    await callback.message.answer("Профиль готов! Теперь рецепты будут персональными.", reply_markup=main_kb)

# Редактирование отдельных полей
@router.callback_query(F.data == "edit_name")
async def edit_name(callback: types.CallbackQuery):
    await update_user_prefs(callback.from_user.id, name="в ожидании...")
    await callback.answer()
    await callback.message.answer("Введи новое имя:")

@router.callback_query(F.data == "edit_diet")
async def edit_diet(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer("Выбери диету:", reply_markup=diet_inline())

@router.callback_query(F.data == "edit_allergies")
async def edit_allergies(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer("Выбери аллергены:", reply_markup=allergies_inline())

@router.callback_query(F.data == "edit_dislikes")
async def edit_dislikes(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer("Что не любишь?", reply_markup=dislikes_inline())

@router.callback_query(F.data == "edit_skill")
async def edit_skill(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer("Твой уровень:", reply_markup=skill_inline())
