import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import ReplyKeyboardBuilder
import aiosqlite

# Логи
logging.basicConfig(level=logging.INFO)

# Токен бота
BOT_TOKEN = "8717650314:AAElCMXuoZsCFMcowm1GqOOnqfGrgycQUtQ"

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

DB_NAME = "events.db"


class EventStates(StatesGroup):
    waiting_for_title = State()  # Ждем название события
    waiting_for_date = State()  # Ждем дату (ГГГГ-ММ-ДД)
    waiting_for_time = State()  # Ждем время
    waiting_for_reminder = State()  # Ждем время напоминания (текстовый ввод)
    waiting_for_event_to_remove = State()  # Ждем событие для удаления


# Инициализация базы данных
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Создаем таблицу событий
        await db.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                event_date TEXT NOT NULL,
                event_time TEXT NOT NULL,
                reminder_hours INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        ''')

        # Создаем индексы для быстрого поиска
        await db.execute('CREATE INDEX IF NOT EXISTS idx_event_date ON events(event_date)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_user_id ON events(user_id)')

        await db.commit()


# Класс для работы с событиями
class EventManager:
    @staticmethod
    async def add_event(user_id: int, title: str, event_date: str, event_time: str, reminder_hours: int):
        """Добавление нового события"""
        async with aiosqlite.connect(DB_NAME) as db:
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            await db.execute('''
                INSERT INTO events (user_id, title, event_date, event_time, reminder_hours, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, title, event_date, event_time, reminder_hours, created_at))
            await db.commit()

    @staticmethod
    async def get_user_events(user_id: int, days_ahead: int = 30):
        """Получение событий пользователя на указанное количество дней вперед"""
        async with aiosqlite.connect(DB_NAME) as db:
            today = datetime.now().strftime("%Y-%m-%d")
            future_date = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

            cursor = await db.execute('''
                SELECT id, title, event_date, event_time, reminder_hours 
                FROM events 
                WHERE user_id = ? AND event_date BETWEEN ? AND ?
                ORDER BY event_date, event_time
            ''', (user_id, today, future_date))

            return await cursor.fetchall()

    @staticmethod
    async def get_event_by_id(event_id: int, user_id: int):
        """Получение события по ID"""
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                'SELECT id, title, event_date, event_time, reminder_hours FROM events WHERE id = ? AND user_id = ?',
                (event_id, user_id)
            )
            return await cursor.fetchone()

    @staticmethod
    async def remove_event(event_id: int, user_id: int):
        """Удаление события"""
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                'DELETE FROM events WHERE id = ? AND user_id = ?',
                (event_id, user_id)
            )
            await db.commit()

    @staticmethod
    async def get_events_for_reminder():
        """Получение событий, для которых нужно отправить напоминание"""
        async with aiosqlite.connect(DB_NAME) as db:
            now = datetime.now()
            events_to_notify = []

            # Получаем все события
            cursor = await db.execute('''
                SELECT id, user_id, title, event_date, event_time, reminder_hours 
                FROM events
            ''')

            async for row in cursor:
                event_id, user_id, title, event_date, event_time, reminder_hours = row

                # Формируем дату и время события
                event_datetime = datetime.strptime(f"{event_date} {event_time}", "%Y-%m-%d %H:%M")

                # Вычисляем время напоминания
                reminder_time = event_datetime - timedelta(hours=reminder_hours)

                # Проверяем, нужно ли отправить напоминание сейчас
                # (с точностью до минуты)
                if reminder_time <= now < reminder_time + timedelta(minutes=1):
                    events_to_notify.append({
                        'user_id': user_id,
                        'title': title,
                        'event_datetime': event_datetime,
                        'reminder_hours': reminder_hours
                    })

            return events_to_notify


# Клавиатуры
def get_main_keyboard():
    """Основная клавиатура с командами"""
    builder = ReplyKeyboardBuilder()
    builder.button(text="📅 Мои события")
    builder.button(text="➕ Добавить событие")
    builder.button(text="❌ Удалить событие")
    builder.button(text="📋 Помощь")
    builder.adjust(2, 2)
    return builder.as_markup(resize_keyboard=True)


def get_events_keyboard(events):
    """Клавиатура со списком событий для удаления"""
    builder = InlineKeyboardBuilder()
    for event_id, title, event_date, event_time, _ in events:
        display_text = f"{title} ({event_date} {event_time})"
        builder.button(text=display_text, callback_data=f"remove_{event_id}")
    builder.button(text="❌ Отмена", callback_data="cancel_remove")
    builder.adjust(1)
    return builder.as_markup()


# Обработчики команд
@dp.message(CommandStart())
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    await message.answer(
        "👋 Привет! Я бот для управления событиями и напоминаниями!\n\n"
        "Я помогу тебе не забыть о важных делах. Используй команды:\n"
        "📅 /events - показать мои события\n"
        "➕ /addevent - добавить новое событие\n"
        "❌ /removeevent - удалить событие\n"
        "ℹ️ /help - помощь",
        reply_markup=get_main_keyboard()
    )


@dp.message(F.text == "📋 Помощь")
@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help"""
    await message.answer(
        "🤖 Доступные команды:\n\n"
        "📅 /events - показать список ваших событий\n"
        "➕ /addevent - добавить новое событие\n"
        "❌ /removeevent - удалить событие\n"
        "ℹ️ /help - показать это сообщение\n\n"
        "📝 Как добавить событие:\n"
        "1. Нажмите /addevent\n"
        "2. Введите название события\n"
        "3. Введите дату в формате ГГГГ-ММ-ДД (например, 2026-03-15)\n"
        "4. Введите время в формате ЧЧ:ММ (например, 15:30)\n"
        "5. Введите за сколько часов напомнить (целое число от 1 до 168)\n\n"
        "Бот автоматически напомнит вам о событии в указанное время!"
    )


@dp.message(F.text == "📅 Мои события")
@dp.message(Command("events"))
async def cmd_events(message: Message):
    """Обработчик команды /events"""
    user_id = message.from_user.id
    events = await EventManager.get_user_events(user_id)

    if not events:
        await message.answer(
            "📭 У вас пока нет предстоящих событий.\n"
            "Используйте /addevent чтобы создать событие!"
        )
        return

    response = "📅 **Ваши предстоящие события:**\n\n"
    for i, event in enumerate(events, 1):
        event_id, title, event_date, event_time, reminder = event
        # Преобразуем дату для красивого отображения
        date_obj = datetime.strptime(event_date, "%Y-%m-%d")
        display_date = date_obj.strftime("%d.%m.%Y")
        response += f"{i}. **{title}**\n"
        response += f"   📆 {display_date} в {event_time}\n"
        response += f"   ⏰ Напоминание за {reminder} ч.\n\n"

    await message.answer(response, parse_mode="Markdown")


@dp.message(F.text == "➕ Добавить событие")
@dp.message(Command("addevent"))
async def cmd_addevent(message: Message, state: FSMContext):
    """Начало процесса добавления события"""
    await state.set_state(EventStates.waiting_for_title)
    await message.answer(
        "📝 Введите название события:",
        reply_markup=None
    )


@dp.message(EventStates.waiting_for_title)
async def process_title(message: Message, state: FSMContext):
    """Обработка названия события"""
    if len(message.text) > 100:
        await message.answer("❌ Название слишком длинное! Максимум 100 символов. Попробуйте еще раз:")
        return

    await state.update_data(title=message.text)
    await state.set_state(EventStates.waiting_for_date)
    await message.answer(
        "📅 Введите дату события в формате **ГГГГ-ММ-ДД**\n"
        "Например: 2026-03-15",
        parse_mode="Markdown"
    )


@dp.message(EventStates.waiting_for_date)
async def process_date(message: Message, state: FSMContext):
    """Обработка даты события в формате ГГГГ-ММ-ДД"""
    date_str = message.text.strip()

    try:
        # Проверяем формат даты ГГГГ-ММ-ДД
        event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        today = datetime.now().date()

        if event_date < today:
            await message.answer("❌ Дата не может быть в прошлом! Введите будущую дату в формате ГГГГ-ММ-ДД:")
            return

        await state.update_data(event_date=date_str)
        await state.set_state(EventStates.waiting_for_time)
        await message.answer(
            "⏰ Введите время события в формате **ЧЧ:ММ**\n"
            "Например: 15:30",
            parse_mode="Markdown"
        )
    except ValueError:
        await message.answer(
            "❌ Неверный формат даты! Используйте **ГГГГ-ММ-ДД**\n"
            "Например: 2026-03-15",
            parse_mode="Markdown"
        )


@dp.message(EventStates.waiting_for_time)
async def process_time(message: Message, state: FSMContext):
    """Обработка времени события"""
    time_str = message.text.strip()

    try:
        # Проверяем формат времени
        datetime.strptime(time_str, "%H:%M")

        await state.update_data(event_time=time_str)
        await state.set_state(EventStates.waiting_for_reminder)

        await message.answer(
            "⏱ **За сколько часов напомнить?**\n\n"
            "Введите целое число от 1 до 168 (максимум 7 дней)\n"
            "Например: 2 (напомнить за 2 часа), 24 (напомнить за сутки)",
            parse_mode="Markdown"
        )
    except ValueError:
        await message.answer(
            "❌ Неверный формат времени! Используйте **ЧЧ:ММ**\n"
            "Например: 15:30",
            parse_mode="Markdown"
        )


@dp.message(EventStates.waiting_for_reminder)
async def process_reminder_text(message: Message, state: FSMContext):
    """Обработка текстового ввода времени напоминания"""
    try:
        reminder_hours = int(message.text.strip())

        # Проверяем, что число положительное и разумное (максимум 168 часов = 7 дней)
        if reminder_hours <= 0:
            await message.answer("❌ Количество часов должно быть положительным числом! Введите снова:")
            return
        if reminder_hours > 168:
            await message.answer("❌ Максимальное время напоминания - 168 часов (7 дней). Введите меньшее число:")
            return

        user_data = await state.get_data()

        # Сохраняем событие в базу данных
        await EventManager.add_event(
            user_id=message.from_user.id,
            title=user_data['title'],
            event_date=user_data['event_date'],
            event_time=user_data['event_time'],
            reminder_hours=reminder_hours
        )

        # Преобразуем дату для красивого отображения
        date_obj = datetime.strptime(user_data['event_date'], "%Y-%m-%d")
        display_date = date_obj.strftime("%d.%m.%Y")

        await message.answer(
            f"✅ **Событие успешно добавлено!**\n\n"
            f"📝 {user_data['title']}\n"
            f"📆 {display_date} в {user_data['event_time']}\n"
            f"⏰ Напомню за {reminder_hours} ч.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )

        await state.clear()

    except ValueError:
        await message.answer(
            "❌ Пожалуйста, введите целое число часов.\n"
            "Например: 1, 2, 24, 48",
            parse_mode="Markdown"
        )


@dp.message(F.text == "❌ Удалить событие")
@dp.message(Command("removeevent"))
async def cmd_removeevent(message: Message, state: FSMContext):
    """Начало процесса удаления события"""
    user_id = message.from_user.id
    events = await EventManager.get_user_events(user_id)

    if not events:
        await message.answer(
            "📭 У вас нет событий для удаления.",
            reply_markup=get_main_keyboard()
        )
        return

    await state.set_state(EventStates.waiting_for_event_to_remove)

    # Формируем список событий с номерами для выбора
    response = "❌ **Выберите событие для удаления:**\n\n"
    for i, event in enumerate(events, 1):
        event_id, title, event_date, event_time, _ = event
        # Преобразуем дату для красивого отображения
        date_obj = datetime.strptime(event_date, "%Y-%m-%d")
        display_date = date_obj.strftime("%d.%m.%Y")
        response += f"{i}. {title} ({display_date} {event_time})\n"
    response += "\nОтправьте номер события для удаления или /cancel для отмены"

    # Сохраняем список событий в состоянии
    await state.update_data(events_list=events)

    await message.answer(response, parse_mode="Markdown")


@dp.message(EventStates.waiting_for_event_to_remove)
async def process_remove_by_number(message: Message, state: FSMContext):
    """Обработка удаления события по номеру"""
    if message.text == "/cancel":
        await message.answer("❌ Удаление отменено.", reply_markup=get_main_keyboard())
        await state.clear()
        return

    try:
        choice = int(message.text.strip())
        data = await state.get_data()
        events = data.get('events_list', [])

        if 1 <= choice <= len(events):
            event_to_remove = events[choice - 1]
            event_id = event_to_remove[0]

            # Удаляем событие
            await EventManager.remove_event(event_id, message.from_user.id)

            await message.answer(
                f"✅ Событие **{event_to_remove[1]}** успешно удалено!",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
            await state.clear()
        else:
            await message.answer(
                f"❌ Введите номер от 1 до {len(events)} или /cancel для отмены:"
            )
    except ValueError:
        await message.answer(
            "❌ Пожалуйста, введите номер события или /cancel для отмены:"
        )


# Обработчик текстовых сообщений (не команд)
@dp.message(F.text)
async def handle_text(message: Message):
    """Обработчик текстовых сообщений"""
    if message.text == "📅 Мои события":
        await cmd_events(message)
    elif message.text == "➕ Добавить событие":
        await cmd_addevent(message, None)
    elif message.text == "❌ Удалить событие":
        await cmd_removeevent(message, None)
    elif message.text == "📋 Помощь":
        await cmd_help(message)
    else:
        await message.answer(
            "Я не понимаю эту команду. Используйте /help для списка команд.",
            reply_markup=get_main_keyboard()
        )


# Фоновая задача для проверки напоминаний
async def check_reminders():
    """Проверка и отправка напоминаний"""
    while True:
        try:
            events_to_notify = await EventManager.get_events_for_reminder()

            for event in events_to_notify:
                try:
                    # Преобразуем дату для красивого отображения в напоминании
                    display_date = event['event_datetime'].strftime("%d.%m.%Y")

                    await bot.send_message(
                        chat_id=event['user_id'],
                        text=f"🔔 **НАПОМИНАНИЕ!**\n\n"
                             f"📝 Событие: {event['title']}\n"
                             f"⏰ Начнется через {event['reminder_hours']} ч.\n"
                             f"🕐 Время: {display_date} в {event['event_datetime'].strftime('%H:%M')}",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logging.error(f"Ошибка отправки напоминания: {e}")

            # Проверяем каждую минуту
            await asyncio.sleep(60)

        except Exception as e:
            logging.error(f"Ошибка в check_reminders: {e}")
            await asyncio.sleep(60)


# Основная функция
async def main():
    print("Инициализация базы данных...")
    await init_db()

    print("Запуск обработчика напоминаний...")
    asyncio.create_task(check_reminders())

    print("Бот запускается...")
    try:
        # Запускаем поллинг
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        print("Получен сигнал остановки...")
    finally:
        print("Закрываем соединения...")
        await bot.session.close()
        print("Бот остановлен.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nБот остановлен пользователем (Ctrl+C)")