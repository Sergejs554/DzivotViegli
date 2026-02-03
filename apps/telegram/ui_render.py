from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🩺 Самочувствие")],
            [KeyboardButton(text="🌍 Язык")],
        ],
        resize_keyboard=True
    )


def request_location_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Поделиться геолокацией", request_location=True)],
            [KeyboardButton(text="✍️ Ввести адрес вручную")],
            [KeyboardButton(text="⬅️ Назад в меню")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )


def remove_kb() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()
