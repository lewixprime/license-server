"""
Telegram бот для управления лицензиями (aiogram 3.x)
Версия: 2.0 - Полностью асинхронный с логированием
"""

import asyncio
import logging
import os
import sys
from datetime import datetime
from functools import wraps
from typing import Optional, Tuple, Any

import aiohttp
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, 
    CallbackQuery, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    ErrorEvent
)
from aiogram.filters import Command
from aiogram.enums import ParseMode

# ==================== КОНФИГУРАЦИЯ ====================

# Загрузка переменных окружения
load_dotenv()

class Config:
    """Конфигурация бота"""
    TELEGRAM_BOT_TOKEN: str = os.getenv('TELEGRAM_BOT_TOKEN', '')
    ADMIN_USER_ID: int = int(os.getenv('ADMIN_USER_ID', '0'))
    SERVER_URL: str = os.getenv('SERVER_URL', '').rstrip('/')
    ADMIN_PASSWORD: str = os.getenv('ADMIN_PASSWORD', '')
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
    REQUEST_TIMEOUT: int = 30
    
    @classmethod
    def validate(cls) -> bool:
        """Проверка что все настройки заданы"""
        errors = []
        if not cls.TELEGRAM_BOT_TOKEN:
            errors.append("TELEGRAM_BOT_TOKEN не задан")
        if not cls.ADMIN_USER_ID:
            errors.append("ADMIN_USER_ID не задан")
        if not cls.SERVER_URL:
            errors.append("SERVER_URL не задан")
        if not cls.ADMIN_PASSWORD:
            errors.append("ADMIN_PASSWORD не задан")
        
        if errors:
            for error in errors:
                logging.error(f"❌ Ошибка конфигурации: {error}")
            return False
        return True


# ==================== ЛОГИРОВАНИЕ ====================

def setup_logging():
    """Настройка логирования"""
    log_format = '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'
    
    logging.basicConfig(
        level=getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO),
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Уменьшаем логи от aiohttp
    logging.getLogger('aiohttp').setLevel(logging.WARNING)
    logging.getLogger('aiogram').setLevel(logging.WARNING)

logger = logging.getLogger('LicenseBot')


# ==================== КОНСТАНТЫ ====================

LICENSE_TYPES = {
    "trial_1day": {"name": "1 Day", "price": "$2", "emoji": "🕐"},
    "trial_3days": {"name": "3 Days", "price": "$5", "emoji": "📅"},
    "weekly": {"name": "Weekly", "price": "$8", "emoji": "📆"},
    "monthly": {"name": "Monthly", "price": "$20", "emoji": "🗓"},
    "yearly": {"name": "Yearly", "price": "$150", "emoji": "📊"},
    "lifetime": {"name": "Lifetime", "price": "$250", "emoji": "♾"},
}


# ==================== API КЛИЕНТ ====================

class LicenseAPI:
    """Асинхронный клиент для License Server API"""
    
    def __init__(self, base_url: str, password: str):
        self.base_url = base_url
        self.headers = {"Authorization": f"Bearer {password}"}
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def get_session(self) -> aiohttp.ClientSession:
        """Получить или создать сессию"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=Config.REQUEST_TIMEOUT)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session
    
    async def close(self):
        """Закрыть сессию"""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def _request(
        self, 
        method: str, 
        endpoint: str, 
        json_data: dict = None
    ) -> Tuple[bool, Any]:
        """
        Выполнить запрос к API
        Возвращает: (успех, данные или сообщение об ошибке)
        """
        url = f"{self.base_url}{endpoint}"
        session = await self.get_session()
        
        try:
            if method == "GET":
                async with session.get(url, headers=self.headers) as resp:
                    data = await resp.json()
                    if resp.status == 200:
                        return True, data
                    return False, data.get("error", f"HTTP {resp.status}")
            else:
                async with session.post(url, json=json_data, headers=self.headers) as resp:
                    data = await resp.json()
                    if resp.status == 200:
                        return True, data
                    return False, data.get("error", f"HTTP {resp.status}")
                    
        except asyncio.TimeoutError:
            logger.error(f"Timeout при запросе к {endpoint}")
            return False, "Сервер не отвечает (timeout)"
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка соединения с {endpoint}: {e}")
            return False, f"Ошибка соединения: {str(e)}"
        except Exception as e:
            logger.error(f"Неожиданная ошибка при запросе к {endpoint}: {e}")
            return False, f"Неожиданная ошибка: {str(e)}"
    
    async def generate_key(self, license_type: str, count: int = 1) -> Tuple[bool, Any]:
        """Генерация ключей"""
        logger.info(f"Генерация ключа: type={license_type}, count={count}")
        return await self._request("POST", "/admin/generate", {
            "type": license_type,
            "count": count
        })
    
    async def list_keys(self) -> Tuple[bool, Any]:
        """Получение списка ключей"""
        logger.info("Запрос списка ключей")
        return await self._request("GET", "/admin/list")
    
    async def block_key(self, key: str) -> Tuple[bool, Any]:
        """Блокировка ключа"""
        logger.info(f"Блокировка ключа: {key[:16]}...")
        return await self._request("POST", "/admin/block", {"key": key})
    
    async def get_stats(self) -> Tuple[bool, Any]:
        """Получение статистики"""
        logger.info("Запрос статистики")
        return await self._request("GET", "/admin/stats")


# Глобальный экземпляр API клиента
api: Optional[LicenseAPI] = None


# ==================== КЛАВИАТУРЫ ====================

def get_main_keyboard() -> InlineKeyboardMarkup:
    """Главное меню"""
    buttons = [
        [InlineKeyboardButton(text="🔑 Генерация ключей", callback_data="generate")],
        [InlineKeyboardButton(text="📋 Список ключей", callback_data="list")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton(text="🚫 Заблокировать ключ", callback_data="block")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_generate_keyboard() -> InlineKeyboardMarkup:
    """Меню выбора типа лицензии"""
    buttons = []
    for key, info in LICENSE_TYPES.items():
        text = f"{info['emoji']} {info['name']} ({info['price']})"
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"gen_{key}")])
    
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_back_keyboard() -> InlineKeyboardMarkup:
    """Кнопка назад"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
    ])


def get_after_generate_keyboard(license_type: str) -> InlineKeyboardMarkup:
    """Меню после генерации ключа"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Ещё один такой же", callback_data=f"gen_{license_type}")],
        [InlineKeyboardButton(text="🔑 Другой тип", callback_data="generate")],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="back")]
    ])


# ==================== ДЕКОРАТОРЫ ====================

def admin_only(func):
    """Декоратор проверки прав администратора для callback"""
    @wraps(func)
    async def wrapper(callback: CallbackQuery, *args, **kwargs):
        if callback.from_user.id != Config.ADMIN_USER_ID:
            logger.warning(f"Попытка доступа от неавторизованного пользователя: {callback.from_user.id}")
            await callback.answer("❌ У вас нет доступа", show_alert=True)
            return
        return await func(callback, *args, **kwargs)
    return wrapper


def admin_only_message(func):
    """Декоратор проверки прав администратора для сообщений"""
    @wraps(func)
    async def wrapper(message: Message, *args, **kwargs):
        if message.from_user.id != Config.ADMIN_USER_ID:
            logger.warning(f"Попытка доступа от неавторизованного пользователя: {message.from_user.id}")
            await message.answer("❌ У вас нет доступа к этому боту")
            return
        return await func(message, *args, **kwargs)
    return wrapper


def handle_errors(func):
    """Декоратор обработки ошибок для callback"""
    @wraps(func)
    async def wrapper(callback: CallbackQuery, *args, **kwargs):
        try:
            return await func(callback, *args, **kwargs)
        except Exception as e:
            logger.exception(f"Ошибка в {func.__name__}: {e}")
            try:
                await callback.message.edit_text(
                    f"❌ Произошла ошибка: {str(e)}\n\n"
                    "Попробуйте позже или обратитесь к разработчику.",
                    reply_markup=get_back_keyboard()
                )
            except:
                pass
            await callback.answer("Произошла ошибка", show_alert=True)
    return wrapper


# ==================== РОУТЕР И ОБРАБОТЧИКИ ====================

router = Router()


@router.message(Command("start"))
@admin_only_message
async def cmd_start(message: Message):
    """Команда /start - главное меню"""
    logger.info(f"Пользователь {message.from_user.id} открыл главное меню")
    
    await message.answer(
        "🔐 *Админ-панель управления лицензиями*\n\n"
        f"👤 Администратор: `{message.from_user.id}`\n"
        f"📡 Сервер: `{Config.SERVER_URL}`\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )


@router.message(Command("help"))
@admin_only_message
async def cmd_help(message: Message):
    """Команда /help - справка"""
    help_text = """
🔐 *Справка по командам*

/start - Главное меню
/help - Эта справка
/block `КЛЮЧ` - Заблокировать ключ
/stats - Статистика сервера

*Типы лицензий:*
🕐 1 Day - $2
📅 3 Days - $5
📆 Weekly - $8
🗓 Monthly - $20
📊 Yearly - $150
♾ Lifetime - $250
"""
    await message.answer(help_text, parse_mode=ParseMode.MARKDOWN)


@router.message(Command("block"))
@admin_only_message
async def cmd_block(message: Message):
    """Команда /block KEY - блокировка ключа"""
    args = message.text.split(maxsplit=1)
    
    if len(args) != 2:
        await message.answer(
            "❌ *Неверный формат*\n\n"
            "Использование: `/block КЛЮЧ`\n\n"
            "Пример: `/block ABC123-DEF456-GHI789`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    key = args[1].strip()
    
    success, result = await api.block_key(key)
    
    if success:
        logger.info(f"Ключ заблокирован: {key[:16]}...")
        await message.answer(
            f"✅ *Ключ заблокирован*\n\n"
            f"🔑 `{key}`",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await message.answer(f"❌ Ошибка: {result}")


@router.message(Command("stats"))
@admin_only_message
async def cmd_stats(message: Message):
    """Команда /stats - статистика"""
    await show_stats_message(message)


async def show_stats_message(message: Message):
    """Показать статистику в сообщении"""
    success, result = await api.get_stats()
    
    if success:
        stats = result
        text = (
            "📊 *Статистика сервера*\n\n"
            f"📝 Всего лицензий: `{stats.get('total', 0)}`\n"
            f"✅ Активировано: `{stats.get('activated', 0)}`\n"
            f"🚫 Заблокировано: `{stats.get('blocked', 0)}`\n"
            f"⏳ Ожидают активации: `{stats.get('pending', 0)}`\n"
        )
        await message.answer(text, parse_mode=ParseMode.MARKDOWN)
    else:
        await message.answer(f"❌ Ошибка получения статистики: {result}")


# ==================== CALLBACK ОБРАБОТЧИКИ ====================

@router.callback_query(F.data == "back")
@admin_only
@handle_errors
async def cb_back(callback: CallbackQuery):
    """Возврат в главное меню"""
    await callback.message.edit_text(
        "🔐 *Админ-панель управления лицензиями*\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()


@router.callback_query(F.data == "generate")
@admin_only
@handle_errors
async def cb_generate(callback: CallbackQuery):
    """Меню генерации ключей"""
    logger.info(f"Открыто меню генерации ключей")
    
    await callback.message.edit_text(
        "🔑 *Генерация нового ключа*\n\n"
        "Выберите тип лицензии:",
        reply_markup=get_generate_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()


@router.callback_query(F.data == "list")
@admin_only
@handle_errors
async def cb_list(callback: CallbackQuery):
    """Список всех ключей"""
    logger.info("Запрошен список ключей")
    
    success, result = await api.list_keys()
    
    if not success:
        await callback.message.edit_text(
            f"❌ Ошибка: {result}",
            reply_markup=get_back_keyboard()
        )
        await callback.answer()
        return
    
    licenses = result.get("licenses", [])
    
    if not licenses:
        await callback.message.edit_text(
            "📋 *Список лицензий*\n\n"
            "_Нет лицензий_",
            reply_markup=get_back_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        await callback.answer()
        return
    
    # Формируем текст
    text = "📋 *Последние 10 лицензий:*\n\n"
    
    for lic in licenses[:10]:
        if lic.get("blocked"):
            status = "🚫"
        elif lic.get("activated"):
            status = "✅"
        else:
            status = "⏳"
        
        license_info = LICENSE_TYPES.get(lic.get("type", ""), {})
        type_emoji = license_info.get("emoji", "🔑")
        
        text += f"{status} `{lic['key'][:20]}...`\n"
        text += f"    {type_emoji} {lic.get('type', 'unknown')}"
        
        if lic.get("activated") and lic.get("hwid"):
            text += f" | HWID: `{lic['hwid'][:8]}...`"
        
        text += "\n\n"
    
    # Статистика
    total = len(licenses)
    activated = sum(1 for l in licenses if l.get("activated"))
    blocked = sum(1 for l in licenses if l.get("blocked"))
    
    text += f"━━━━━━━━━━━━━━━\n"
    text += f"📊 Всего: {total} | ✅ Активных: {activated} | 🚫 Заблокированных: {blocked}"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_back_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()


@router.callback_query(F.data == "stats")
@admin_only
@handle_errors
async def cb_stats(callback: CallbackQuery):
    """Статистика сервера"""
    logger.info("Запрошена статистика")
    
    success, result = await api.get_stats()
    
    if success:
        stats = result
        text = (
            "📊 *Статистика сервера*\n\n"
            f"📝 Всего лицензий: `{stats.get('total', 0)}`\n"
            f"✅ Активировано: `{stats.get('activated', 0)}`\n"
            f"🚫 Заблокировано: `{stats.get('blocked', 0)}`\n"
            f"⏳ Ожидают активации: `{stats.get('pending', 0)}`\n\n"
            f"🕐 Обновлено: {datetime.now().strftime('%H:%M:%S')}"
        )
    else:
        text = f"❌ Ошибка: {result}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="stats")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
    ])
    
    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()


@router.callback_query(F.data == "block")
@admin_only
@handle_errors
async def cb_block(callback: CallbackQuery):
    """Инструкция по блокировке"""
    await callback.message.edit_text(
        "🚫 *Блокировка ключа*\n\n"
        "Чтобы заблокировать ключ, отправьте команду:\n\n"
        "`/block ВАSH_КЛЮЧ`\n\n"
        "Пример:\n"
        "`/block TRIAL-ABC123-DEF456`\n\n"
        "_После блокировки пользователь не сможет использовать программу_",
        reply_markup=get_back_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()


@router.callback_query(F.data.startswith("gen_"))
@admin_only
@handle_errors
async def cb_gen_key(callback: CallbackQuery):
    """Генерация ключа выбранного типа"""
    license_type = callback.data.replace("gen_", "")
    
    logger.info(f"Генерация ключа типа: {license_type}")
    
    # Показываем что идёт генерация
    await callback.message.edit_text(
        "⏳ *Генерация ключа...*",
        parse_mode=ParseMode.MARKDOWN
    )
    
    success, result = await api.generate_key(license_type)
    
    if success:
        key = result["keys"][0]
        info = LICENSE_TYPES.get(license_type, {"name": license_type, "price": "?", "emoji": "🔑"})
        
        logger.info(f"Ключ сгенерирован: {key[:16]}...")
        
        await callback.message.edit_text(
            f"✅ *Ключ успешно сгенерирован!*\n\n"
            f"{info['emoji']} Тип: *{info['name']}* ({info['price']})\n\n"
            f"🔑 Ключ:\n`{key}`\n\n"
            f"_Нажмите на ключ чтобы скопировать_\n\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            reply_markup=get_after_generate_keyboard(license_type),
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await callback.message.edit_text(
            f"❌ *Ошибка генерации*\n\n{result}",
            reply_markup=get_back_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
    
    await callback.answer()


# ==================== ОБРАБОТКА ОШИБОК ====================

@router.error()
async def error_handler(event: ErrorEvent):
    """Глобальный обработчик ошибок"""
    logger.exception(f"Необработанная ошибка: {event.exception}")


# ==================== ЗАПУСК ====================

async def on_startup(bot: Bot):
    """Действия при запуске"""
    me = await bot.get_me()
    logger.info(f"Бот запущен: @{me.username}")
    logger.info(f"Сервер лицензий: {Config.SERVER_URL}")
    logger.info(f"ID администратора: {Config.ADMIN_USER_ID}")


async def on_shutdown(bot: Bot):
    """Действия при остановке"""
    logger.info("Бот останавливается...")
    if api:
        await api.close()
    logger.info("Бот остановлен")


async def main():
    """Главная функция запуска"""
    global api
    
    # Настройка логирования
    setup_logging()
    
    logger.info("=" * 50)
    logger.info("🤖 Запуск License Admin Bot v2.0")
    logger.info("=" * 50)
    
    # Проверка конфигурации
    if not Config.validate():
        logger.error("Ошибка конфигурации. Проверьте переменные окружения.")
        sys.exit(1)
    
    # Инициализация API клиента
    api = LicenseAPI(Config.SERVER_URL, Config.ADMIN_PASSWORD)
    
    # Создание бота и диспетчера
    bot = Bot(token=Config.TELEGRAM_BOT_TOKEN)
    dp = Dispatcher()
    
    # Регистрация роутера
    dp.include_router(router)
    
    # Регистрация событий
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    try:
        # Удаляем старые апдейты и запускаем polling
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await api.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.exception(f"Критическая ошибка: {e}")
        sys.exit(1)
