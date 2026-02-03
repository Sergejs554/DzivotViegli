from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🩺 Самочувствие")],
            [KeyboardButton(text="🌍 Язык")],
        ],
        resize_keyboard=True
    )
