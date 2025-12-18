"""
Запуск license_server.py и telegram_admin_bot.py
Версия 2.0 - с мониторингом и автоперезапуском
"""
import subprocess
import sys
import time
import os
import signal
import threading
from datetime import datetime

# ==================== КОНФИГУРАЦИЯ ====================

SERVER_FILE = 'license_server.py'
BOT_FILE = 'telegram_admin_bot.py'
HEALTH_CHECK_INTERVAL = 60  # секунд
AUTO_RESTART = True
MAX_RESTARTS = 5
RESTART_DELAY = 5

# ==================== ЦВЕТА ДЛЯ КОНСОЛИ ====================

class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    PURPLE = '\033[95m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def log(message: str, color: str = Colors.RESET):
    """Логирование с временем и цветом"""
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"{Colors.CYAN}[{timestamp}]{Colors.RESET} {color}{message}{Colors.RESET}")

def log_error(message: str):
    log(f"❌ {message}", Colors.RED)

def log_success(message: str):
    log(f"✅ {message}", Colors.GREEN)

def log_warning(message: str):
    log(f"⚠️ {message}", Colors.YELLOW)

def log_info(message: str):
    log(f"ℹ️ {message}", Colors.BLUE)

# ==================== ПРОВЕРКИ ====================

def check_environment():
    """Проверка переменных окружения"""
    required = {
        'TELEGRAM_BOT_TOKEN': 'Токен бота от @BotFather',
        'ADMIN_USER_ID': 'Твой Telegram ID',
        'ADMIN_PASSWORD': 'Пароль для API'
    }
    
    missing = []
    for var, description in required.items():
        if not os.getenv(var):
            missing.append(f"  • {var} - {description}")
    
    if missing:
        log_warning("Не установлены переменные окружения:")
        for m in missing:
            print(f"{Colors.YELLOW}{m}{Colors.RESET}")
        print()
        return False
    return True

def check_files():
    """Проверка наличия файлов"""
    files = [SERVER_FILE, BOT_FILE]
    missing = [f for f in files if not os.path.exists(f)]
    
    if missing:
        log_error(f"Файлы не найдены: {', '.join(missing)}")
        return False
    return True

# ==================== УПРАВЛЕНИЕ ПРОЦЕССАМИ ====================

class ProcessManager:
    def __init__(self):
        self.server_process = None
        self.bot_process = None
        self.server_restarts = 0
        self.bot_restarts = 0
        self.running = True
    
    def start_server(self):
        """Запуск сервера лицензий"""
        log_info("Запуск License Server...")
        self.server_process = subprocess.Popen(
            [sys.executable, SERVER_FILE],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        time.sleep(2)
        
        if self.server_process.poll() is None:
            log_success(f"License Server запущен (PID: {self.server_process.pid})")
            return True
        else:
            log_error("License Server не запустился!")
            return False
    
    def start_bot(self):
        """Запуск Telegram бота"""
        log_info("Запуск Telegram Bot...")
        self.bot_process = subprocess.Popen(
            [sys.executable, BOT_FILE],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        time.sleep(2)
        
        if self.bot_process.poll() is None:
            log_success(f"Telegram Bot запущен (PID: {self.bot_process.pid})")
            return True
        else:
            log_error("Telegram Bot не запустился!")
            return False
    
    def check_and_restart(self):
        """Проверка и перезапуск упавших процессов"""
        # Проверяем сервер
        if self.server_process and self.server_process.poll() is not None:
            self.server_restarts += 1
            if self.server_restarts <= MAX_RESTARTS:
                log_warning(f"Server упал! Перезапуск ({self.server_restarts}/{MAX_RESTARTS})...")
                time.sleep(RESTART_DELAY)
                self.start_server()
            else:
                log_error("Server: превышен лимит перезапусков!")
        
        # Проверяем бота
        if self.bot_process and self.bot_process.poll() is not None:
            self.bot_restarts += 1
            if self.bot_restarts <= MAX_RESTARTS:
                log_warning(f"Bot упал! Перезапуск ({self.bot_restarts}/{MAX_RESTARTS})...")
                time.sleep(RESTART_DELAY)
                self.start_bot()
            else:
                log_error("Bot: превышен лимит перезапусков!")
    
    def monitor(self):
        """Мониторинг процессов"""
        while self.running:
            time.sleep(HEALTH_CHECK_INTERVAL)
            if AUTO_RESTART:
                self.check_and_restart()
    
    def stop_all(self):
        """Остановка всех процессов"""
        self.running = False
        
        log_info("Остановка процессов...")
        
        if self.server_process and self.server_process.poll() is None:
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=5)
                log_success("Server остановлен")
            except subprocess.TimeoutExpired:
                self.server_process.kill()
                log_warning("Server принудительно остановлен")
        
        if self.bot_process and self.bot_process.poll() is None:
            self.bot_process.terminate()
            try:
                self.bot_process.wait(timeout=5)
                log_success("Bot остановлен")
            except subprocess.TimeoutExpired:
                self.bot_process.kill()
                log_warning("Bot принудительно остановлен")
    
    def status(self):
        """Статус процессов"""
        server_status = "🟢 Running" if self.server_process and self.server_process.poll() is None else "🔴 Stopped"
        bot_status = "🟢 Running" if self.bot_process and self.bot_process.poll() is None else "🔴 Stopped"
        
        return f"Server: {server_status} | Bot: {bot_status}"

# ==================== ГЛАВНАЯ ФУНКЦИЯ ====================

def main():
    print(f"""
{Colors.PURPLE}╔══════════════════════════════════════════════════╗
║       🔐 License System Launcher v2.0             ║
╚══════════════════════════════════════════════════╝{Colors.RESET}
""")
    
    # Проверки
    if not check_files():
        sys.exit(1)
    
    env_ok = check_environment()
    if not env_ok:
        log_warning("Продолжаем без некоторых переменных...\n")
        time.sleep(2)
    
    # Создаём менеджер процессов
    manager = ProcessManager()
    
    # Обработка Ctrl+C
    def signal_handler(sig, frame):
        print()
        log_info("Получен сигнал остановки...")
        manager.stop_all()
        log_success("Всё остановлено. До свидания! 👋")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Запуск
    print(f"{Colors.BOLD}{'='*50}{Colors.RESET}\n")
    
    if not manager.start_server():
        log_error("Не удалось запустить сервер!")
        sys.exit(1)
    
    if not manager.start_bot():
        log_warning("Бот не запустился, но сервер работает")
    
    print(f"\n{Colors.BOLD}{'='*50}{Colors.RESET}")
    log_success("Система запущена!")
    print(f"""
{Colors.GREEN}📡 License Server:{Colors.RESET} http://localhost:5000
{Colors.GREEN}🤖 Telegram Bot:{Colors.RESET} Активен

{Colors.YELLOW}Нажмите Ctrl+C для остановки{Colors.RESET}
""")
    
    # Запуск мониторинга в отдельном потоке
    if AUTO_RESTART:
        monitor_thread = threading.Thread(target=manager.monitor, daemon=True)
        monitor_thread.start()
        log_info(f"Мониторинг активен (интервал: {HEALTH_CHECK_INTERVAL}с)")
    
    # Основной цикл
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()
