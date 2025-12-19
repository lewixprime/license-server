"""
Telegram Admin Bot для управления лицензиями
"""
import os
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Конфигурация
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
ADMIN_CHAT_ID = os.getenv('TELEGRAM_ADMIN_CHAT_ID', '')
SERVER_URL = os.getenv('SERVER_URL', 'http://localhost:5000')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '')

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class TelegramAdminBot:
    """Telegram бот для администрирования лицензий"""
    
    def __init__(self):
        self.app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        self.headers = {"Authorization": f"Bearer {ADMIN_PASSWORD}"}
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Настройка обработчиков команд"""
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("stats", self.cmd_stats))
        self.app.add_handler(CommandHandler("logs", self.cmd_logs))
        self.app.add_handler(CommandHandler("generate", self.cmd_generate))
        self.app.add_handler(CommandHandler("search", self.cmd_search))
        self.app.add_handler(CallbackQueryHandler(self.button_callback))
    
    def _check_admin(self, update: Update) -> bool:
        """Проверка что пользователь - админ"""
        user_id = str(update.effective_user.id)
        if user_id != ADMIN_CHAT_ID:
            return False
        return True
    
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /start"""
        if not self._check_admin(update):
            await update.message.reply_text("❌ У вас нет доступа к этому боту")
            return
        
        keyboard = [
            [InlineKeyboardButton("📊 Статистика", callback_data='stats')],
            [InlineKeyboardButton("🔑 Создать ключ", callback_data='generate')],
            [InlineKeyboardButton("📋 Логи", callback_data='logs')],
            [InlineKeyboardButton("🔍 Поиск", callback_data='search')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            '🤖 <b>RBXMT License Admin Bot</b>\n\n'
            'Выберите действие:',
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    
    async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Статистика лицензий"""
        if not self._check_admin(update):
            return
        
        try:
            response = requests.get(
                f'{SERVER_URL}/admin/stats',
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                stats = response.json()
                
                message = f"""
📊 <b>Статистика лицензий</b>

📈 Всего: {stats['total']}
✅ Активных: {stats['activated']}
⏳ Ожидают: {stats['pending']}
🚫 Заблокировано: {stats['blocked']}
⏰ Истекло: {stats.get('expired', 0)}

📅 Активаций за 24ч: {stats.get('activations_24h', 0)}
📅 Активаций за 7д: {stats.get('activations_7d', 0)}

<b>По типам:</b>
"""
                for license_type, count in stats.get('by_type', {}).items():
                    message += f"• {license_type}: {count}\n"
                
                await update.message.reply_text(message, parse_mode='HTML')
            else:
                await update.message.reply_text(f"❌ Ошибка: {response.status_code}")
        
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")
    
    async def cmd_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Последние логи"""
        if not self._check_admin(update):
            return
        
        try:
            response = requests.get(
                f'{SERVER_URL}/admin/logs?limit=10',
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                logs = data.get('logs', [])
                
                if not logs:
                    await update.message.reply_text("📋 Логи пусты")
                    return
                
                message = "📋 <b>Последние события:</b>\n\n"
                for log in logs:
                    timestamp = log['timestamp'].split('T')[1][:8]  # Только время
                    action = log['action']
                    key = log.get('license_key', 'N/A')
                    message += f"• <code>{timestamp}</code> - {action}\n"
                    if key != 'N/A':
                        message += f"  Key: <code>{key}</code>\n"
                
                await update.message.reply_text(message, parse_mode='HTML')
            else:
                await update.message.reply_text(f"❌ Ошибка: {response.status_code}")
        
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")
    
    async def cmd_generate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Генерация ключа"""
        if not self._check_admin(update):
            return
        
        keyboard = [
            [InlineKeyboardButton("1 Day ($2)", callback_data='gen_trial_1day')],
            [InlineKeyboardButton("3 Days ($5)", callback_data='gen_trial_3days')],
            [InlineKeyboardButton("Weekly ($10)", callback_data='gen_weekly')],
            [InlineKeyboardButton("Monthly ($25)", callback_data='gen_monthly')],
            [InlineKeyboardButton("Yearly ($200)", callback_data='gen_yearly')],
            [InlineKeyboardButton("Lifetime ($500)", callback_data='gen_lifetime')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            '🔑 Выберите тип лицензии:',
            reply_markup=reply_markup
        )
    
    async def cmd_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Поиск ключа"""
        if not self._check_admin(update):
            return
        
        if not context.args:
            await update.message.reply_text(
                "🔍 Использование: /search <ключ или HWID>\n"
                "Пример: /search RBXMT-1234"
            )
            return
        
        query = ' '.join(context.args)
        
        try:
            response = requests.get(
                f'{SERVER_URL}/admin/search',
                params={'q': query},
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                results = data.get('results', [])
                
                if not results:
                    await update.message.reply_text(f"🔍 Ничего не найдено по запросу: {query}")
                    return
                
                message = f"🔍 <b>Найдено: {len(results)}</b>\n\n"
                for result in results[:5]:  # Показываем первые 5
                    status = "🚫" if result['blocked'] else ("✅" if result['activated'] else "⏳")
                    message += f"{status} <code>{result['key']}</code>\n"
                    message += f"   Type: {result['type']}\n"
                    if result.get('hwid'):
                        message += f"   HWID: <code>{result['hwid'][:16]}...</code>\n"
                    message += "\n"
                
                await update.message.reply_text(message, parse_mode='HTML')
            else:
                await update.message.reply_text(f"❌ Ошибка: {response.status_code}")
        
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка нажатий кнопок"""
        query = update.callback_query
        await query.answer()
        
        if not self._check_admin(update):
            return
        
        data = query.data
        
        # Статистика
        if data == 'stats':
            await self.cmd_stats(update, context)
        
        # Логи
        elif data == 'logs':
            await self.cmd_logs(update, context)
        
        # Генерация
        elif data == 'generate':
            await self.cmd_generate(update, context)
        
        # Поиск
        elif data == 'search':
            await query.edit_message_text(
                "🔍 Используйте команду: /search <запрос>"
            )
        
        # Генерация конкретного типа
        elif data.startswith('gen_'):
            license_type = data.replace('gen_', '')
            
            try:
                response = requests.post(
                    f'{SERVER_URL}/admin/generate',
                    json={'type': license_type, 'count': 1},
                    headers=self.headers,
                    timeout=10
                )
                
                if response.status_code == 200:
                    result = response.json()
                    key = result['keys'][0]
                    
                    await query.edit_message_text(
                        f'✅ <b>Ключ создан!</b>\n\n'
                        f'Тип: <code>{license_type}</code>\n'
                        f'Ключ: <code>{key}</code>\n\n'
                        f'Скопируйте ключ и отправьте клиенту.',
                        parse_mode='HTML'
                    )
                    
                    logger.info(f"Создан ключ {license_type}: {key[:16]}...")
                else:
                    await query.edit_message_text(f'❌ Ошибка создания ключа: {response.status_code}')
            
            except Exception as e:
                await query.edit_message_text(f'❌ Ошибка: {str(e)}')
    
    def run(self):
        """Запуск бота"""
        logger.info("🤖 Telegram Admin Bot запущен")
        self.app.run_polling()


# Функция для отправки уведомлений (вызывается из license_server.py)
def send_notification(message: str):
    """Отправка уведомления админу"""
    try:
        url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
        data = {
            'chat_id': ADMIN_CHAT_ID,
            'text': message,
            'parse_mode': 'HTML'
        }
        requests.post(url, json=data, timeout=5)
    except:
        pass


if __name__ == '__main__':
    if not TELEGRAM_BOT_TOKEN or not ADMIN_CHAT_ID:
        print("❌ Установите TELEGRAM_BOT_TOKEN и TELEGRAM_ADMIN_CHAT_ID в переменных окружения")
        exit(1)
    
    bot = TelegramAdminBot()
    bot.run()
