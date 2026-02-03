import os
import json
import asyncio
from typing import Optional, Tuple

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

# ВАЖНО: если у тебя старое приветствие дублировалось — оно было тут.
# Я убрал вызов handle_start, чтобы не было двух приветствий.
# from core.orchestrator import handle_start

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
                "phone": "+37163403222",
            }
        }


def google_maps_route_url(from_lat: float, from_lon: float, dest_query: str) -> str:
    dest = dest_query.replace(" ", "+")
    return f"https://www.google.com/maps/dir/?api=1&origin={from_lat},{from_lon}&destination={dest}"


def google_maps_search_url(query: str) -> str:
    q = query.replace(" ", "+")
    return f"https://www.google.com/maps/search/?api=1&query={q}"


# ---------- Doctors mapping ----------
def _contains_any(text: str, words: list[str]) -> bool:
    return any(w in text for w in words)


def guess_specialist(problem: str) -> str:
    """
    Короткая карта: симптом -> врач.
    Не диагноз. Если резко/плохо — 113.
    """
    p = (problem or "").lower().strip()

    # красные флаги в тексте
    red_flags = [
        "не хватает воздуха", "удуш", "сильная боль", "нестерпим", "обморок",
        "кровь", "кровотеч", "судорог", "парализ", "инсульт", "в груди жмет",
        "синюш", "потеря сознания",
    ]
    if _contains_any(p, red_flags):
        return "🚨 если резко/плохо — 113 (параллельно: приедет скорая)"

    # ЖКТ
    if _contains_any(p, ["живот", "желуд", "киш", "тошн", "рвот", "понос", "диар", "аппен", "гастр", "изжог", "пищев", "печен", "желч"]):
        return "гастроэнтеролог; при резкой боли — хирург (если усиливается — 113)"

    # зубы/челюсть
    if _contains_any(p, ["зуб", "десн", "челюст", "кариес", "пломб", "зуб мудр"]):
        return "стоматолог"

    # ЛОР (ухо/горло/нос)
    if _contains_any(p, ["ухо", "отит", "горло", "ангин", "нос", "гаймор", "синус", "насморк", "заложен", "пазух"]):
        return "ЛОР (отоларинголог)"

    # глаза
    if _contains_any(p, ["глаз", "зрение", "веко", "конъюнкт", "линз", "слез", "ячмен"]):
        return "офтальмолог"

    # сердце/дыхание
    if _contains_any(p, ["сердц", "давлен", "аритм", "пульс", "тахикард", "одыш", "задыш", "в груди", "астм", "бронх"]):
        return "кардиолог/пульмонолог; при боли в груди/одышке — 113"

    # неврология/голова
    if _contains_any(p, ["голова", "мигр", "головокруж", "онем", "мураш", "слабост", "невралг", "судорог"]):
        return "невролог (если внезапно/сильно — 113)"

    # спина/суставы/травмы
    if _contains_any(p, ["спина", "поясниц", "шея", "сустав", "колен", "плеч", "растяж", "ушиб", "перелом", "вывих"]):
        return "травматолог-ортопед (при травме/переломе — травмпункт)"

    # кожа
    if _contains_any(p, ["сып", "зуд", "пятн", "аллерг", "дермат", "экзем", "крапивниц", "псориаз", "прыщ", "угр"]):
        return "дерматолог (если отёк лица/удушье — 113)"

    # мочеполовая (включая “писька”)
    if _contains_any(p, ["письк", "пенис", "член", "яичк", "мошон", "простит", "уретр", "моч", "писать больно", "жжет", "цистит", "почки", "пах"]):
        return "уролог (женщинам при цистите часто — гинеколог тоже)"

    # женское здоровье
    if _contains_any(p, ["месячн", "менстр", "беремен", "выделен", "боль внизу", "матк", "яичник"]):
        return "гинеколог"

    # детское (если явно)
    if _contains_any(p, ["ребен", "ребён", "малыш", "дет"]):
        return "педиатр (если резко/тяжело — 113)"

    # психика/паника/сон
    if _contains_any(p, ["паник", "тревог", "депресс", "не сплю", "бессон", "псих", "страх"]):
        return "психотерапевт/психиатр (если риск себе/другим — 113)"

    # температура/простуда/общее
    if _contains_any(p, ["температ", "озноб", "простуд", "кашель", "слабост", "ломит", "горячк"]):
        return "терапевт (если очень плохо/не сбивается — 113)"

    # дефолт
    return "терапевт (врач общей практики)"


# ---------- Keyboards ----------
def urgency_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔴 Сильно / резко / хуже", callback_data="urgency:severe"),
                InlineKeyboardButton(text="🟡 Терпимо", callback_data="urgency:mild"),
            ]
        ]
    )


def menu_button_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🏠 Меню")]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


# Звонки делаем через callback (бот присылает номер текстом — он кликабельный)
def actions_kb(
    resources: dict,
    severe: bool,
    from_coords: Optional[Tuple[float, float]] = None,
) -> InlineKeyboardMarkup:
    hospital = resources.get("hospital", {})
    duty = resources.get("duty_doctor", {})

    buttons = []

    hosp_name = hospital.get("name", "Клиника")
    hosp_addr = hospital.get("address", "")
    dest_query = f"{hosp_name} {hosp_addr}".strip()

    if severe:
        buttons.append([InlineKeyboardButton(text="🚑 113", callback_data="call:113")])
        if hospital.get("phone"):
            buttons.append([InlineKeyboardButton(text="☎️ Клиника", callback_data="call:clinic")])

        if from_coords:
            lat, lon = from_coords
            drive_url = google_maps_route_url(lat, lon, dest_query) + "&travelmode=driving"
            buttons.append([InlineKeyboardButton(text="🚗 Маршрут", url=drive_url)])
        else:
            buttons.append([InlineKeyboardButton(text="📍 На карте", url=google_maps_search_url(dest_query))])

        buttons.append([InlineKeyboardButton(text="🚕 Bolt", url="https://bolt.eu")])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    # mild
    if duty and duty.get("phone"):
        buttons.append([InlineKeyboardButton(text="👨‍⚕️ Дежурный врач", callback_data="call:duty")])

    if hospital.get("phone"):
        buttons.append([InlineKeyboardButton(text="☎️ Клиника", callback_data="call:clinic")])

    if from_coords:
        lat, lon = from_coords
        walk_url = google_maps_route_url(lat, lon, dest_query) + "&travelmode=walking"
        transit_url = google_maps_route_url(lat, lon, dest_query) + "&travelmode=transit"
        drive_url = google_maps_route_url(lat, lon, dest_query) + "&travelmode=driving"

        buttons.append([InlineKeyboardButton(text="🚶 Пешком", url=walk_url)])
        buttons.append([InlineKeyboardButton(text="🚌 Автобус", url=transit_url)])
        buttons.append([InlineKeyboardButton(text="🚗 Машина", url=drive_url)])
    else:
        buttons.append([InlineKeyboardButton(text="📍 На карте", url=google_maps_search_url(dest_query))])

    buttons.append([InlineKeyboardButton(text="🚕 Bolt", url="https://bolt.eu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ---------- Handlers ----------
@router.message(CommandStart())
async def on_start(message: Message, state: FSMContext) -> None:
    await state.clear()

    # красивое короткое приветствие
    await message.answer(
        "👋 Привет! Я *DzīvotViegli*.\n"
        "⚡ *сложно → просто → действие*\n\n"
        "📝 Напиши, что случилось (1 строка)\n"
        "Напр.: `болит ухо` / `болит живот` / `плохо`",
        parse_mode="Markdown",
        reply_markup=main_menu(),
    )
    await state.set_state(Flow.awaiting_problem)


@router.message(Command("menu"))
async def on_menu_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🏠 Меню:", reply_markup=main_menu())
    await state.set_state(Flow.awaiting_problem)


@router.message(F.text == "🏠 Меню")
async def on_menu_button(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🏠 Меню:", reply_markup=main_menu())
    await state.set_state(Flow.awaiting_problem)


@router.message(F.text == "⬅️ Назад в меню")
async def on_back(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Ок. Выбери кнопку или напиши 1 строкой:", reply_markup=main_menu())
    await state.set_state(Flow.awaiting_problem)


@router.message(F.text == "🩺 Самочувствие")
async def on_health_menu(message: Message, state: FSMContext) -> None:
    await state.set_state(Flow.awaiting_problem)
    await message.answer(
        "🩺 Ок, напиши 1 строкой:\n"
        "Напр.: `болит ухо` / `болит зуб` / `писька болит` / `температура 39`",
        parse_mode="Markdown",
        reply_markup=main_menu(),
    )


@router.message(F.text == "🌍 Язык")
async def on_language(message: Message) -> None:
    await message.answer("Пока RU. LV подключим следующим блоком (i18n).")


@router.message(Flow.awaiting_problem, F.text)
async def on_problem_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        return

    await state.update_data(problem=text)

    await message.answer(
        f"✅ Понял: «{text}»\n\n🕒 Насколько срочно?",
        reply_markup=urgency_kb(),
    )
    await state.set_state(Flow.awaiting_urgency)


@router.callback_query(F.data.in_({"urgency:severe", "urgency:mild"}))
async def on_urgency_anytime(callback: CallbackQuery, state: FSMContext) -> None:
    severe = (callback.data == "urgency:severe")
    await state.update_data(severe=severe)

    label = "🔴 Срочно" if severe else "🟡 Терпимо"
    await callback.message.answer(
        f"Ок: {label}\n📍 Пришли геолокацию или введи адрес.",
        reply_markup=request_location_kb(),
    )
    await state.set_state(Flow.awaiting_location)
    await callback.answer("Принято")


@router.message(Flow.awaiting_location, F.text == "✍️ Ввести адрес вручную")
async def on_ask_address(message: Message, state: FSMContext) -> None:
    await message.answer(
        "✍️ Напиши адрес 1 строкой (город, улица, дом).",
        reply_markup=menu_button_kb(),
    )
    await state.set_state(Flow.awaiting_address)


@router.message(F.location)
async def on_location_anytime(message: Message, state: FSMContext) -> None:
    loc = message.location
    data = await state.get_data()

    problem = data.get("problem")
    if not problem:
        await message.answer(
            "Сначала напиши 1 строкой, что болит/что случилось.\n"
            "Напр.: `болит ухо` / `болит живот`",
            parse_mode="Markdown",
            reply_markup=menu_button_kb(),
        )
        await state.set_state(Flow.awaiting_problem)
        return

    severe = bool(data.get("severe", False))
    await state.update_data(lat=loc.latitude, lon=loc.longitude, severe=severe)

    await message.answer("✅ Геолокация принята. Собираю варианты…", reply_markup=menu_button_kb())

    resources = load_liepaja_resources()
    hospital = resources.get("hospital", {})
    duty = resources.get("duty_doctor", {})

    hosp_name = hospital.get("name", "Клиника")
    hosp_addr = hospital.get("address", "")
    hosp_phone = hospital.get("phone", "")

    info_lines = [
        f"📝 Ситуация: «{problem}»",
        f"👨‍⚕️ Подходит: {guess_specialist(problem)}",
        "",
    ]

    if severe:
        info_lines += ["🚨 Если станет хуже — 113", ""]

    if duty and duty.get("phone"):
        info_lines += [
            f"👨‍⚕️ {duty.get('name', 'Дежурный врач')}",
            f"📞 {duty.get('phone')}",
        ]
        notes = (duty.get("notes") or "").strip()
        if notes:
            info_lines += [notes]
        info_lines += [""]

    if hosp_name or hosp_addr or hosp_phone:
        info_lines += [f"🏥 {hosp_name}"]
        if hosp_addr:
            info_lines += [f"📍 {hosp_addr}"]
        if hosp_phone:
            info_lines += [f"☎️ {hosp_phone}"]
        info_lines += ["", "👇 Действия:"]

    kb = actions_kb(resources, severe=severe, from_coords=(loc.latitude, loc.longitude))
    await message.answer("\n".join([x for x in info_lines if x]), reply_markup=kb)

    await state.set_state(Flow.awaiting_problem)


@router.message(Flow.awaiting_address, F.text)
async def on_address(message: Message, state: FSMContext) -> None:
    addr = (message.text or "").strip()
    if not addr:
        return

    await state.update_data(address=addr)

    data = await state.get_data()
    resources = load_liepaja_resources()
    hospital = resources.get("hospital", {})
    duty = resources.get("duty_doctor", {})

    severe = bool(data.get("severe", False))
    problem = data.get("problem", "плохо себя чувствую")

    hosp_name = hospital.get("name", "Клиника")
    hosp_addr = hospital.get("address", "")
    hosp_phone = hospital.get("phone", "")

    info_lines = [
        f"📝 Ситуация: «{problem}»",
        f"👨‍⚕️ Подходит: {guess_specialist(problem)}",
        "",
        f"📍 Адрес: {addr}",
        "",
    ]

    if severe:
        info_lines += ["🚨 Если станет хуже — 113", ""]

    if duty and duty.get("phone"):
        info_lines += [
            f"👨‍⚕️ {duty.get('name', 'Дежурный врач')}",
            f"📞 {duty.get('phone')}",
        ]
        notes = (duty.get("notes") or "").strip()
        if notes:
            info_lines += [notes]
        info_lines += [""]

    if hosp_name or hosp_addr or hosp_phone:
        info_lines += [f"🏥 {hosp_name}"]
        if hosp_addr:
            info_lines += [f"📍 {hosp_addr}"]
        if hosp_phone:
            info_lines += [f"☎️ {hosp_phone}"]
        info_lines += ["", "👇 Действия:"]

    kb = actions_kb(resources, severe=severe, from_coords=None)
    await message.answer("\n".join([x for x in info_lines if x]), reply_markup=kb)
    await message.answer("🏠 Меню — кнопка снизу.", reply_markup=menu_button_kb())
    await state.set_state(Flow.awaiting_problem)


@router.callback_query(F.data.startswith("call:"))
async def on_call_callback(callback: CallbackQuery) -> None:
    resources = load_liepaja_resources()
    hospital = resources.get("hospital", {})
    duty = resources.get("duty_doctor", {})

    hosp_phone = (hospital.get("phone", "") or "").strip()
    hosp_name = hospital.get("name", "Клиника")

    duty_phone = (duty.get("phone", "") or "").strip()
    duty_name = duty.get("name", "Дежурный врач")

    key = callback.data.split(":", 1)[1]

    if key == "113":
        await callback.message.answer("🚑 Срочно: 113\nНажми на номер, чтобы позвонить.", reply_markup=menu_button_kb())
        await callback.answer("113")
        return

    if key == "clinic":
        if hosp_phone:
            await callback.message.answer(
                f"☎️ {hosp_name}\n{hosp_phone}\nНажми на номер, чтобы позвонить.",
                reply_markup=menu_button_kb(),
            )
            await callback.answer("Клиника")
        else:
            await callback.answer("Номер клиники не задан", show_alert=True)
        return

    if key == "duty":
        if duty_phone:
            txt = f"👨‍⚕️ {duty_name}\n{duty_phone}\nНажми на номер, чтобы позвонить."
            notes = (duty.get("notes") or "").strip()
            if notes:
                txt += f"\n\n{notes}"
            await callback.message.answer(txt, reply_markup=menu_button_kb())
            await callback.answer("Дежурный врач")
        else:
            await callback.answer("Номер дежурного врача не задан", show_alert=True)
        return

    await callback.answer("Ок")


@router.message(F.text)
async def fallback_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        return

    if text in {"🩺 Самочувствие", "🌍 Язык", "⬅️ Назад в меню", "🏠 Меню"}:
        return

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
