from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from database.db import update_user_prefs, get_user_prefs

router = Router()

class NameState(StatesGroup):
    waiting_for_name = State()

# Главное меню
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🍳 Придумать рецепт")],
        [KeyboardButton(text="⭐ Мои избранные")],
        [KeyboardButton(text="🔔 Блюдо дня"), KeyboardButton(text="📅 Меню на неделю")],
        [KeyboardButton(text="⚙️ Профиль"), KeyboardButton(text="❓ Помощь")]
    ],
    resize_keyboard=True
)

# Инлайн-клавиатуры
def diet_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Без ограничений", callback_data="set_diet:none")],
        [InlineKeyboardButton(text="Кето", callback_data="set_diet:keto")],
        [InlineKeyboardButton(text="Веган", callback_data="set_diet:vegan")],
        [InlineKeyboardButton(text="Вегетарианская", callback_data="set_diet:vegetarian")],
        [InlineKeyboardButton(text="Низкоуглеводная", callback_data="set_diet:lowcarb")]
    ])

def allergies_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Нет", callback_data="set_allergies:none")],
        [InlineKeyboardButton(text="Орехи", callback_data="set_allergies:nuts")],
        [InlineKeyboardButton(text="Молочка", callback_data="set_allergies:dairy")],
        [InlineKeyboardButton(text="Глютен", callback_data="set_allergies:gluten")],
        [InlineKeyboardButton(text="Морепродукты", callback_data="set_allergies:seafood")]
    ])

def dislikes_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Нет", callback_data="set_dislikes:none")],
        [InlineKeyboardButton(text="Лук", callback_data="set_dislikes:onion")],
        [InlineKeyboardButton(text="Рыба", callback_data="set_dislikes:fish")],
        [InlineKeyboardButton(text="Брокколи", callback_data="set_dislikes:broccoli")],
        [InlineKeyboardButton(text="Чеснок", callback_data="set_dislikes:garlic")]
    ])

def skill_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Новичок", callback_data="set_skill:beginner")],
        [InlineKeyboardButton(text="Средний", callback_data="set_skill:intermediate")],
        [InlineKeyboardButton(text="Продвинутый", callback_data="set_skill:advanced")]
    ])

@router.message(Command("profile"))
@router.message(F.text == "⚙️ Профиль")
async def profile_start(message: types.Message, state: FSMContext):
    prefs = await get_user_prefs(message.from_user.id)
    if prefs and prefs.get("name") and prefs.get("name") != "в ожидании...":
        await message.answer(
            f"Твой профиль:\n"
            f"👤 Имя: {prefs.get('name', '-')}\n"
            f"🥗 Диета: {prefs.get('diet', '-')}\n"
            f"⚠️ Аллергии: {prefs.get('allergies', '-')}\n"
            f"🚫 Не любишь: {prefs.get('dislikes', '-')}\n"
            f"👨‍🍳 Уровень: {prefs.get('skill', '-')}\n\n"
            "Что хочешь изменить?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✏️ Имя", callback_data="edit_name")],
                [InlineKeyboardButton(text="🥗 Диета", callback_data="edit_diet")],
                [InlineKeyboardButton(text="⚠️ Аллергии", callback_data="edit_allergies")],
                [InlineKeyboardButton(text="🚫 Нелюбимые", callback_data="edit_dislikes")],
                [InlineKeyboardButton(text="👨‍🍳 Уровень", callback_data="edit_skill")]
            ])
        )
        return

    await message.answer("Давай заполним профиль! Напиши своё имя:")
    await state.set_state(NameState.waiting_for_name)

@router.message(NameState.waiting_for_name, F.text)
async def process_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("Имя не может быть пустым. Попробуй ещё раз.")
        return
    await update_user_prefs(message.from_user.id, name=name)
    await state.clear()
    await message.answer(f"Отлично, {name}! Выбери диету:", reply_markup=diet_inline())

# Обработчики с конкретными фильтрами
@router.callback_query(F.data.startswith("set_diet:"))
async def set_diet(callback: types.CallbackQuery):
    diet_map = {
        "none": "Без ограничений", "keto": "Кето", "vegan": "Веган",
        "vegetarian": "Вегетарианская", "lowcarb": "Низкоуглеводная"
    }
    key = callback.data.split(":", 1)[1]
    diet = diet_map.get(key, key)
    await update_user_prefs(callback.from_user.id, diet=diet)
    await callback.answer(f"Диета: {diet}")
    await callback.message.edit_text("Есть ли у тебя аллергии?", reply_markup=allergies_inline())

@router.callback_query(F.data.startswith("set_allergies:"))
async def set_allergies(callback: types.CallbackQuery):
    allergies_map = {
        "none": "Нет", "nuts": "Орехи", "dairy": "Молочка",
        "gluten": "Глютен", "seafood": "Морепродукты"
    }
    key = callback.data.split(":", 1)[1]
    value = allergies_map.get(key, key)
    await update_user_prefs(callback.from_user.id, allergies=value)
    await callback.answer(f"Аллергии: {value}")
    await callback.message.edit_text("Какие продукты не любишь?", reply_markup=dislikes_inline())

@router.callback_query(F.data.startswith("set_dislikes:"))
async def set_dislikes(callback: types.CallbackQuery):
    dislikes_map = {
        "none": "Нет", "onion": "Лук", "fish": "Рыба",
        "broccoli": "Брокколи", "garlic": "Чеснок"
    }
    key = callback.data.split(":", 1)[1]
    value = dislikes_map.get(key, key)
    await update_user_prefs(callback.from_user.id, dislikes=value)
    await callback.answer(f"Нелюбимые: {value}")
    await callback.message.edit_text("Какой у тебя уровень готовки?", reply_markup=skill_inline())

@router.callback_query(F.data.startswith("set_skill:"))
async def set_skill(callback: types.CallbackQuery):
    skill_map = {
        "beginner": "Новичок", "intermediate": "Средний", "advanced": "Продвинутый"
    }
    key = callback.data.split(":", 1)[1]
    skill = skill_map.get(key, key)
    await update_user_prefs(callback.from_user.id, skill=skill)
    await callback.answer(f"Уровень: {skill}")
    await callback.message.edit_text(
        "✅ Профиль сохранён! Теперь рецепты будут персональными.",
        reply_markup=None
    )
    await callback.message.answer("Главное меню:", reply_markup=main_kb)

# Редактирование отдельных полей
@router.callback_query(F.data == "edit_name")
async def edit_name(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text("Введи новое имя:")
    await state.set_state(NameState.waiting_for_name)

@router.callback_query(F.data == "edit_diet")
async def edit_diet(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Выбери диету:", reply_markup=diet_inline())

@router.callback_query(F.data == "edit_allergies")
async def edit_allergies(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Выбери аллергены:", reply_markup=allergies_inline())

@router.callback_query(F.data == "edit_dislikes")
async def edit_dislikes(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Что не любишь?", reply_markup=dislikes_inline())

@router.callback_query(F.data == "edit_skill")
async def edit_skill(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Твой уровень:", reply_markup=skill_inline())
