from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from database.db import update_user_prefs, get_user_prefs

router = Router()

# Единственное состояние только для ввода имени
class NameState(StatesGroup):
    waiting_for_name = State()

# Главное меню (обычные кнопки)
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
        [InlineKeyboardButton(text="Без ограничений", callback_data="set_diet:Без ограничений")],
        [InlineKeyboardButton(text="Кето", callback_data="set_diet:Кето")],
        [InlineKeyboardButton(text="Веган", callback_data="set_diet:Веган")],
        [InlineKeyboardButton(text="Вегетарианская", callback_data="set_diet:Вегетарианская")],
        [InlineKeyboardButton(text="Низкоуглеводная", callback_data="set_diet:Низкоуглеводная")]
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

def skill_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Новичок", callback_data="set_skill:Новичок")],
        [InlineKeyboardButton(text="Средний", callback_data="set_skill:Средний")],
        [InlineKeyboardButton(text="Продвинутый", callback_data="set_skill:Продвинутый")]
    ])

# ---------- Старт профиля ----------
@router.message(Command("profile"))
@router.message(F.text == "⚙️ Профиль")
async def profile_start(message: types.Message, state: FSMContext):
    prefs = await get_user_prefs(message.from_user.id)
    if prefs and prefs.get("name") and prefs.get("name") != "в ожидании...":
        # Уже заполненный профиль – показываем данные и кнопки редактирования
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

    # Новый пользователь или не завершён ввод имени
    await message.answer("Давай заполним профиль! Напиши своё имя:")
    await state.set_state(NameState.waiting_for_name)

# ---------- Обработка ввода имени (только когда ждём) ----------
@router.message(NameState.waiting_for_name, F.text)
async def process_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("Имя не может быть пустым. Попробуй ещё раз.")
        return
    await update_user_prefs(message.from_user.id, name=name)
    await state.clear()
    # Отправляем новое сообщение с выбором диеты (удалим предыдущее? оставим)
    await message.answer(f"Отлично, {name}! Выбери диету:", reply_markup=diet_inline())

# ---------- Инлайн-обработчики (редактируют текущее сообщение) ----------
@router.callback_query(F.data.startswith("set_diet:"))
async def set_diet(callback: types.CallbackQuery):
    diet = callback.data.split(":", 1)[1]
    await update_user_prefs(callback.from_user.id, diet=diet)
    await callback.answer(f"Диета: {diet}")
    await callback.message.edit_text("Есть ли у тебя аллергии?", reply_markup=allergies_inline())

@router.callback_query(F.data.startswith("set_allergies:"))
async def set_allergies(callback: types.CallbackQuery):
    value = callback.data.split(":", 1)[1]
    await update_user_prefs(callback.from_user.id, allergies=value)
    await callback.answer(f"Аллергии: {value}")
    await callback.message.edit_text("Какие продукты не любишь?", reply_markup=dislikes_inline())

@router.callback_query(F.data.startswith("set_dislikes:"))
async def set_dislikes(callback: types.CallbackQuery):
    value = callback.data.split(":", 1)[1]
    await update_user_prefs(callback.from_user.id, dislikes=value)
    await callback.answer(f"Нелюбимые: {value}")
    await callback.message.edit_text("Какой у тебя уровень готовки?", reply_markup=skill_inline())

@router.callback_query(F.data.startswith("set_skill:"))
async def set_skill(callback: types.CallbackQuery):
    skill = callback.data.split(":", 1)[1]
    await update_user_prefs(callback.from_user.id, skill=skill)
    await callback.answer(f"Уровень: {skill}")
    # Заменяем сообщение на финальное и возвращаем главное меню
    await callback.message.edit_text(
        "✅ Профиль сохранён! Теперь рецепты будут персональными.",
        reply_markup=None  # убираем инлайн-кнопки
    )
    # Отправляем главное меню отдельным сообщением
    await callback.message.answer("Главное меню:", reply_markup=main_kb)

# ---------- Редактирование отдельных полей ----------
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
