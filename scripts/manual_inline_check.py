import asyncio
from aiogram import Bot
from aiogram.types import Update, ChosenInlineResult, User
from app.main import dp

async def run_inline_smoke_check():
    from app.core.config import settings
    bot = Bot(token=settings.BOT_TOKEN or "123:ABC")
    
    user = User(id=123456789, is_bot=False, first_name="Test")
    result = ChosenInlineResult(
        result_id="test_id",
        from_user=user,
        query="test query",
        inline_message_id="1234567890"
    )
    update = Update(update_id=1, chosen_inline_result=result)
    
    print("Feeding update...")
    try:
        await dp.feed_update(bot=bot, update=update)
        print("Success!")
    except Exception as e:
        print("FAILED:", e)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_inline_smoke_check())
