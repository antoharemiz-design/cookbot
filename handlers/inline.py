from aiogram import Router, types
from aiogram.types import InlineQueryResultArticle, InputTextMessageContent
from services.ai import get_recipe
import hashlib

router = Router()

@router.inline_query()
async def inline_recipe(inline_query: types.InlineQuery):
    query = inline_query.query.strip()
    if not query or len(query) < 3:
        return

    recipe, _ = await get_recipe(query)
    if recipe is None:
        return

    # Формируем текст для предпросмотра
    title = recipe.get("title", "Рецепт")
    time = recipe.get("cooking_time", "? мин")
    description = f"⏱ {time} | {recipe.get('difficulty', '')}"
    ingredients = "\n".join(f"• {ing}" for ing in recipe.get("ingredients", []))
    steps = "\n".join(f"{i+1}. {step}" for i, step in enumerate(recipe.get("steps", [])))
    full_text = f"🍽 <b>{title}</b>\n⏱ {time}\n\n<b>Ингредиенты:</b>\n{ingredients}\n\n<b>Приготовление:</b>\n{steps}"
    if recipe.get("tip"):
        full_text += f"\n\n💡 {recipe['tip']}"

    input_content = InputTextMessageContent(full_text, parse_mode="HTML")
    result_id = hashlib.md5(query.encode()).hexdigest()

    result = InlineQueryResultArticle(
        id=result_id,
        title=title,
        description=description,
        input_message_content=input_content
    )

    await inline_query.answer([result], cache_time=10)
