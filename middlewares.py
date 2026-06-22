from aiogram import BaseMiddleware
from aiogram.types import Update, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramForbiddenError

CHANNEL_USERNAME = "@architectkulees"

class SubscriptionMiddleware(BaseMiddleware):
    def __init__(self, channel_username: str = CHANNEL_USERNAME):
        self.channel_username = channel_username
        super().__init__()

    async def __call__(self, handler, event: Update, data: dict):
        user_id = None
        if event.message:
            user_id = event.message.from_user.id
            # Пропускаем команду /start, чтобы показать приветствие
            if event.message.text and event.message.text.startswith('/start'):
                return await handler(event, data)
        elif event.callback_query:
            user_id = event.callback_query.from_user.id
        elif event.inline_query:
            user_id = event.inline_query.from_user.id

        if user_id:
            bot = data["bot"]
            try:
                member = await bot.get_chat_member(chat_id=self.channel_username, user_id=user_id)
                if member.status in ("left", "kicked", "banned"):
                    await self.send_subscription_prompt(event, bot)
                    return
            except TelegramForbiddenError:
                # Бот не добавлен в канал – продолжаем без проверки
                pass
        return await handler(event, data)

    async def send_subscription_prompt(self, event, bot):
        text = f"🔒 Чтобы пользоваться ботом, подпишитесь на канал {self.channel_username}\n\nПосле подписки повторите ваш запрос."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👉 Подписаться", url=f"https://t.me/{self.channel_username[1:]}")]
        ])
        if event.message:
            await event.message.answer(text, reply_markup=kb)
        elif event.callback_query:
            await event.callback_query.message.answer(text, reply_markup=kb)
            await event.callback_query.answer()
