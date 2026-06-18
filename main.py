import asyncio
import logging
import os
from aiohttp import web
from aiogram import Bot, Dispatcher
from config import TELEGRAM_BOT_TOKEN
from handlers.recipe import router
from database.db import init_db

logging.basicConfig(level=logging.INFO)

async def health(request):
    return web.Response(text="OK")

async def main():
    await init_db()
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    # Запускаем веб-сервер на порту из переменной окружения (Render сам его задаст)
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Health server started on port {port}")

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
