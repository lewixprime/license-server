"""
Telegram бот для управления лицензиями
Запусти: python telegram_admin_bot.py
"""
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# НАСТРОЙКИ (можно задать через переменные окружения или здесь)
import os

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', "8382494933:AAGRNCxPykBp26Ujm1nAxDdK-0_0fmQrOAw")  # Получи у @BotFather
ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID', '547899784'))  # Твой Telegram ID (узнай у @userinfobot)
SERVER_URL = os.getenv('SERVER_URL', "https://license-server-qjmh.onrender.com")
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', "9724776_rD")  # Тот же что в license_server.py

# Проверка админа
def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_USER_ID

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ У вас нет доступа к этому боту")
        return
    
    keyboard = [
        [InlineKeyboardButton("🔑 Генерация ключей", callback_data="generate")],
        [InlineKeyboardButton("📋 Список ключей", callback_data="list")],
        [InlineKeyboardButton("🚫 Заблокировать ключ", callback_data="block")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🔐 *Админ-панель лицензий*\n\n"
        "Выберите действие:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# Обработка кнопок
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not is_admin(query.from_user.id):
        await query.edit_message_text("❌ У вас нет доступа")
        return
    
    if query.data == "generate":
        keyboard = [
            [InlineKeyboardButton("1 Day ($2)", callback_data="gen_trial_1day")],
            [InlineKeyboardButton("3 Days ($5)", callback_data="gen_trial_3days")],
            [InlineKeyboardButton("Weekly ($8)", callback_data="gen_weekly")],
            [InlineKeyboardButton("Monthly ($20)", callback_data="gen_monthly")],
            [InlineKeyboardButton("Yearly ($150)", callback_data="gen_yearly")],
            [InlineKeyboardButton("Lifetime ($250)", callback_data="gen_lifetime")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🔑 *Генерация ключа*\n\n"
            "Выберите тип лицензии:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    
    elif query.data.startswith("gen_"):
        license_type = query.data.replace("gen_", "")
        await generate_key(query, license_type)
    
    elif query.data == "list":
        await list_keys(query)
    
    elif query.data == "block":
        await query.edit_message_text(
            "🚫 *Блокировка ключа*\n\n"
            "Отправьте ключ который нужно заблокировать:\n"
            "Используйте команду: `/block КЛЮЧ`",
            parse_mode="Markdown"
        )
    
    elif query.data == "back":
        keyboard = [
            [InlineKeyboardButton("🔑 Генерация ключей", callback_data="generate")],
            [InlineKeyboardButton("📋 Список ключей", callback_data="list")],
            [InlineKeyboardButton("🚫 Заблокировать ключ", callback_data="block")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🔐 *Админ-панель лицензий*\n\n"
            "Выберите действие:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

# Генерация ключа
async def generate_key(query, license_type: str):
    try:
        headers = {"Authorization": f"Bearer {ADMIN_PASSWORD}"}
        response = requests.post(
            f"{SERVER_URL}/admin/generate",
            json={"type": license_type, "count": 1},
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            key = data["keys"][0]
            
            type_names = {
                "trial_1day": "1 Day ($2)",
                "trial_3days": "3 Days ($5)",
                "weekly": "Weekly ($8)",
                "monthly": "Monthly ($20)",
                "yearly": "Yearly ($150)",
                "lifetime": "Lifetime ($250)"
            }
            
            await query.edit_message_text(
                f"✅ *Ключ сгенерирован!*\n\n"
                f"Тип: `{type_names.get(license_type, license_type)}`\n"
                f"Ключ: `{key}`\n\n"
                f"_Нажмите на ключ чтобы скопировать_",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text(
                f"❌ Ошибка: {response.text}"
            )
    except Exception as e:
        await query.edit_message_text(
            f"❌ Ошибка: {str(e)}"
        )

# Список ключей
async def list_keys(query):
    try:
        headers = {"Authorization": f"Bearer {ADMIN_PASSWORD}"}
        response = requests.get(
            f"{SERVER_URL}/admin/list",
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            licenses = data.get("licenses", [])
            
            if not licenses:
                await query.edit_message_text("📋 Нет лицензий")
                return
            
            # Показываем последние 10
            text = "📋 *Последние 10 лицензий:*\n\n"
            for lic in licenses[:10]:
                status = "🚫" if lic["blocked"] else "✅"
                activated = "✓" if lic["activated"] else "✗"
                text += f"{status} `{lic['key'][:16]}...`\n"
                text += f"   Тип: {lic['type']} | Активирован: {activated}\n\n"
            
            text += f"_Всего лицензий: {len(licenses)}_"
            
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text(
                f"❌ Ошибка: {response.text}"
            )
    except Exception as e:
        await query.edit_message_text(
            f"❌ Ошибка: {str(e)}"
        )

# Команда блокировки
async def block_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ У вас нет доступа")
        return
    
    if len(context.args) != 1:
        await update.message.reply_text(
            "❌ Использование: `/block КЛЮЧ`",
            parse_mode="Markdown"
        )
        return
    
    key = context.args[0]
    
    try:
        headers = {"Authorization": f"Bearer {ADMIN_PASSWORD}"}
        response = requests.post(
            f"{SERVER_URL}/admin/block",
            json={"key": key},
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            await update.message.reply_text(
                f"✅ Ключ `{key[:16]}...` заблокирован",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"❌ Ошибка: {response.text}"
            )
    except Exception as e:
        await update.message.reply_text(
            f"❌ Ошибка: {str(e)}"
        )

# Главная функция
def main():
    print("🤖 Запуск Telegram бота...")
    print(f"📡 Сервер: {SERVER_URL}")
    print(f"👤 Админ ID: {ADMIN_USER_ID}")
    
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("block", block_key))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("✅ Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
