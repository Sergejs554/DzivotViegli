from aiogram.types import Message
from apps.telegram.ui_render import main_menu

WELCOME_TEXT = (
    "Привет.\n\n"
    "Я DzīvotViegli.\n"
    "Делаю сложные вещи простыми: сложно → просто → действие.\n\n"
    "Напиши одним сообщением, что случилось (например: «болит живот», «болит зуб», «плохо»)\n"
    "или выбери кнопку ниже:"
)

async def handle_start(message: Message) -> None:
    await message.answer(WELCOME_TEXT, reply_markup=main_menu())
