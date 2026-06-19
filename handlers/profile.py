from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from database.db import update_user_prefs, get_user_prefs

router = Router()

class ProfileForm(StatesGroup):
    name = State()
    diet = State()
    allergies = State()
    dislikes = State()
    skill = State()

def diet_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Без ограничений")],
            [KeyboardButton(text="Кето")],
            [KeyboardButton(text="Веган")],
            [KeyboardButton(text="Вегетарианская")],
            [KeyboardButton(text="Низкоуглеводная")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def skill_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Новичок")],
            [KeyboardButton(text="Средний")],
            [KeyboardButton(text="Продвинутый")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def skip_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Пропустить")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🍳 Придумать рецепт")],
        [KeyboardButton(text="⭐ Мои избранные")],
        [KeyboardButton(text="🔔 Блюдо дня"), KeyboardButton(text="📅 Меню на неделю")],
        [KeyboardButton(text="⚙️ Профиль"), KeyboardButton(text="❓ Помощь")]
    ],
    resize_keyboard=True
)

@router.message(Command("profile"))
@router.message(F.text == "⚙️ Профиль")
async def start_profile(message: types.Message, state: FSMContext):
    prefs = await get_user_prefs(message.from_user.id)
    if prefs and prefs.get("name") and prefs.get("name") != "в ожидании...":
        await message.answer(
            f"Твой профиль:\n"
            f"👤 Имя: {prefs.get('name', '-')}\n"
            f"🥗 Диета: {prefs.get('diet', '-')}\n"
            f"⚠️ Аллергии: {prefs.get('allergies', '-')}\n"
            f"🚫 Не любишь: {prefs.get('dislikes', '-')}\n"
            f"👨‍🍳 Уровень: {prefs.get('skill', '-')}\n\n"
            "Чтобы изменить, нажми /profile ещё раз.",
            reply_markup=main_kb
        )
        return

    await message.answer("Давай познакомимся! Как тебя зовут?")
    await state.set_state(ProfileForm.name)

@router.message(ProfileForm.name, F.text)
async def process_name(message: types.Message, state: FSMContext):
    print("DEBUG: process_name")
    await state.update_data(name=message.text)
    await message.answer("Какая у тебя диета или предпочтения по питанию?", reply_markup=diet_kb())
    await state.set_state(ProfileForm.diet)

@router.message(ProfileForm.diet, F.text)
async def process_diet(message: types.Message, state: FSMContext):
    print(f"DEBUG: process_diet text={message.text}")
    if message.text not in ["Без ограничений", "Кето", "Веган", "Вегетарианская", "Низкоуглеводная"]:
        await message.answer("Пожалуйста, выбери из вариантов.", reply_markup=diet_kb())
        return
    await state.update_data(diet=message.text)
    await message.answer("Есть ли у тебя аллергии? (например: орехи, молочка, глютен). Если нет, напиши 'нет'.", reply_markup=skip_kb())
    await state.set_state(ProfileForm.allergies)

@router.message(ProfileForm.allergies, F.text)
async def process_allergies(message: types.Message, state: FSMContext):
    print(f"DEBUG: process_allergies text={message.text}")
    if message.text == "Пропустить":
        await state.update_data(allergies="Нет")
    else:
        await state.update_data(allergies=message.text)
    await message.answer("Какие продукты ты не любишь? (например: лук, рыба, брокколи). Можно пропустить.", reply_markup=skip_kb())
    await state.set_state(ProfileForm.dislikes)

@router.message(ProfileForm.dislikes, F.text)
async def process_dislikes(message: types.Message, state: FSMContext):
    print(f"DEBUG: process_dislikes text={message.text}")
    if message.text == "Пропустить":
        await state.update_data(dislikes="Нет")
    else:
        await state.update_data(dislikes=message.text)
    await message.answer("Какой у тебя уровень готовки?", reply_markup=skill_kb())
    await state.set_state(ProfileForm.skill)

@router.message(ProfileForm.skill, F.text)
async def process_skill(message: types.Message, state: FSMContext):
    print(f"DEBUG: process_skill text={message.text}")
    if message.text not in ["Новичок", "Средний", "Продвинутый"]:
        await message.answer("Выбери уровень.", reply_markup=skill_kb())
        return
    data = await state.get_data()
    print(f"DEBUG: data from state = {data}")
    await update_user_prefs(
        message.from_user.id,
        name=data['name'],
        diet=data['diet'],
        allergies=data['allergies'],
        dislikes=data['dislikes'],
        skill=message.text
    )
    await state.clear()
    await message.answer(
        f"✅ Профиль сохранён! Теперь рецепты будут подбираться с учётом твоих предпочтений.",
        reply_markup=main_kb
    )
