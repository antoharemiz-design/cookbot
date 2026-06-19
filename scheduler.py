from apscheduler.schedulers.asyncio import AsyncIOScheduler
from services.ai import get_recipe
from database.db import get_all_subscribers

async def send_daily_recipe(bot):
    subscribers = await get_all_subscribers()
    if not subscribers:
        return
    recipe, _ = await get_recipe("случайное блюдо дня", extra_context="Придумай интересный сбалансированный рецепт")
    if recipe is None:
        return
    from handlers.recipe import format_recipe
    text = format_recipe(recipe)
    for user_id in subscribers:
        try:
            await bot.send_message(user_id, "🍽️ <b>Блюдо дня!</b>\n\n" + text, parse_mode="HTML")
        except:
            pass

scheduler = AsyncIOScheduler()
