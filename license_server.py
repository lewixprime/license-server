from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import sqlite3
import hashlib
import secrets
import os

app = Flask(__name__)

# Инициализация БД
def init_db():
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS licenses
                 (key TEXT PRIMARY KEY,
                  hwid TEXT,
                  type TEXT,
                  created_at TEXT,
                  expires_at TEXT,
                  activated INTEGER DEFAULT 0,
                  blocked INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

init_db()

def generate_license_key():
    """Генерация уникального ключа"""
    return secrets.token_hex(16).upper()

@app.route('/api/activate', methods=['POST'])
def activate_license():
    """Активация лицензии"""
    data = request.json
    license_key = data.get('key')
    hwid = data.get('hwid')
    
    if not license_key or not hwid:
        return jsonify({"success": False, "message": "Неверные данные"}), 400
    
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    # Проверка существования ключа
    c.execute("SELECT * FROM licenses WHERE key=?", (license_key,))
    license_data = c.fetchone()
    
    if not license_data:
        conn.close()
        return jsonify({"success": False, "message": "Ключ не найден"}), 404
    
    key, stored_hwid, license_type, created_at, expires_at, activated, blocked = license_data
    
    # Проверка блокировки
    if blocked:
        conn.close()
        return jsonify({"success": False, "message": "Ключ заблокирован"}), 403
    
    # Проверка истечения
    if expires_at and datetime.fromisoformat(expires_at) < datetime.now():
        conn.close()
        return jsonify({"success": False, "message": "Срок действия истек"}), 403
    
    # Если уже активирован, проверяем HWID
    if activated:
        if stored_hwid != hwid:
            conn.close()
            return jsonify({"success": False, "message": "Ключ привязан к другому устройству"}), 403
    else:
        # Первая активация - привязываем к HWID
        c.execute("UPDATE licenses SET hwid=?, activated=1 WHERE key=?", (hwid, license_key))
        conn.commit()
    
    conn.close()
    
    return jsonify({
        "success": True,
        "message": "Лицензия активирована",
        "expiry_date": expires_at,
        "type": license_type
    })

@app.route('/api/verify', methods=['POST'])
def verify_license():
    """Проверка валидности лицензии"""
    data = request.json
    license_key = data.get('key')
    hwid = data.get('hwid')
    
    if not license_key or not hwid:
        return jsonify({"valid": False, "message": "Неверные данные"}), 400
    
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    c.execute("SELECT * FROM licenses WHERE key=?", (license_key,))
    license_data = c.fetchone()
    conn.close()
    
    if not license_data:
        return jsonify({"valid": False, "message": "Ключ не найден"})
    
    key, stored_hwid, license_type, created_at, expires_at, activated, blocked = license_data
    
    if blocked:
        return jsonify({"valid": False, "message": "Ключ заблокирован"})
    
    if stored_hwid != hwid:
        return jsonify({"valid": False, "message": "HWID не совпадает"})
    
    if expires_at and datetime.fromisoformat(expires_at) < datetime.now():
        return jsonify({"valid": False, "message": "Срок действия истек"})
    
    return jsonify({
        "valid": True,
        "message": "Лицензия действительна",
        "expiry_date": expires_at,
        "type": license_type
    })

@app.route('/api/info', methods=['POST'])
def license_info():
    """Информация о лицензии"""
    data = request.json
    license_key = data.get('key')
    hwid = data.get('hwid')
    
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    c.execute("SELECT * FROM licenses WHERE key=? AND hwid=?", (license_key, hwid))
    license_data = c.fetchone()
    conn.close()
    
    if not license_data:
        return jsonify({"error": "Лицензия не найдена"}), 404
    
    key, stored_hwid, license_type, created_at, expires_at, activated, blocked = license_data
    
    days_left = None
    if expires_at:
        delta = datetime.fromisoformat(expires_at) - datetime.now()
        days_left = max(0, delta.days)
    
    return jsonify({
        "key": key[:8] + "...",
        "type": license_type,
        "created_at": created_at,
        "expires_at": expires_at,
        "days_left": days_left,
        "activated": bool(activated),
        "blocked": bool(blocked)
    })

# Админ пароль (ИЗМЕНИ ЭТО!)
ADMIN_PASSWORD = "9724776_rD"

def check_admin_auth():
    """Проверка авторизации админа"""
    auth = request.headers.get('Authorization')
    if not auth or auth != f"Bearer {ADMIN_PASSWORD}":
        return False
    return True

# Админ функции
@app.route('/admin/generate', methods=['POST'])
def generate_license():
    """Генерация новой лицензии"""
    if not check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    license_type = data.get('type', 'monthly')  # trial, weekly, monthly, lifetime
    count = data.get('count', 1)
    
    # Определение срока действия
    duration_map = {
        'trial_1day': 1,
        'trial_3days': 3,
        'weekly': 7,
        'monthly': 30,
        'yearly': 365,
        'lifetime': None
    }
    
    days = duration_map.get(license_type)
    
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    
    generated_keys = []
    for _ in range(count):
        key = generate_license_key()
        created_at = datetime.now().isoformat()
        expires_at = (datetime.now() + timedelta(days=days)).isoformat() if days else None
        
        c.execute("""INSERT INTO licenses (key, type, created_at, expires_at)
                     VALUES (?, ?, ?, ?)""",
                  (key, license_type, created_at, expires_at))
        generated_keys.append(key)
    
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "keys": generated_keys})

@app.route('/admin/block', methods=['POST'])
def block_license():
    """Блокировка лицензии"""
    if not check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    license_key = data.get('key')
    
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    c.execute("UPDATE licenses SET blocked=1 WHERE key=?", (license_key,))
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "message": "Ключ заблокирован"})

@app.route('/admin/list', methods=['GET'])
def list_licenses():
    """Список всех лицензий"""
    if not check_admin_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    c.execute("SELECT * FROM licenses ORDER BY created_at DESC")
    licenses = c.fetchall()
    conn.close()
    
    result = []
    for lic in licenses:
        result.append({
            "key": lic[0],
            "hwid": lic[1][:16] + "..." if lic[1] else None,
            "type": lic[2],
            "created_at": lic[3],
            "expires_at": lic[4],
            "activated": bool(lic[5]),
            "blocked": bool(lic[6])
        })
    
    return jsonify({"licenses": result})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
