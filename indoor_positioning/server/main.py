"""
Indoor Positioning System - Enhanced with Detailed Logging
"""

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import time
import threading
from datetime import datetime, timedelta
from collections import defaultdict, deque
import logging
import json
import os
import sys

from trilateration import TrilaterationEngine, calculate_confidence

app = Flask(__name__)
app.config['SECRET_KEY'] = 'indoor_positioning_secret'

socketio = SocketIO(app,
                    cors_allowed_origins="*",
                    async_mode='threading',
                    logger=True,
                    engineio_logger=True)

# Настройка расширенного логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('positioning_system.log')
    ]
)
logger = logging.getLogger(__name__)

# Конфигурационные файлы
CONFIG_FILE = 'room_config.json'
ANCHORS_FILE = 'anchors_config.json'

# Стандартная конфигурация
DEFAULT_ROOM_CONFIG = {
    'width': 20,
    'height': 15,
    'depth': 5
}

DEFAULT_ANCHORS_CONFIG = {
    'Якорь_1': {'x': 0, 'y': 0, 'z': 2.5, 'enabled': True},
    'Якорь_2': {'x': 20, 'y': 0, 'z': 2.5, 'enabled': True},
    'Якорь_3': {'x': 20, 'y': 15, 'z': 2.5, 'enabled': True},
    'Якорь_4': {'x': 0, 'y': 15, 'z': 1.0, 'enabled': True}
}

def log_system_info():
    """Логирование информации о системе при запуске"""
    logger.info("=" * 50)
    logger.info("🚀 Indoor Positioning System Starting")
    logger.info("=" * 50)
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Working directory: {os.getcwd()}")
    logger.info(f"Config files: {CONFIG_FILE}, {ANCHORS_FILE}")

# Загрузка конфигураций
def load_config():
    global room_config, anchors_config

    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                room_config = json.load(f)
            logger.info(f"✅ Room config loaded from {CONFIG_FILE}")
        else:
            room_config = DEFAULT_ROOM_CONFIG.copy()
            save_room_config()
            logger.info("✅ Default room config created")
    except Exception as e:
        logger.error(f"❌ Error loading room config: {e}")
        room_config = DEFAULT_ROOM_CONFIG.copy()

    try:
        if os.path.exists(ANCHORS_FILE):
            with open(ANCHORS_FILE, 'r', encoding='utf-8') as f:
                anchors_config = json.load(f)
            logger.info(f"✅ Anchors config loaded from {ANCHORS_FILE}")
        else:
            anchors_config = DEFAULT_ANCHORS_CONFIG.copy()
            save_anchors_config()
            logger.info("✅ Default anchors config created")
    except Exception as e:
        logger.error(f"❌ Error loading anchors config: {e}")
        anchors_config = DEFAULT_ANCHORS_CONFIG.copy()

def save_room_config():
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(room_config, f, indent=2, ensure_ascii=False)
        logger.info(f"💾 Room config saved to {CONFIG_FILE}")
        return True
    except Exception as e:
        logger.error(f"❌ Error saving room config: {e}")
        return False

def save_anchors_config():
    try:
        with open(ANCHORS_FILE, 'w', encoding='utf-8') as f:
            json.dump(anchors_config, f, indent=2, ensure_ascii=False)
        logger.info(f"💾 Anchors config saved to {ANCHORS_FILE}")
        return True
    except Exception as e:
        logger.error(f"❌ Error saving anchors config: {e}")
        return False

# Инициализация конфигураций
log_system_info()
load_config()

# Хранилища данных
anchors = {}  # Активные якоря с временными метками
devices = {}  # Обнаруженные устройства
positions = {}  # Рассчитанные позиции
anchor_data = defaultdict(lambda: deque(maxlen=10))

# Статус системы
system_status = {
    'is_running': True,
    'start_time': datetime.now().isoformat(),
    'total_updates': 0,
    'last_calculation': None
}

# Статистика
statistics = {
    'connections': 0,
    'position_updates': 0,
    'anchor_updates': 0,
    'devices_detected': 0,
    'calculation_errors': 0,
    'active_anchors': 0
}

# Инициализация движка трилатерации
trilateration_engine = TrilaterationEngine({
    'width': room_config['width'],
    'height': room_config['height'],
    'anchors': {k: v for k, v in anchors_config.items() if v['enabled']}
})
logger.info("✅ Trilateration engine initialized")

# Валидация конфигурации
def validate_anchor_position(anchor_id, x, y, z, room_config):
    """Проверяет, что якорь находится в пределах комнаты"""
    errors = []

    if x < 0 or x > room_config['width']:
        errors.append(f"Координата X якоря {anchor_id} ({x}) выходит за пределы комнаты (0-{room_config['width']})")

    if y < 0 or y > room_config['height']:
        errors.append(f"Координата Y якоря {anchor_id} ({y}) выходит за пределы комнаты (0-{room_config['height']})")

    if z < 0 or z > room_config['depth']:
        errors.append(f"Координата Z якоря {anchor_id} ({z}) выходит за пределы комнаты (0-{room_config['depth']})")

    return errors

def validate_anchors_config(anchors_config, room_config):
    """Проверяет всю конфигурацию якорей"""
    all_errors = []
    enabled_anchors = 0

    for anchor_id, config in anchors_config.items():
        if config.get('enabled', True):
            enabled_anchors += 1
            errors = validate_anchor_position(
                anchor_id, config['x'], config['y'], config['z'], room_config
            )
            all_errors.extend(errors)

    # Проверяем минимальное количество якорей
    if enabled_anchors < 2:
        all_errors.append("Для работы системы необходимо как минимум 2 активных якоря")

    logger.info(f"🔍 Config validation: {enabled_anchors} enabled anchors, {len(all_errors)} errors")
    return all_errors

@app.route('/')
def index():
    logger.info("🌐 Home page accessed")
    return render_template('index.html',
                         room_config=room_config,
                         anchors_config=anchors_config)

# API для получения конфигураций
@app.route('/api/config/room')
def get_room_config():
    logger.info("📋 Room config requested")
    return jsonify(room_config)

@app.route('/api/config/anchors')
def get_anchors_config():
    logger.info("📋 Anchors config requested")
    return jsonify(anchors_config)

@app.route('/api/anchors')
def get_anchors():
    return jsonify(dict(anchors))

@app.route('/api/devices')
def get_devices():
    return jsonify(dict(devices))

@app.route('/api/positions')
def get_positions():
    return jsonify(dict(positions))

@app.route('/api/status')
def get_status():
    return jsonify({
        'system': system_status,
        'statistics': statistics
    })

# API для обновления конфигураций
@app.route('/api/config/room', methods=['POST'])
def update_room_config():
    try:
        data = request.get_json()
        logger.info(f"🔄 Room config update request: {data}")

        if not data:
            return jsonify({'error': 'No data provided'}), 400

        # Валидируем новые размеры комнаты
        new_room_config = room_config.copy()
        new_room_config.update(data)

        # Проверяем, что якоря остаются в новых границах
        validation_errors = validate_anchors_config(anchors_config, new_room_config)
        if validation_errors:
            logger.warning(f"❌ Room config validation failed: {validation_errors}")
            return jsonify({'error': 'Validation failed', 'details': validation_errors}), 400

        # Сохраняем новую конфигурацию
        room_config.update(data)
        if save_room_config():
            # Обновляем движок трилатерации
            trilateration_engine.update_room_config({
                'width': room_config['width'],
                'height': room_config['height'],
                'anchors': {k: v for k, v in anchors_config.items() if v['enabled']}
            })

            emit_log(f"Конфигурация комнаты обновлена: {room_config}", 'success')
            socketio.emit('room_config_updated', room_config)
            logger.info("✅ Room config updated successfully")
            return jsonify({'status': 'success', 'config': room_config})
        else:
            logger.error("❌ Failed to save room config")
            return jsonify({'error': 'Failed to save config'}), 500
    except Exception as e:
        logger.error(f"❌ Error updating room config: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/anchors', methods=['POST'])
def update_anchors_config():
    try:
        data = request.get_json()
        logger.info(f"🔄 Anchors config update request: {data}")

        if not data:
            return jsonify({'error': 'No data provided'}), 400

        # Валидируем новую конфигурацию
        validation_errors = validate_anchors_config(data, room_config)
        if validation_errors:
            logger.warning(f"❌ Anchors config validation failed: {validation_errors}")
            return jsonify({'error': 'Validation failed', 'details': validation_errors}), 400

        # Полностью заменяем конфигурацию
        anchors_config.clear()
        anchors_config.update(data)

        if save_anchors_config():
            # Обновляем движок трилатерации
            trilateration_engine.update_room_config({
                'width': room_config['width'],
                'height': room_config['height'],
                'anchors': {k: v for k, v in anchors_config.items() if v['enabled']}
            })

            emit_log("Конфигурация якорей обновлена", 'success')
            socketio.emit('anchors_config_updated', anchors_config)
            logger.info("✅ Anchors config updated successfully")
            return jsonify({'status': 'success', 'config': anchors_config})
        else:
            logger.error("❌ Failed to save anchors config")
            return jsonify({'error': 'Failed to save config'}), 500
    except Exception as e:
        logger.error(f"❌ Error updating anchors config: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/validate', methods=['POST'])
def validate_config():
    """API для валидации конфигурации"""
    try:
        data = request.get_json()
        logger.info("🔍 Config validation request")

        room_config_to_validate = data.get('room', room_config)
        anchors_config_to_validate = data.get('anchors', anchors_config)

        errors = validate_anchors_config(anchors_config_to_validate, room_config_to_validate)

        result = {
            'valid': len(errors) == 0,
            'errors': errors,
            'enabled_anchors_count': sum(1 for config in anchors_config_to_validate.values() if config.get('enabled', True))
        }

        logger.info(f"✅ Config validation result: {result}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"❌ Config validation error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/anchor_data', methods=['POST'])
def receive_anchor_data():
    try:
        data = request.get_json()
        logger.info(f"📨 Data received from anchor: {data.get('anchor_id')}")

        if not data:
            logger.warning("❌ No data received")
            return jsonify({'error': 'Не получены данные'}), 400

        anchor_id = data.get('anchor_id')
        measurements = data.get('measurements', [])

        if not anchor_id:
            logger.warning("❌ Missing anchor_id")
            return jsonify({'error': 'Отсутствует anchor_id'}), 400

        # Проверяем, включен ли якорь в конфигурации
        if anchor_id not in anchors_config:
            logger.warning(f"❌ Anchor {anchor_id} not found in config")
            return jsonify({'error': 'Anchor not found in config'}), 400

        if not anchors_config[anchor_id].get('enabled', True):
            logger.warning(f"❌ Anchor {anchor_id} is disabled")
            return jsonify({'error': 'Anchor disabled'}), 400

        # Обновляем информацию о якоре (помечаем как активный)
        anchor_config = anchors_config[anchor_id]
        anchors[anchor_id] = {
            'x': anchor_config['x'],
            'y': anchor_config['y'],
            'z': anchor_config['z'],
            'last_update': datetime.now().isoformat(),
            'status': 'active',
            'enabled': True,
            'measurements_count': len(measurements)
        }

        logger.info(f"✅ Anchor {anchor_id} marked as active with {len(measurements)} measurements")

        # Обрабатываем измерения
        _process_anchor_measurements(anchor_id, measurements)

        statistics['anchor_updates'] += 1
        system_status['total_updates'] += 1

        # Пересчитываем позиции
        calculate_positions()

        return jsonify({'status': 'success', 'message': 'Данные получены'})

    except Exception as e:
        logger.error(f"❌ Error processing anchor data: {e}")
        statistics['calculation_errors'] += 1
        return jsonify({'error': str(e)}), 500

def _process_anchor_measurements(anchor_id, measurements):
    logger.info(f"📊 Processing {len(measurements)} measurements from {anchor_id}")

    for measurement in measurements:
        mac = measurement.get('mac')
        distance = measurement.get('distance')
        rssi = measurement.get('rssi')

        if mac and distance is not None:
            anchor_data[mac].append({
                'anchor_id': anchor_id,
                'distance': float(distance),
                'rssi': rssi,
                'timestamp': datetime.now().isoformat()
            })

            if mac not in devices:
                devices[mac] = {
                    'mac': mac,
                    'first_seen': datetime.now().isoformat(),
                    'type': 'mobile_device',
                    'color': _generate_color_from_mac(mac)
                }
                logger.info(f"📱 New device detected: {mac}")

def calculate_positions():
    try:
        logger.info(f"🎯 Starting position calculation for {len(anchor_data)} devices")

        calculated_positions = 0
        for mac, measurements_list in anchor_data.items():
            anchor_measurements = _group_recent_measurements(measurements_list)

            if len(anchor_measurements) >= 2:
                if _calculate_device_position(mac, anchor_measurements):
                    calculated_positions += 1
            else:
                logger.debug(f"⚠️ Not enough anchors for {mac}: {len(anchor_measurements)}")

        statistics['devices_detected'] = len(devices)
        logger.info(f"✅ Position calculation completed: {calculated_positions} positions calculated")

    except Exception as e:
        logger.error(f"❌ Error in position calculation: {e}")
        statistics['calculation_errors'] += 1

def _group_recent_measurements(measurements_list):
    anchor_measurements = {}
    current_time = datetime.now()

    for measurement in measurements_list:
        measure_time = datetime.fromisoformat(measurement['timestamp'])
        if (current_time - measure_time).total_seconds() <= 10:
            anchor_id = measurement['anchor_id']
            if anchor_id not in anchor_measurements:
                anchor_measurements[anchor_id] = []
            anchor_measurements[anchor_id].append(measurement['distance'])

    return anchor_measurements

def _calculate_device_position(mac, anchor_measurements):
    avg_distances = {}
    for anchor_id, distances in anchor_measurements.items():
        avg_distances[anchor_id] = sum(distances) / len(distances)

    logger.debug(f"📐 Calculating position for {mac} using anchors: {list(avg_distances.keys())}")

    position = trilateration_engine.calculate_position(avg_distances)

    if position:
        confidence = calculate_confidence(avg_distances, position)

        positions[mac] = {
            'position': position,
            'timestamp': datetime.now().isoformat(),
            'confidence': confidence * 0.8 if len(avg_distances) == 2 else confidence,
            'anchors_used': len(avg_distances),
            'type': devices[mac]['type'] if mac in devices else 'unknown'
        }

        statistics['position_updates'] += 1
        system_status['last_calculation'] = datetime.now().isoformat()

        _emit_position_update(mac, positions[mac])

        logger.info(f"📍 Position calculated for {mac}: ({position['x']:.2f}, {position['y']:.2f}, {position['z']:.2f})")
        return True

    logger.warning(f"❌ Failed to calculate position for {mac}")
    return False

def _emit_position_update(mac, position_data):
    socketio.emit('position_update', {
        'device_id': mac,
        'position': position_data['position'],
        'timestamp': position_data['timestamp'],
        'confidence': position_data['confidence'],
        'anchors_used': position_data['anchors_used']
    })

def _generate_color_from_mac(mac):
    import hashlib
    hash_obj = hashlib.md5(mac.encode())
    hash_hex = hash_obj.hexdigest()[:6]
    return f'#{hash_hex}'

# WebSocket обработчики
@socketio.on('connect')
def handle_connect():
    statistics['connections'] += 1
    logger.info(f"🔌 Client connected. Total connections: {statistics['connections']}")

    emit('system_status', system_status)
    emit('anchors_data', anchors)
    emit('devices_data', devices)
    emit('positions_data', positions)
    emit('statistics_update', statistics)
    emit('room_config_updated', room_config)
    emit('anchors_config_updated', anchors_config)
    emit_log('Новый клиент подключился', 'info')

@socketio.on('disconnect')
def handle_disconnect():
    statistics['connections'] = max(0, statistics['connections'] - 1)
    logger.info(f"🔌 Client disconnected. Total connections: {statistics['connections']}")
    emit_log('Клиент отключился', 'warning')

@socketio.on('toggle_positioning')
def handle_toggle_positioning(data):
    system_status['is_running'] = data.get('is_running', True)
    status_text = "активирована" if system_status['is_running'] else "остановлена"
    logger.info(f"⚡ System {status_text}")
    emit_log(f'Система {status_text}', 'info')
    emit('system_status', system_status)

def emit_log(message, log_type='info'):
    log_data = {
        'message': message,
        'type': log_type,
        'timestamp': datetime.now().isoformat()
    }
    logger.info(f"📝 {log_type.upper()}: {message}")
    socketio.emit('log_message', log_data)


def background_task():
    """Фоновая задача для обслуживания данных системы"""
    logger.info("🔄 Background task started")

    while True:
        try:
            current_time = datetime.now()

            # Автоматическое определение неактивных якорей
            _update_anchors_status(current_time)

            # Очистка устаревших позиций
            _cleanup_old_positions(current_time)

            # Очистка старых измерений
            _cleanup_old_measurements(current_time)

            # Обновление статистики активных якорей
            _update_active_anchors_count()

            # Отправка обновлений
            socketio.emit('system_status', system_status)
            socketio.emit('statistics_update', statistics)
            socketio.emit('anchors_data', anchors)
            socketio.emit('devices_data', devices)
            socketio.emit('positions_data', positions)

        except Exception as e:
            logger.error(f"❌ Background task error: {e}")

        time.sleep(2)


def _update_active_anchors_count():
    """Обновляет счетчик активных якорей в статистике"""
    active_count = 0
    current_time = datetime.now()

    for anchor_id, anchor_data in anchors.items():
        if anchor_data.get('enabled', True):
            last_update = datetime.fromisoformat(anchor_data['last_update'])
            time_since_update = (current_time - last_update).total_seconds()

            # Якорь считается активным если обновлялся в последние 30 секунд
            if time_since_update <= 30:
                active_count += 1
                anchors[anchor_id]['status'] = 'active'
            else:
                anchors[anchor_id]['status'] = 'inactive'

    statistics['active_anchors'] = active_count

def _update_anchors_status(current_time):
    """Обновляет статус якорей на основе времени последнего обновления"""
    inactive_anchors = []

    for anchor_id, anchor_data in anchors.items():
        last_update = datetime.fromisoformat(anchor_data['last_update'])
        time_since_update = (current_time - last_update).total_seconds()

        # Если якорь не обновлялся более 30 секунд, помечаем как неактивный
        if time_since_update > 30:
            if anchor_data['status'] == 'active':
                anchors[anchor_id]['status'] = 'inactive'
                logger.warning(f"⚠️ Anchor {anchor_id} marked as inactive (no data for {time_since_update:.1f}s)")
                emit_log(f'Якорь {anchor_id} отключился (нет данных)', 'warning')
                socketio.emit('anchor_updated', {
                    'anchor_id': anchor_id,
                    'config': anchors[anchor_id]
                })

        # Если якорь не обновлялся более 60 секунд, удаляем его
        elif time_since_update > 60:
            inactive_anchors.append(anchor_id)

    # Удаляем давно неактивные якоря
    for anchor_id in inactive_anchors:
        if anchor_id in anchors:
            del anchors[anchor_id]
            logger.warning(f"🗑️ Anchor {anchor_id} removed from system")
            emit_log(f'Якорь {anchor_id} удален из системы', 'warning')
            socketio.emit('anchor_removed', {'anchor_id': anchor_id})

def _cleanup_old_positions(current_time):
    expired_positions = []
    for mac, pos_data in positions.items():
        pos_time = datetime.fromisoformat(pos_data['timestamp'])
        if (current_time - pos_time).total_seconds() > 10:
            expired_positions.append(mac)

    for mac in expired_positions:
        del positions[mac]
        logger.debug(f"🧹 Expired position removed: {mac}")
        socketio.emit('position_removed', {'device_id': mac})

def _cleanup_old_measurements(current_time):
    expired_devices = []
    for mac in list(anchor_data.keys()):
        anchor_data[mac] = deque(
            [m for m in anchor_data[mac]
             if (current_time - datetime.fromisoformat(m['timestamp'])).total_seconds() <= 10],
            maxlen=10
        )

        # Если устройство долго не обновлялось, удаляем его
        if len(anchor_data[mac]) == 0:
            expired_devices.append(mac)

    for mac in expired_devices:
        if mac in devices:
            del devices[mac]
            del anchor_data[mac]
            logger.debug(f"🧹 Expired device removed: {mac}")
            socketio.emit('device_removed', {'device_id': mac})

if __name__ == '__main__':
    logger.info("🚀 Starting Indoor Positioning System...")
    logger.info("📍 Web interface: http://localhost:5000")

    bg_thread = threading.Thread(target=background_task, daemon=True)
    bg_thread.start()

    try:
        socketio.run(app,
                     host='0.0.0.0',
                     port=5000,
                     debug=False,
                     use_reloader=False,
                     allow_unsafe_werkzeug=True)
    except Exception as e:
        logger.error(f"❌ Failed to start server: {e}")
