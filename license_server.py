"""
License Server v2.0 - Расширенная версия
"""
from flask import Flask, request, jsonify
from datetime import datetime, timedelta
from functools import wraps
import sqlite3
import secrets
import os
import hashlib
import logging
from collections import defaultdict
import time

app = Flask(__name__)

# ==================== КОНФИГУРАЦИЯ ====================

ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '9724776_rD')
DATABASE_PATH = os.getenv('DATABASE_PATH', 'licenses.db')
RATE_LIMIT_REQUESTS = 10  # Максимум запросов
RATE_LIMIT_WINDOW = 60    # За 60 секунд

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger('LicenseServer')

# Rate limiting storage
rate_limit_storage = defaultdict(list)


# ==================== БАЗА ДАННЫХ ====================

def get_db():
    """Получить соединение с БД"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Инициализация базы данных"""
    conn = get_db()
    c = conn.cursor()
    
    # Таблица лицензий
    c.execute('''CREATE TABLE IF NOT EXISTS licenses (
        key TEXT PRIMARY KEY,
        hwid TEXT,
        type TEXT,
        created_at TEXT,
        expires_at TEXT,
        activated INTEGER DEFAULT 0,
        blocked INTEGER DEFAULT 0,
        activation_date TEXT,
        activation_ip TEXT,
        notes TEXT
    )''')
    
    # Таблица логов
    c.execute('''CREATE TABLE IF NOT EXISTS activity_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        action TEXT,
        license_key TEXT,
        hwid TEXT,
        ip_address TEXT,
        details TEXT
    )''')
    
    conn.commit()
    conn.close()
    logger.info("База данных инициализирована")


init_db()


# ==================== УТИЛИТЫ ====================

def generate_license_key(prefix: str = "") -> str:
    """Генерация уникального ключа с префиксом RBXMT"""
    random_part = secrets.token_hex(10).upper()
    # Формат: RBXMT-XXXX-XXXX-XXXX-XXXX
    key = f"{random_part[:4]}-{random_part[4:8]}-{random_part[8:12]}-{random_part[12:16]}-{random_part[16:]}"
    if prefix:
        key = f"{prefix}-{key}"
    return key


def get_client_ip() -> str:
    """Получить IP клиента"""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr or 'unknown'


def log_activity(action: str, license_key: str = None, hwid: str = None, details: str = None):
    """Записать действие в лог"""
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO activity_logs (timestamp, action, license_key, hwid, ip_address, details)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().isoformat(),
        action,
        license_key,
        hwid,
        get_client_ip(),
        details
    ))
    conn.commit()
    conn.close()


def check_rate_limit(ip: str) -> bool:
    """Проверка rate limit"""
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW
    
    # Очистка старых записей
    rate_limit_storage[ip] = [t for t in rate_limit_storage[ip] if t > window_start]
    
    if len(rate_limit_storage[ip]) >= RATE_LIMIT_REQUESTS:
        return False
    
    rate_limit_storage[ip].append(now)
    return True


# ==================== ДЕКОРАТОРЫ ====================

def rate_limited(f):
    """Декоратор rate limiting"""
    @wraps(f)
    def decorated(*args, **kwargs):
        ip = get_client_ip()
        if not check_rate_limit(ip):
            log_activity("RATE_LIMIT_EXCEEDED", details=f"IP: {ip}")
            return jsonify({"error": "Too many requests. Try again later."}), 429
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Декоратор проверки админа"""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization')
        if not auth or auth != f"Bearer {ADMIN_PASSWORD}":
            log_activity("UNAUTHORIZED_ACCESS", details=f"IP: {get_client_ip()}")
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# ==================== API КЛИЕНТА ====================

@app.route('/api/activate', methods=['POST'])
@rate_limited
def activate_license():
    """Активация лицензии"""
    data = request.json or {}
    license_key = data.get('key', '').strip()
    hwid = data.get('hwid', '').strip()
    
    if not license_key or not hwid:
        return jsonify({"success": False, "message": "Missing key or hwid"}), 400
    
    conn = get_db()
    c = conn.cursor()
    
    c.execute("SELECT * FROM licenses WHERE key=?", (license_key,))
    row = c.fetchone()
    
    if not row:
        log_activity("ACTIVATION_FAILED", license_key, hwid, "Key not found")
        conn.close()
        return jsonify({"success": False, "message": "Invalid license key"}), 404
    
    # Проверка блокировки
    if row['blocked']:
        log_activity("ACTIVATION_BLOCKED", license_key, hwid, "Key is blocked")
        conn.close()
        return jsonify({"success": False, "message": "License is blocked"}), 403
    
    # Проверка истечения
    if row['expires_at']:
        expires = datetime.fromisoformat(row['expires_at'])
        if expires < datetime.now():
            log_activity("ACTIVATION_EXPIRED", license_key, hwid, "Key expired")
            conn.close()
            return jsonify({"success": False, "message": "License expired"}), 403
    
    # Проверка HWID
    if row['activated']:
        if row['hwid'] != hwid:
            log_activity("ACTIVATION_HWID_MISMATCH", license_key, hwid, f"Expected: {row['hwid'][:16]}")
            conn.close()
            return jsonify({"success": False, "message": "License bound to another device"}), 403
    else:
        # Первая активация
        c.execute("""
            UPDATE licenses 
            SET hwid=?, activated=1, activation_date=?, activation_ip=?
            WHERE key=?
        """, (hwid, datetime.now().isoformat(), get_client_ip(), license_key))
        conn.commit()
        log_activity("ACTIVATION_SUCCESS", license_key, hwid, f"Type: {row['type']}")
        logger.info(f"✅ Новая активация: {license_key[:16]}... | Type: {row['type']}")
    
    conn.close()
    
    return jsonify({
        "success": True,
        "message": "License activated",
        "type": row['type'],
        "expires_at": row['expires_at']
    })


@app.route('/api/verify', methods=['POST'])
@rate_limited
def verify_license():
    """Проверка валидности лицензии"""
    data = request.json or {}
    license_key = data.get('key', '').strip()
    hwid = data.get('hwid', '').strip()
    
    if not license_key or not hwid:
        return jsonify({"valid": False, "message": "Missing data"}), 400
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM licenses WHERE key=?", (license_key,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        return jsonify({"valid": False, "message": "Key not found"})
    
    if row['blocked']:
        return jsonify({"valid": False, "message": "License blocked"})
    
    if row['hwid'] != hwid:
        return jsonify({"valid": False, "message": "HWID mismatch"})
    
    if row['expires_at']:
        if datetime.fromisoformat(row['expires_at']) < datetime.now():
            return jsonify({"valid": False, "message": "License expired"})
    
    return jsonify({
        "valid": True,
        "type": row['type'],
        "expires_at": row['expires_at']
    })


@app.route('/api/info', methods=['POST'])
@rate_limited
def license_info():
    """Информация о лицензии"""
    data = request.json or {}
    license_key = data.get('key', '').strip()
    hwid = data.get('hwid', '').strip()
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM licenses WHERE key=? AND hwid=?", (license_key, hwid))
    row = c.fetchone()
    conn.close()
    
    if not row:
        return jsonify({"error": "License not found"}), 404
    
    days_left = None
    if row['expires_at']:
        delta = datetime.fromisoformat(row['expires_at']) - datetime.now()
        days_left = max(0, delta.days)
    
    return jsonify({
        "key": row['key'][:8] + "...",
        "type": row['type'],
        "created_at": row['created_at'],
        "expires_at": row['expires_at'],
        "days_left": days_left,
        "activated": bool(row['activated']),
        "blocked": bool(row['blocked'])
    })


# ==================== ADMIN API ====================

@app.route('/admin/generate', methods=['POST'])
@admin_required
def generate_license():
    """Генерация новых лицензий"""
    data = request.json or {}
    license_type = data.get('type', 'monthly')
    count = min(data.get('count', 1), 100)
    notes = data.get('notes', '')
    
    # Префиксы для типов - все начинаются с RBXMT
    prefix_map = {
        'trial_1day': 'RBXMT-T1D',
        'trial_3days': 'RBXMT-T3D',
        'weekly': 'RBXMT-WKY',
        'monthly': 'RBXMT-MTH',
        'yearly': 'RBXMT-YRL',
        'lifetime': 'RBXMT-LTM'
    }
    
    # Сроки действия
    duration_map = {
        'trial_1day': 1,
        'trial_3days': 3,
        'weekly': 7,
        'monthly': 30,
        'yearly': 365,
        'lifetime': None
    }
    
    days = duration_map.get(license_type)
    prefix = prefix_map.get(license_type, 'RBXMT')
    
    conn = get_db()
    c = conn.cursor()
    
    generated_keys = []
    for _ in range(count):
        key = generate_license_key(prefix)
        created_at = datetime.now().isoformat()
        expires_at = (datetime.now() + timedelta(days=days)).isoformat() if days else None
        
        c.execute("""
            INSERT INTO licenses (key, type, created_at, expires_at, notes)
            VALUES (?, ?, ?, ?, ?)
        """, (key, license_type, created_at, expires_at, notes))
        generated_keys.append(key)
    
    conn.commit()
    conn.close()
    
    log_activity("KEYS_GENERATED", details=f"Type: {license_type}, Count: {count}")
    logger.info(f"🔑 Сгенерировано {count} ключей типа {license_type}")
    
    return jsonify({"success": True, "keys": generated_keys})


@app.route('/admin/block', methods=['POST'])
@admin_required
def block_license():
    """Блокировка лицензии"""
    data = request.json or {}
    license_key = data.get('key', '').strip()
    
    if not license_key:
        return jsonify({"error": "Key required"}), 400
    
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE licenses SET blocked=1 WHERE key=?", (license_key,))
    affected = c.rowcount
    conn.commit()
    conn.close()
    
    if affected == 0:
        return jsonify({"error": "Key not found"}), 404
    
    log_activity("KEY_BLOCKED", license_key)
    logger.info(f"🚫 Ключ заблокирован: {license_key[:16]}...")
    
    return jsonify({"success": True, "message": "Key blocked"})


@app.route('/admin/unblock', methods=['POST'])
@admin_required
def unblock_license():
    """Разблокировка лицензии"""
    data = request.json or {}
    license_key = data.get('key', '').strip()
    
    if not license_key:
        return jsonify({"error": "Key required"}), 400
    
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE licenses SET blocked=0 WHERE key=?", (license_key,))
    affected = c.rowcount
    conn.commit()
    conn.close()
    
    if affected == 0:
        return jsonify({"error": "Key not found"}), 404
    
    log_activity("KEY_UNBLOCKED", license_key)
    logger.info(f"✅ Ключ разблокирован: {license_key[:16]}...")
    
    return jsonify({"success": True, "message": "Key unblocked"})


@app.route('/admin/reset-hwid', methods=['POST'])
@admin_required
def reset_hwid():
    """Сброс HWID (для смены устройства)"""
    data = request.json or {}
    license_key = data.get('key', '').strip()
    
    if not license_key:
        return jsonify({"error": "Key required"}), 400
    
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        UPDATE licenses 
        SET hwid=NULL, activated=0, activation_date=NULL, activation_ip=NULL 
        WHERE key=?
    """, (license_key,))
    affected = c.rowcount
    conn.commit()
    conn.close()
    
    if affected == 0:
        return jsonify({"error": "Key not found"}), 404
    
    log_activity("HWID_RESET", license_key)
    logger.info(f"🔄 HWID сброшен: {license_key[:16]}...")
    
    return jsonify({"success": True, "message": "HWID reset successful"})


@app.route('/admin/extend', methods=['POST'])
@admin_required
def extend_license():
    """Продление лицензии"""
    data = request.json or {}
    license_key = data.get('key', '').strip()
    days = data.get('days', 30)
    
    if not license_key:
        return jsonify({"error": "Key required"}), 400
    
    conn = get_db()
    c = conn.cursor()
    
    c.execute("SELECT expires_at FROM licenses WHERE key=?", (license_key,))
    row = c.fetchone()
    
    if not row:
        conn.close()
        return jsonify({"error": "Key not found"}), 404
    
    # Вычисляем новую дату
    if row['expires_at']:
        current_expiry = datetime.fromisoformat(row['expires_at'])
        # Если уже истёк, продлеваем от сегодня
        if current_expiry < datetime.now():
            current_expiry = datetime.now()
    else:
        # Lifetime лицензия - не нужно продлевать
        conn.close()
        return jsonify({"error": "Lifetime license cannot be extended"}), 400
    
    new_expiry = (current_expiry + timedelta(days=days)).isoformat()
    
    c.execute("UPDATE licenses SET expires_at=? WHERE key=?", (new_expiry, license_key))
    conn.commit()
    conn.close()
    
    log_activity("KEY_EXTENDED", license_key, details=f"Added {days} days")
    logger.info(f"⏰ Ключ продлён на {days} дней: {license_key[:16]}...")
    
    return jsonify({
        "success": True,
        "message": f"Extended by {days} days",
        "new_expiry": new_expiry
    })


@app.route('/admin/delete', methods=['POST'])
@admin_required
def delete_license():
    """Удаление лицензии"""
    data = request.json or {}
    license_key = data.get('key', '').strip()
    
    if not license_key:
        return jsonify({"error": "Key required"}), 400
    
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM licenses WHERE key=?", (license_key,))
    affected = c.rowcount
    conn.commit()
    conn.close()
    
    if affected == 0:
        return jsonify({"error": "Key not found"}), 404
    
    log_activity("KEY_DELETED", license_key)
    logger.info(f"🗑️ Ключ удалён: {license_key[:16]}...")
    
    return jsonify({"success": True, "message": "Key deleted"})


@app.route('/admin/list', methods=['GET'])
@admin_required
def list_licenses():
    """Список всех лицензий с фильтрацией"""
    filter_type = request.args.get('type')
    filter_status = request.args.get('status')  # active, blocked, expired, pending
    search = request.args.get('search', '').strip()
    limit = min(int(request.args.get('limit', 100)), 500)
    
    conn = get_db()
    c = conn.cursor()
    
    query = "SELECT * FROM licenses WHERE 1=1"
    params = []
    
    if filter_type:
        query += " AND type=?"
        params.append(filter_type)
    
    if search:
        query += " AND (key LIKE ? OR hwid LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    
    now = datetime.now()
    result = []
    
    for row in rows:
        # Определяем статус
        if row['blocked']:
            status = 'blocked'
        elif row['expires_at'] and datetime.fromisoformat(row['expires_at']) < now:
            status = 'expired'
        elif row['activated']:
            status = 'active'
        else:
            status = 'pending'
        
        # Фильтр по статусу
        if filter_status and status != filter_status:
            continue
        
        result.append({
            "key": row['key'],
            "hwid": row['hwid'][:16] + "..." if row['hwid'] else None,
            "type": row['type'],
            "status": status,
            "created_at": row['created_at'],
            "expires_at": row['expires_at'],
            "activated": bool(row['activated']),
            "blocked": bool(row['blocked']),
            "activation_date": row['activation_date'],
            "notes": row['notes']
        })
    
    return jsonify({"licenses": result, "count": len(result)})


@app.route('/admin/stats', methods=['GET'])
@admin_required
def get_stats():
    """Статистика по лицензиям"""
    conn = get_db()
    c = conn.cursor()
    
    now = datetime.now().isoformat()
    
    # Общая статистика
    c.execute("SELECT COUNT(*) FROM licenses")
    total = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM licenses WHERE activated=1")
    activated = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM licenses WHERE blocked=1")
    blocked = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM licenses WHERE activated=0 AND blocked=0")
    pending = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM licenses WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
    expired = c.fetchone()[0]
    
    # По типам
    c.execute("SELECT type, COUNT(*) FROM licenses GROUP BY type")
    by_type = dict(c.fetchall())
    
    # Активации за последние 24 часа
    yesterday = (datetime.now() - timedelta(days=1)).isoformat()
    c.execute("SELECT COUNT(*) FROM licenses WHERE activation_date > ?", (yesterday,))
    activations_24h = c.fetchone()[0]
    
    # Активации за последние 7 дней
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    c.execute("SELECT COUNT(*) FROM licenses WHERE activation_date > ?", (week_ago,))
    activations_7d = c.fetchone()[0]
    
    conn.close()
    
    return jsonify({
        "total": total,
        "activated": activated,
        "blocked": blocked,
        "pending": pending,
        "expired": expired,
        "by_type": by_type,
        "activations_24h": activations_24h,
        "activations_7d": activations_7d,
        "server_time": datetime.now().isoformat()
    })


@app.route('/admin/search', methods=['GET'])
@admin_required
def search_license():
    """Поиск лицензии"""
    query = request.args.get('q', '').strip()
    
    if len(query) < 3:
        return jsonify({"error": "Query too short (min 3 chars)"}), 400
    
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM licenses 
        WHERE key LIKE ? OR hwid LIKE ? OR notes LIKE ?
        ORDER BY created_at DESC
        LIMIT 50
    """, (f"%{query}%", f"%{query}%", f"%{query}%"))
    rows = c.fetchall()
    conn.close()
    
    result = []
    for row in rows:
        result.append({
            "key": row['key'],
            "hwid": row['hwid'],
            "type": row['type'],
            "activated": bool(row['activated']),
            "blocked": bool(row['blocked']),
            "expires_at": row['expires_at']
        })
    
    return jsonify({"results": result, "count": len(result)})


@app.route('/admin/logs', methods=['GET'])
@admin_required
def get_logs():
    """Получить логи активности"""
    limit = min(int(request.args.get('limit', 100)), 500)
    action = request.args.get('action')
    
    conn = get_db()
    c = conn.cursor()
    
    if action:
        c.execute("""
            SELECT * FROM activity_logs 
            WHERE action=?
            ORDER BY timestamp DESC 
            LIMIT ?
        """, (action, limit))
    else:
        c.execute("""
            SELECT * FROM activity_logs 
            ORDER BY timestamp DESC 
            LIMIT ?
        """, (limit,))
    
    rows = c.fetchall()
    conn.close()
    
    logs = []
    for row in rows:
        logs.append({
            "id": row['id'],
            "timestamp": row['timestamp'],
            "action": row['action'],
            "license_key": row['license_key'][:16] + "..." if row['license_key'] else None,
            "hwid": row['hwid'][:16] + "..." if row['hwid'] else None,
            "ip": row['ip_address'],
            "details": row['details']
        })
    
    return jsonify({"logs": logs})


@app.route('/admin/export', methods=['GET'])
@admin_required
def export_licenses():
    """Экспорт лицензий"""
    format_type = request.args.get('format', 'json')
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM licenses ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    
    if format_type == 'text':
        lines = ["KEY | TYPE | STATUS | EXPIRES"]
        lines.append("-" * 60)
        for row in rows:
            status = "BLOCKED" if row['blocked'] else ("ACTIVE" if row['activated'] else "PENDING")
            lines.append(f"{row['key']} | {row['type']} | {status} | {row['expires_at'] or 'LIFETIME'}")
        return "\n".join(lines), 200, {'Content-Type': 'text/plain'}
    
    # JSON по умолчанию
    result = []
    for row in rows:
        result.append({
            "key": row['key'],
            "type": row['type'],
            "hwid": row['hwid'],
            "created_at": row['created_at'],
            "expires_at": row['expires_at'],
            "activated": bool(row['activated']),
            "blocked": bool(row['blocked'])
        })
    
    return jsonify({"licenses": result})


# ==================== HEALTH CHECK ====================

@app.route('/health', methods=['GET'])
def health_check():
    """Health check для мониторинга"""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM licenses")
        count = c.fetchone()[0]
        conn.close()
        return jsonify({
            "status": "healthy",
            "database": "connected",
            "licenses_count": count,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e)
        }), 500


@app.route('/api/version', methods=['GET'])
def get_version():
    """Получить информацию о последней версии приложения"""
    return jsonify({
        "version": "1.1.0",
        "download_url": "https://github.com/yourusername/rbxmt/releases/download/v1.1.0/RBXMT_v1.1.0.exe",
        "changelog": [
            "✨ Добавлена система автообновлений",
            "🔒 Улучшенная система HWID",
            "🔐 Шифрование файла лицензии",
            "📊 Расширенная аналитика в админке",
            "📁 Drag & Drop для файлов",
            "💾 Система резервного копирования",
            "📝 Продвинутое логирование",
            "🐛 Исправлены мелкие баги"
        ],
        "required": False,  # Обязательное обновление?
        "size_mb": 15.3,
        "release_date": "2025-12-19",
        "min_version": "1.0.0"  # Минимальная поддерживаемая версия
    })


@app.route('/admin/analytics/activations', methods=['GET'])
@admin_required
def get_activations_chart():
    """График активаций за последние 30 дней"""
    conn = get_db()
    c = conn.cursor()
    
    c.execute("""
        SELECT DATE(activation_date) as date, COUNT(*) as count
        FROM licenses
        WHERE activation_date IS NOT NULL 
        AND activation_date >= date('now', '-30 days')
        GROUP BY DATE(activation_date)
        ORDER BY date
    """)
    
    data = [{'date': row[0], 'count': row[1]} for row in c.fetchall()]
    conn.close()
    
    return jsonify({'data': data})


@app.route('/admin/analytics/revenue', methods=['GET'])
@admin_required
def get_revenue_stats():
    """Статистика доходов"""
    conn = get_db()
    c = conn.cursor()
    
    # Цены по типам лицензий
    prices = {
        'trial_1day': 2,
        'trial_3days': 5,
        'weekly': 10,
        'monthly': 25,
        'yearly': 200,
        'lifetime': 500
    }
    
    c.execute("""
        SELECT type, COUNT(*) as count
        FROM licenses
        WHERE activated = 1
        GROUP BY type
    """)
    
    revenue = {}
    total = 0
    for row in c.fetchall():
        license_type, count = row
        price = prices.get(license_type, 0)
        revenue[license_type] = {
            'count': count,
            'revenue': count * price,
            'price': price
        }
        total += count * price
    
    conn.close()
    
    return jsonify({
        'by_type': revenue,
        'total': total,
        'currency': 'USD'
    })


@app.route('/', methods=['GET'])
def index():
    """Главная страница"""
    return jsonify({
        "name": "License Server",
        "version": "2.0",
        "status": "running",
        "endpoints": {
            "client": ["/api/activate", "/api/verify", "/api/info", "/api/version"],
            "admin": ["/admin/generate", "/admin/list", "/admin/stats", "/admin/block", "/admin/unblock", "/admin/reset-hwid", "/admin/extend", "/admin/delete", "/admin/search", "/admin/logs", "/admin/export", "/admin/analytics/activations", "/admin/analytics/revenue"],
            "health": ["/health"]
        }
    })


# ==================== ЗАПУСК ====================

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('DEBUG', 'false').lower() == 'true'
    
    logger.info(f"🚀 License Server v2.0 запускается на порту {port}")
    app.run(host='0.0.0.0', port=port, debug=debug)
