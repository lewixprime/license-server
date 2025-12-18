"""
Telegram Admin Bot v2.0 - Расширенная версия
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
    InlineKeyboardMarkup
)
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ==================== КОНФИГУРАЦИЯ ====================

load_dotenv()

class Config:
    TELEGRAM_BOT_TOKEN: str = os.getenv('TELEGRAM_BOT_TOKEN', '')
    ADMIN_USER_ID: int = int(os.getenv('ADMIN_USER_ID', '0'))
    SERVER_URL: str = os.getenv('SERVER_URL', '').rstrip('/')
    ADMIN_PASSWORD: str = os.getenv('ADMIN_PASSWORD', '')
    REQUEST_TIMEOUT: int = 30
    
    @classmethod
    def validate(cls) -> bool:
        errors = []
        if not cls.TELEGRAM_BOT_TOKEN:
            errors.append("TELEGRAM_BOT_TOKEN")
        if not cls.ADMIN_USER_ID:
            errors.append("ADMIN_USER_ID")
        if not cls.SERVER_URL:
            errors.append("SERVER_URL")
        if not cls.ADMIN_PASSWORD:
            errors.append("ADMIN_PASSWORD")
        if errors:
            print(f"❌ Не заданы: {', '.join(errors)}")
            return False
        return True


# Логирование
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger('AdminBot')


# ==================== КОНСТАНТЫ ====================

LICENSE_TYPES = {
    "trial_1day": {"name": "1 Day", "price": "$2", "emoji": "🕐"},
    "trial_3days": {"name": "3 Days", "price": "$5", "emoji": "📅"},
    "weekly": {"name": "Weekly", "price": "$8", "emoji": "📆"},
    "monthly": {"name": "Monthly", "price": "$20", "emoji": "🗓"},
    "yearly": {"name": "Yearly", "price": "$150", "emoji": "📊"},
    "lifetime": {"name": "Lifetime", "price": "$250", "emoji": "♾"},
}


# ==================== FSM STATES ====================

class AdminStates(StatesGroup):
    waiting_for_key_to_block = State()
    waiting_for_key_to_unblock = State()
    waiting_for_key_to_reset = State()
    waiting_for_key_to_extend = State()
    waiting_for_extend_days = State()
    waiting_for_key_to_delete = State()
    waiting_for_search_query = State()


# ==================== API КЛИЕНТ ====================

class LicenseAPI:
    def __init__(self):
        self.base_url = Config.SERVER_URL
        self.headers = {"Authorization": f"Bearer {Config.ADMIN_PASSWORD}"}
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=Config.REQUEST_TIMEOUT)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session
    
    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def _request(self, method: str, endpoint: str, json_data: dict = None, params: dict = None) -> Tuple[bool, Any]:
        url = f"{self.base_url}{endpoint}"
        session = await self.get_session()
        
        try:
            if method == "GET":
                async with session.get(url, headers=self.headers, params=params) as resp:
                    data = await resp.json()
                    return resp.status == 200, data
            else:
                async with session.post(url, json=json_data, headers=self.headers) as resp:
                    data = await resp.json()
                    return resp.status == 200, data
        except asyncio.TimeoutError:
            return False, "Сервер не отвечает"
        except Exception as e:
            return False, str(e)
    
    async def generate_key(self, license_type: str, count: int = 1) -> Tuple[bool, Any]:
        return await self._request("POST", "/admin/generate", {"type": license_type, "count": count})
    
    async def list_keys(self, limit: int = 100, status: str = None) -> Tuple[bool, Any]:
        params = {"limit": limit}
        if status:
            params["status"] = status
        return await self._request("GET", "/admin/list", params=params)
    
    async def block_key(self, key: str) -> Tuple[bool, Any]:
        return await self._request("POST", "/admin/block", {"key": key})
    
    async def unblock_key(self, key: str) -> Tuple[bool, Any]:
        return await self._request("POST", "/admin/unblock", {"key": key})
    
    async def reset_hwid(self, key: str) -> Tuple[bool, Any]:
        return await self._request("POST", "/admin/reset-hwid", {"key": key})
    
    async def extend_key(self, key: str, days: int) -> Tuple[bool, Any]:
        return await self._request("POST", "/admin/extend", {"key": key, "days": days})
    
    async def delete_key(self, key: str) -> Tuple[bool, Any]:
        return await self._request("POST", "/admin/delete", {"key": key})
    
    async def search(self, query: str) -> Tuple[bool, Any]:
        return await self._request("GET", "/admin/search", params={"q": query})
    
    async def get_stats(self) -> Tuple[bool, Any]:
        return await self._request("GET", "/admin/stats")
    
    async def get_logs(self, limit: int = 50) -> Tuple[bool, Any]:
        return await self._request("GET", "/admin/logs", params={"limit": limit})


api = LicenseAPI()
router = Router()


# ==================== КЛАВИАТУРЫ ====================

def get_main_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="🔑 Генерация ключей", callback_data="generate")],
        [InlineKeyboardButton(text="📋 Список ключей", callback_data="list")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
        [
            InlineKeyboardButton(text="🚫 Блокировать", callback_data="block"),
            InlineKeyboardButton(text="✅ Разблокировать", callback_data="unblock")
        ],
        [
            InlineKeyboardButton(text="🔄 Сброс HWID", callback_data="reset_hwid"),
            InlineKeyboardButton(text="⏰ Продлить", callback_data="extend")
        ],
        [
            InlineKeyboardButton(text="🔍 Поиск", callback_data="search"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data="delete")
        ],
        [InlineKeyboardButton(text="📝 Логи", callback_data="logs")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_generate_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for key, info in LICENSE_TYPES.items():
        text = f"{info['emoji']} {info['name']} ({info['price']})"
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"gen_{key}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
    ])


def get_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])


def get_list_filter_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📋 Все", callback_data="list_all"),
            InlineKeyboardButton(text="✅ Активные", callback_data="list_active")
        ],
        [
            InlineKeyboardButton(text="⏳ Ожидают", callback_data="list_pending"),
            InlineKeyboardButton(text="🚫 Blocked", callback_data="list_blocked")
        ],
        [
            InlineKeyboardButton(text="⌛ Истёкшие", callback_data="list_expired")
        ],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
    ])


# ==================== ДЕКОРАТОРЫ ====================

def admin_only(func):
    @wraps(func)
    async def wrapper(update, *args, **kwargs):
        user_id = update.from_user.id if hasattr(update, 'from_user') else update.message.from_user.id
        if user_id != Config.ADMIN_USER_ID:
            if hasattr(update, 'answer'):
                await update.answer("❌ Нет доступа", show_alert=True)
            else:
                await update.reply("❌ Нет доступа")
            return
        return await func(update, *args, **kwargs)
    return wrapper


# ==================== КОМАНДЫ ====================

@router.message(Command("start"))
@admin_only
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🔐 *Админ-панель лицензий v2.0*\n\n"
        f"📡 Сервер: `{Config.SERVER_URL}`\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )


@router.message(Command("help"))
@admin_only
async def cmd_help(message: Message):
    await message.answer(
        "📚 *Справка*\n\n"
        "*Команды:*\n"
        "/start - Главное меню\n"
        "/stats - Статистика\n"
        "/help - Справка\n\n"
        "*Типы лицензий:*\n"
        "🕐 1 Day - $2\n"
        "📅 3 Days - $5\n"
        "📆 Weekly - $8\n"
        "🗓 Monthly - $20\n"
        "📊 Yearly - $150\n"
        "♾ Lifetime - $250",
        parse_mode=ParseMode.MARKDOWN
    )


# ==================== CALLBACKS ====================

@router.callback_query(F.data == "back")
@admin_only
async def cb_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "🔐 *Админ-панель лицензий v2.0*\n\nВыберите действие:",
        reply_markup=get_main_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()


@router.callback_query(F.data == "cancel")
@admin_only
async def cb_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "❌ Действие отменено\n\n🔐 *Админ-панель*",
        reply_markup=get_main_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()


# ==================== ГЕНЕРАЦИЯ ====================

@router.callback_query(F.data == "generate")
@admin_only
async def cb_generate(callback: CallbackQuery):
    await callback.message.edit_text(
        "🔑 *Генерация ключа*\n\nВыберите тип:",
        reply_markup=get_generate_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()


@router.callback_query(F.data.startswith("gen_"))
@admin_only
async def cb_gen_key(callback: CallbackQuery):
    license_type = callback.data.replace("gen_", "")
    
    await callback.message.edit_text("⏳ Генерация...", parse_mode=ParseMode.MARKDOWN)
    
    success, result = await api.generate_key(license_type)
    
    if success:
        key = result["keys"][0]
        info = LICENSE_TYPES.get(license_type, {})
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Ещё один", callback_data=callback.data)],
            [InlineKeyboardButton(text="🔑 Другой тип", callback_data="generate")],
            [InlineKeyboardButton(text="◀️ Меню", callback_data="back")]
        ])
        
        await callback.message.edit_text(
            f"✅ *Ключ создан!*\n\n"
            f"{info.get('emoji', '🔑')} Тип: *{info.get('name', license_type)}*\n\n"
            f"🔑 `{key}`\n\n"
            f"_Нажмите чтобы скопировать_",
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await callback.message.edit_text(f"❌ Ошибка: {result}", reply_markup=get_back_keyboard())
    
    await callback.answer()


# ==================== СПИСОК ====================

@router.callback_query(F.data == "list")
@admin_only
async def cb_list(callback: CallbackQuery):
    await callback.message.edit_text(
        "📋 *Список ключей*\n\nВыберите фильтр:",
        reply_markup=get_list_filter_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()


@router.callback_query(F.data.startswith("list_"))
@admin_only
async def cb_list_filtered(callback: CallbackQuery):
    filter_type = callback.data.replace("list_", "")
    status = None if filter_type == "all" else filter_type
    
    await callback.message.edit_text("⏳ Загрузка...", parse_mode=ParseMode.MARKDOWN)
    
    success, result = await api.list_keys(limit=15, status=status)
    
    if not success:
        await callback.message.edit_text(f"❌ Ошибка: {result}", reply_markup=get_back_keyboard())
        await callback.answer()
        return
    
    licenses = result.get("licenses", [])
    
    if not licenses:
        await callback.message.edit_text(
            "📋 *Нет ключей*",
            reply_markup=get_list_filter_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        await callback.answer()
        return
    
    status_emoji = {"active": "✅", "blocked": "🚫", "expired": "⌛", "pending": "⏳"}
    text = f"📋 *Ключи ({filter_type}):*\n\n"
    
    for lic in licenses[:15]:
        emoji = status_emoji.get(lic.get("status", ""), "❓")
        text += f"{emoji} `{lic['key'][:20]}...`\n"
        text += f"    {lic['type']}"
        if lic.get('expires_at'):
            text += f" | до {lic['expires_at'][:10]}"
        text += "\n\n"
    
    text += f"_Показано {len(licenses[:15])} из {result.get('count', 0)}_"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_list_filter_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()


# ==================== СТАТИСТИКА ====================

@router.callback_query(F.data == "stats")
@admin_only
async def cb_stats(callback: CallbackQuery):
    success, result = await api.get_stats()
    
    if success:
        text = (
            "📊 *Статистика*\n\n"
            f"📝 Всего: `{result.get('total', 0)}`\n"
            f"✅ Активных: `{result.get('activated', 0)}`\n"
            f"⏳ Ожидают: `{result.get('pending', 0)}`\n"
            f"🚫 Заблокировано: `{result.get('blocked', 0)}`\n"
            f"⌛ Истекло: `{result.get('expired', 0)}`\n\n"
            f"📈 *Активаций:*\n"
            f"• За 24ч: `{result.get('activations_24h', 0)}`\n"
            f"• За 7 дней: `{result.get('activations_7d', 0)}`\n\n"
            f"📦 *По типам:*\n"
        )
        for t, count in result.get('by_type', {}).items():
            info = LICENSE_TYPES.get(t, {})
            text += f"• {info.get('emoji', '🔑')} {t}: `{count}`\n"
    else:
        text = f"❌ Ошибка: {result}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="stats")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    await callback.answer()


# ==================== БЛОКИРОВКА ====================

@router.callback_query(F.data == "block")
@admin_only
async def cb_block(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_key_to_block)
    await callback.message.edit_text(
        "🚫 *Блокировка ключа*\n\nОтправьте ключ для блокировки:",
        reply_markup=get_cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()


@router.message(AdminStates.waiting_for_key_to_block)
@admin_only
async def process_block_key(message: Message, state: FSMContext):
    key = message.text.strip()
    success, result = await api.block_key(key)
    
    if success:
        await message.answer(f"✅ Ключ `{key[:20]}...` заблокирован", parse_mode=ParseMode.MARKDOWN)
    else:
        await message.answer(f"❌ Ошибка: {result.get('error', result)}")
    
    await state.clear()
    await message.answer("🔐 *Меню*", reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)


# ==================== РАЗБЛОКИРОВКА ====================

@router.callback_query(F.data == "unblock")
@admin_only
async def cb_unblock(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_key_to_unblock)
    await callback.message.edit_text(
        "✅ *Разблокировка ключа*\n\nОтправьте ключ:",
        reply_markup=get_cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()


@router.message(AdminStates.waiting_for_key_to_unblock)
@admin_only
async def process_unblock_key(message: Message, state: FSMContext):
    key = message.text.strip()
    success, result = await api.unblock_key(key)
    
    if success:
        await message.answer(f"✅ Ключ `{key[:20]}...` разблокирован", parse_mode=ParseMode.MARKDOWN)
    else:
        await message.answer(f"❌ Ошибка: {result.get('error', result)}")
    
    await state.clear()
    await message.answer("🔐 *Меню*", reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)


# ==================== СБРОС HWID ====================

@router.callback_query(F.data == "reset_hwid")
@admin_only
async def cb_reset_hwid(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_key_to_reset)
    await callback.message.edit_text(
        "🔄 *Сброс HWID*\n\nОтправьте ключ для сброса привязки:",
        reply_markup=get_cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()


@router.message(AdminStates.waiting_for_key_to_reset)
@admin_only
async def process_reset_hwid(message: Message, state: FSMContext):
    key = message.text.strip()
    success, result = await api.reset_hwid(key)
    
    if success:
        await message.answer(f"✅ HWID для `{key[:20]}...` сброшен", parse_mode=ParseMode.MARKDOWN)
    else:
        await message.answer(f"❌ Ошибка: {result.get('error', result)}")
    
    await state.clear()
    await message.answer("🔐 *Меню*", reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)


# ==================== ПРОДЛЕНИЕ ====================

@router.callback_query(F.data == "extend")
@admin_only
async def cb_extend(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_key_to_extend)
    await callback.message.edit_text(
        "⏰ *Продление лицензии*\n\nОтправьте ключ для продления:",
        reply_markup=get_cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()


@router.message(AdminStates.waiting_for_key_to_extend)
@admin_only
async def process_extend_key(message: Message, state: FSMContext):
    key = message.text.strip()
    await state.update_data(extend_key=key)
    await state.set_state(AdminStates.waiting_for_extend_days)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="7 дней", callback_data="extend_7"),
            InlineKeyboardButton(text="30 дней", callback_data="extend_30")
        ],
        [
            InlineKeyboardButton(text="90 дней", callback_data="extend_90"),
            InlineKeyboardButton(text="365 дней", callback_data="extend_365")
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])
    
    await message.answer(
        f"⏰ Продление `{key[:20]}...`\n\nВыберите срок или отправьте число дней:",
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN
    )


@router.callback_query(F.data.startswith("extend_"), AdminStates.waiting_for_extend_days)
@admin_only
async def process_extend_days_button(callback: CallbackQuery, state: FSMContext):
    days = int(callback.data.replace("extend_", ""))
    data = await state.get_data()
    key = data.get("extend_key")
    
    success, result = await api.extend_key(key, days)
    
    if success:
        await callback.message.edit_text(
            f"✅ Ключ продлён на {days} дней\n\nНовая дата: `{result.get('new_expiry', '')[:10]}`",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await callback.message.edit_text(f"❌ Ошибка: {result.get('error', result)}")
    
    await state.clear()
    await callback.message.answer("🔐 *Меню*", reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)
    await callback.answer()


@router.message(AdminStates.waiting_for_extend_days)
@admin_only
async def process_extend_days_text(message: Message, state: FSMContext):
    try:
        days = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите число дней")
        return
    
    data = await state.get_data()
    key = data.get("extend_key")
    
    success, result = await api.extend_key(key, days)
    
    if success:
        await message.answer(
            f"✅ Ключ продлён на {days} дней\n\nНовая дата: `{result.get('new_expiry', '')[:10]}`",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await message.answer(f"❌ Ошибка: {result.get('error', result)}")
    
    await state.clear()
    await message.answer("🔐 *Меню*", reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)


# ==================== УДАЛЕНИЕ ====================

@router.callback_query(F.data == "delete")
@admin_only
async def cb_delete(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_key_to_delete)
    await callback.message.edit_text(
        "🗑 *Удаление ключа*\n\n⚠️ Это действие необратимо!\n\nОтправьте ключ для удаления:",
        reply_markup=get_cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()


@router.message(AdminStates.waiting_for_key_to_delete)
@admin_only
async def process_delete_key(message: Message, state: FSMContext):
    key = message.text.strip()
    success, result = await api.delete_key(key)
    
    if success:
        await message.answer(f"✅ Ключ `{key[:20]}...` удалён", parse_mode=ParseMode.MARKDOWN)
    else:
        await message.answer(f"❌ Ошибка: {result.get('error', result)}")
    
    await state.clear()
    await message.answer("🔐 *Меню*", reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)


# ==================== ПОИСК ====================

@router.callback_query(F.data == "search")
@admin_only
async def cb_search(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_search_query)
    await callback.message.edit_text(
        "🔍 *Поиск*\n\nВведите часть ключа или HWID (мин. 3 символа):",
        reply_markup=get_cancel_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()


@router.message(AdminStates.waiting_for_search_query)
@admin_only
async def process_search(message: Message, state: FSMContext):
    query = message.text.strip()
    
    if len(query) < 3:
        await message.answer("❌ Минимум 3 символа")
        return
    
    success, result = await api.search(query)
    
    if success:
        results = result.get("results", [])
        if not results:
            await message.answer("🔍 Ничего не найдено")
        else:
            text = f"🔍 *Найдено {len(results)}:*\n\n"
            for r in results[:10]:
                status = "🚫" if r['blocked'] else ("✅" if r['activated'] else "⏳")
                text += f"{status} `{r['key'][:25]}...`\n"
                text += f"    {r['type']}\n\n"
            await message.answer(text, parse_mode=ParseMode.MARKDOWN)
    else:
        await message.answer(f"❌ Ошибка: {result.get('error', result)}")
    
    await state.clear()
    await message.answer("🔐 *Меню*", reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)


# ==================== ЛОГИ ====================

@router.callback_query(F.data == "logs")
@admin_only
async def cb_logs(callback: CallbackQuery):
    success, result = await api.get_logs(30)
    
    if success:
        logs = result.get("logs", [])
        if not logs:
            text = "📝 Нет логов"
        else:
            text = "📝 *Последние события:*\n\n"
            for log in logs[:15]:
                action = log['action']
                emoji = {"ACTIVATION_SUCCESS": "✅", "KEY_BLOCKED": "🚫", "KEYS_GENERATED": "🔑"}.get(action, "📌")
                text += f"{emoji} `{log['timestamp'][11:19]}` {action}\n"
    else:
        text = f"❌ Ошибка: {result}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="logs")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    await callback.answer()


# ==================== ЗАПУСК ====================

async def main():
    if not Config.validate():
        sys.exit(1)
    
    logger.info("🤖 Запуск бота v2.0...")
    
    bot = Bot(token=Config.TELEGRAM_BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp.include_router(router)
    
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("✅ Бот запущен!")
        await dp.start_polling(bot)
    finally:
        await api.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
