import asyncio
import logging
import os
from aiohttp import web
from aiogram import Bot, Dispatcher
from config import TELEGRAM_BOT_TOKEN
from handlers.recipe import router as recipe_router
from handlers.profile import router as profile_router
from database.db import init_db
from scheduler import scheduler, send_daily_recipe

logging.basicConfig(level=logging.INFO)

async def health(request):
    return web.Response(text="OK")

async def main():
    await init_db()
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(profile_router)
    dp.include_router(recipe_router)

    # Health server
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Health server started on port {port}")

    # Планировщик
    scheduler.add_job(send_daily_recipe, 'cron', hour=10, minute=0, args=[bot])
    scheduler.start()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
