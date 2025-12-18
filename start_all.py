"""
Запуск license_server.py и telegram_admin_bot.py одновременно
"""
import subprocess
import sys
import time
import os

def start_server():
    """Запуск Flask сервера"""
    print("🚀 Запуск license сервера...")
    return subprocess.Popen([sys.executable, 'license_server.py'])

def start_bot():
    """Запуск Telegram бота"""
    print("🤖 Запуск Telegram бота...")
    return subprocess.Popen([sys.executable, 'telegram_admin_bot.py'])

if __name__ == '__main__':
    # Проверка переменных окружения
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    admin_id = os.getenv('ADMIN_USER_ID')
    
    if not bot_token or not admin_id:
        print("⚠️ ВНИМАНИЕ: Не установлены переменные окружения!")
        print("Установи в Render.com:")
        print("  TELEGRAM_BOT_TOKEN - токен бота")
        print("  ADMIN_USER_ID - твой Telegram ID")
        print("  ADMIN_PASSWORD - пароль админки")
        print("\nСервер запустится, но бот может не работать.")
        time.sleep(3)
    
    # Запуск обоих процессов
    server_process = start_server()
    time.sleep(2)  # Даём серверу время запуститься
    bot_process = start_bot()
    
    print("\n✅ Всё запущено!")
    print("📡 License сервер работает на порту 5000")
    print("🤖 Telegram бот подключен")
    
    try:
        # Ждём завершения (никогда не завершится в нормальном режиме)
        server_process.wait()
        bot_process.wait()
    except KeyboardInterrupt:
        print("\n🛑 Остановка...")
        server_process.terminate()
        bot_process.terminate()
