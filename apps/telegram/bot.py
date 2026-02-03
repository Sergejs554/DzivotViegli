import os
import json
import asyncio
from typing import Optional, Tuple

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from core.orchestrator import handle_start
from apps.telegram.ui_render import main_menu, request_location_kb, remove_kb


router = Router()


# ---------- FSM states ----------
class Flow(StatesGroup):
    awaiting_problem = State()
    awaiting_urgency = State()
    awaiting_location = State()
    awaiting_address = State()


# ---------- Resources ----------
def load_liepaja_resources() -> dict:
    path = "data/resources/liepaja.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "hospital": {
                "name": "Liepājas reģionālā slimnīca",
                "address": "Slimnīcas iela 25, Liepāja",
                "phone": "+37163403222"
            }
        }


def google_maps_route_url(from_lat: float, from_lon: float, dest_query: str) -> str:
    dest = dest_query.replace(" ", "+")
    return f"https://www.google.com/maps/dir/?api=1&origin={from_lat},{from_lon}&destination={dest}"


def google_maps_search_url(query: str) -> str:
    q = query.replace(" ", "+")
    return f"https://www.google.com/maps/search/?api=1&query={q}"


def urgency_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔴 Сильно / резко / хуже", callback_data="urgency:severe"),
            InlineKeyboardButton(text="🟡 Терпимо", callback_data="urgency:mild"),
        ]
    ])


# === изменено ===
# Убрали tel: (часто ломает отправку клавиатуры). Теперь звонки через callback.
def actions_kb(resources: dict, severe: bool, from_coords: Optional[Tuple[float, float]] = None) -> InlineKeyboardMarkup:
    hospital = resources.get("hospital", {})
    hosp_name = hospital.get("name", "Больница")
    hosp_addr = hospital.get("address", "")
    hosp_phone = hospital.get("phone", "")

    buttons = []

    if severe:
        buttons.append([InlineKeyboardButton(text="🚑 Позвонить 113", callback_data="call:113")])

    if hosp_phone:
        buttons.append([InlineKeyboardButton(text="☎️ Позвонить в клинику", callback_data="call:clinic")])

    dest_query = f"{hosp_name} {hosp_addr}".strip()
    if from_coords:
        lat, lon = from_coords
        route_url = google_maps_route_url(lat, lon, dest_query)
        buttons.append([InlineKeyboardButton(text="📍 Маршрут до клиники", url=route_url)])
    else:
        search_url = google_maps_search_url(dest_query)
        buttons.append([InlineKeyboardButton(text="📍 Открыть клинику на карте", url=search_url)])

    buttons.append([InlineKeyboardButton(text="🚕 Такси (Bolt)", url="https://bolt.eu")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)
# === /изменено ===


# ---------- Handlers ----------
@router.message(CommandStart())
async def on_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await handle_start(message)
    await message.answer(
        "Выбери, что сейчас происходит, или напиши одним сообщением:",
        reply_markup=main_menu()
    )
    await state.set_state(Flow.awaiting_problem)


@router.message(F.text == "⬅️ Назад в меню")
async def on_back(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Ок. Напиши, что происходит, или выбери кнопку:", reply_markup=main_menu())
    await state.set_state(Flow.awaiting_problem)


@router.message(F.text == "🩺 Самочувствие")
async def on_health_menu(message: Message, state: FSMContext) -> None:
    await state.set_state(Flow.awaiting_problem)
    await message.answer(
        "Напиши, что болит или что случилось (1 строка). Например: «болит живот», «болит зуб», «плохо».",
        reply_markup=main_menu()
    )


@router.message(F.text == "🌍 Язык")
async def on_language(message: Message) -> None:
    await message.answer("Пока RU. LV подключим следующим блоком (i18n).")


@router.message(Flow.awaiting_problem, F.text)
async def on_problem_text(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if not text:
        return

    await state.update_data(problem=text)

    await message.answer(
        f"Ок. Я правильно понимаю, что сейчас: «{text}»?\n\nНасколько срочно?",
        reply_markup=urgency_kb()
    )
    await state.set_state(Flow.awaiting_urgency)


@router.callback_query(F.data.in_({"urgency:severe", "urgency:mild"}))
async def on_urgency_anytime(callback: CallbackQuery, state: FSMContext) -> None:
    severe = (callback.data == "urgency:severe")
    await state.update_data(severe=severe)

    label = "🔴 Срочно" if severe else "🟡 Терпимо"

    await callback.message.answer(
        f"Ок. Принято: {label}.\nЧтобы дать точные варианты рядом — пришли геолокацию или введи адрес.",
        reply_markup=request_location_kb()
    )

    await state.set_state(Flow.awaiting_location)
    await callback.answer("Принято")


# === изменено ===
# Не хватало обработчика для кнопки "Ввести адрес вручную" (она ломала поток)
@router.message(Flow.awaiting_location, F.text == "✍️ Ввести адрес вручную")
async def on_ask_address(message: Message, state: FSMContext) -> None:
    await message.answer(
        "Ок. Напиши адрес одним сообщением (город, улица, дом).",
        reply_markup=remove_kb()
    )
    await state.set_state(Flow.awaiting_address)
# === /изменено ===


# === изменено ===
# Делаем гео-ответ “железобетонным”: без tel:, с явным итоговым сообщением, и возвратом в awaiting_problem.
@router.message(F.location)
async def on_location_anytime(message: Message, state: FSMContext) -> None:
    loc = message.location
    data = await state.get_data()

    problem = data.get("problem")
    if not problem:
        await message.answer("Сначала напиши одним сообщением, что болит/что случилось (например: «болит живот»).")
        await state.set_state(Flow.awaiting_problem)
        return

    severe = bool(data.get("severe", False))

    await state.update_data(lat=loc.latitude, lon=loc.longitude, severe=severe)

    await message.answer("Принял геолокацию. Собираю действия рядом…", reply_markup=remove_kb())

    resources = load_liepaja_resources()
    hospital = resources.get("hospital", {})
    hosp_name = hospital.get("name", "Клиника")
    hosp_addr = hospital.get("address", "")
    hosp_phone = hospital.get("phone", "")

    kb = actions_kb(
        resources,
        severe=severe,
        from_coords=(loc.latitude, loc.longitude)
    )

    # Сразу показываем “номера клиник” (как ты хотел) — в тексте + кнопки действий ниже
    info_lines = [
        f"Ситуация: «{problem}»",
        "",
        f"🏥 {hosp_name}",
        f"📍 {hosp_addr}" if hosp_addr else "",
        f"☎️ {hosp_phone}" if hosp_phone else "",
        "",
        "Вот быстрые действия:"
    ]
    info = "\n".join([x for x in info_lines if x])

    await message.answer(info, reply_markup=kb)

    # возвращаемся в свободный ввод
    await state.set_state(Flow.awaiting_problem)
# === /изменено ===


@router.message(Flow.awaiting_address, F.text)
async def on_address(message: Message, state: FSMContext) -> None:
    addr = message.text.strip()
    if not addr:
        return

    await state.update_data(address=addr)

    data = await state.get_data()
    resources = load_liepaja_resources()
    severe = bool(data.get("severe", False))
    problem = data.get("problem", "плохо себя чувствую")

    hospital = resources.get("hospital", {})
    hosp_name = hospital.get("name", "Клиника")
    hosp_addr = hospital.get("address", "")
    hosp_phone = hospital.get("phone", "")

    kb = actions_kb(resources, severe=severe, from_coords=None)

    info_lines = [
        f"Принял адрес: {addr}",
        f"Ситуация: «{problem}»",
        "",
        f"🏥 {hosp_name}",
        f"📍 {hosp_addr}" if hosp_addr else "",
        f"☎️ {hosp_phone}" if hosp_phone else "",
        "",
        "Вот быстрые действия:"
    ]
    info = "\n".join([x for x in info_lines if x])

    await message.answer(info, reply_markup=kb)
    await state.set_state(Flow.awaiting_problem)


# === изменено ===
# Callback-звонки (вместо tel:)
@router.callback_query(F.data.startswith("call:"))
async def on_call_callback(callback: CallbackQuery) -> None:
    resources = load_liepaja_resources()
    hospital = resources.get("hospital", {})
    hosp_phone = (hospital.get("phone", "") or "").strip()

    key = callback.data.split(":", 1)[1]

    if key == "113":
        await callback.message.answer("🚑 Срочно: 113\nНажми на номер, чтобы позвонить.")
        await callback.answer("113")
        return

    if key == "clinic":
        if hosp_phone:
            await callback.message.answer(f"☎️ Клиника:\n{hosp_phone}\nНажми на номер, чтобы позвонить.")
            await callback.answer("Клиника")
        else:
            await callback.answer("Номер клиники не задан", show_alert=True)
        return

    await callback.answer("Ок")
# === /изменено ===


@router.message(F.text)
async def fallback_text(message: Message, state: FSMContext) -> None:
    await state.set_state(Flow.awaiting_problem)
    await on_problem_text(message, state)


async def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is not set. Add it to Railway Variables.")

    bot = Bot(token=token)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
