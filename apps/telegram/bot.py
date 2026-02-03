import os
import asyncio

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from core.orchestrator import handle_start


router = Router()


def health_urgency_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔴 Сильно / резко / хуже", callback_data="health:severe"),
            InlineKeyboardButton(text="🟡 Терпимо", callback_data="health:mild"),
        ]
    ])


def health_actions_kb(severe: bool) -> InlineKeyboardMarkup:
    # В Telegram можно дать ссылку tel: и на карты.
    # Такси/транспорт пока заглушками (потом подключим конкретные сервисы/маршруты).
    buttons = []

    if severe:
        buttons.append([InlineKeyboardButton(text="🚑 Позвонить 113", url="tel:113")])

    # Маршрут до больницы (пока общий Google Maps query)
    hospital_query = "Liepājas reģionālā slimnīca Slimnīcas iela 25"
    maps_url = f"https://www.google.com/maps/search/?api=1&query={hospital_query.replace(' ', '+')}"
    buttons.append([InlineKeyboardButton(text="📍 Маршрут до больницы", url=maps_url)])

    # Такси/транспорт - пока как “действие-заглушка”, потом сделаем нормально
    buttons.append([
        InlineKeyboardButton(text="🚕 Такси", callback_data="todo:taxi"),
        InlineKeyboardButton(text="🚌 Транспорт", callback_data="todo:transport"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(CommandStart())
async def on_start(message: Message) -> None:
    await handle_start(message)


@router.message(F.text == "🩺 Самочувствие")
async def on_health(message: Message) -> None:
    await message.answer(
        "Ок. Насколько срочно?",
        reply_markup=health_urgency_kb()
    )


@router.callback_query(F.data == "health:severe")
async def on_health_severe(callback: CallbackQuery) -> None:
    await callback.message.answer(
        "Если становится хуже - не тяни. Вот быстрые действия рядом:",
        reply_markup=health_actions_kb(severe=True)
    )
    await callback.answer()


@router.callback_query(F.data == "health:mild")
async def on_health_mild(callback: CallbackQuery) -> None:
    await callback.message.answer(
        "Понял. Давай сделаем спокойно и по делу. Вот варианты действий:",
        reply_markup=health_actions_kb(severe=False)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("todo:"))
async def on_todo(callback: CallbackQuery) -> None:
    if callback.data == "todo:taxi":
        await callback.message.answer("Такси: в следующем шаге подключим конкретные кнопки (Bolt/др.)")
    elif callback.data == "todo:transport":
        await callback.message.answer("Транспорт: в следующем шаге подтянем ближайшие маршруты/время (Rīgas satiksme / Liepāja).")
    await callback.answer()


@router.message(F.text == "🌍 Язык")
async def on_language(message: Message) -> None:
    await message.answer("Пока default RU. LV подключим следующим блоком (i18n).")


async def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is not set. Add it to Railway Variables.")

    bot = Bot(token=token)
    dp = Dispatcher()
    dp.include_router(router)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
