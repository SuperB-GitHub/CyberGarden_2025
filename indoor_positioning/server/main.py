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
import numpy as np
from trilateration import EnhancedTrilaterationEngine, calculate_enhanced_confidence


class AdaptiveKalmanFilter:
    """Адаптивный фильтр Калмана для RSSI с автоматической настройкой параметров"""

    def __init__(self, process_noise=0.1, measurement_noise=2.0):
        self.Q = process_noise  # Шум процесса
        self.R = measurement_noise  # Шум измерения
        self.P = 1.0  # Ковариация ошибки
        self.X = 0.0  # Оценка
        self.measurement_count = 0
        self.measurement_history = deque(maxlen=10)

    def update(self, measurement, packet_count=1):
        # Адаптивная настройка шума измерения на основе packet_count
        adaptive_R = self.R / min(packet_count, 5)  # Уменьшаем шум с ростом packet_count

        # Прогноз
        self.P = self.P + self.Q

        # Коррекция
        K = self.P / (self.P + adaptive_R)
        self.X = self.X + K * (measurement - self.X)
        self.P = (1 - K) * self.P

        # Сохраняем историю для адаптации
        self.measurement_history.append(measurement)
        self.measurement_count += 1

        # Адаптируем шум процесса на основе дисперсии измерений
        if len(self.measurement_history) >= 5:
            variance = np.var(list(self.measurement_history))
            self.Q = max(0.01, min(0.5, variance * 0.1))

        return self.X

    def get_confidence(self):
        """Возвращает уверенность в текущей оценке"""
        if self.measurement_count == 0:
            return 0.0
        return min(1.0, self.measurement_count / 10.0) * (1.0 / (1.0 + self.P))

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

# Глобальные хранилища для расширенных данных
device_kalman_filters = defaultdict(AdaptiveKalmanFilter)
device_channel_data = defaultdict(lambda: deque(maxlen=20))
device_packet_stats = defaultdict(lambda: {'count': 0, 'first_seen': None})


# Функции для обработки частот и коррекции расстояний
def get_frequency_correction(channel):
    """Корректировка расстояния на основе частоты канала"""
    # 2.4 GHz каналы (1-14)
    if 1 <= channel <= 14:
        return 1.0  # Базовая коррекция для 2.4GHz

    # 5 GHz каналы (36-165)
    elif 36 <= channel <= 165:
        return 0.85  # 5GHz сигналы затухают быстрее

    # Неизвестные каналы
    else:
        return 1.0


def get_channel_group(channel):
    """Группировка каналов для калибровки"""
    if 1 <= channel <= 14:
        return '2.4GHz'
    elif 36 <= channel <= 64:
        return '5GHz_LOW'
    elif 100 <= channel <= 165:
        return '5GHz_HIGH'
    else:
        return 'UNKNOWN'


def apply_channel_correction(distance, channel, rssi_filtered):
    """Применяет коррекцию расстояния на основе канала и RSSI"""
    base_correction = get_frequency_correction(channel)

    # Дополнительная коррекция на основе качества сигнала
    if rssi_filtered > -50:
        signal_quality_correction = 0.9  # Отличный сигнал
    elif rssi_filtered > -70:
        signal_quality_correction = 1.0  # Хороший сигнал
    else:
        signal_quality_correction = 1.1  # Слабый сигнал

    corrected_distance = distance * base_correction * signal_quality_correction

    # Ограничиваем разумными пределами
    return max(0.1, min(50.0, corrected_distance))


def calculate_distance_confidence(rssi_filtered, packet_count, channel_consistency):
    """Улучшенный расчет уверенности в измерении расстояния."""
    # Более мягкая оценка по RSSI
    if rssi_filtered > -45:
        rssi_confidence = 0.95
    elif rssi_filtered > -55:
        rssi_confidence = 0.85
    elif rssi_filtered > -65:
        rssi_confidence = 0.75
    elif rssi_filtered > -75:
        rssi_confidence = 0.60
    elif rssi_filtered > -85:
        rssi_confidence = 0.45
    else:
        rssi_confidence = 0.30

    # Более мягкая оценка по пакетам
    packet_confidence = min(1.0, 0.3 + (packet_count / 10.0) * 0.7)

    # Общая уверенность (более сбалансированная)
    total_confidence = (
            rssi_confidence * 0.6 +  # 60% за RSSI
            packet_confidence * 0.3 +  # 30% за пакеты
            channel_consistency * 0.1  # 10% за канал
    )

    # Гарантированный минимум при хороших условиях
    if rssi_filtered > -65 and packet_count >= 3:
        total_confidence = max(total_confidence, 0.6)

    return max(0.1, min(1.0, total_confidence))


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
anchor_data = defaultdict(list)

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
trilateration_engine = EnhancedTrilaterationEngine({
    'width': room_config['width'],
    'height': room_config['height'],
    'depth': room_config.get('depth', 5),
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
    try:
        # Создаем сериализуемую копию devices
        serializable_devices = {}
        for mac, device in devices.items():
            serializable_devices[mac] = device.copy()
            if 'channels_used' in serializable_devices[mac]:
                serializable_devices[mac]['channels_used'] = list(serializable_devices[mac]['channels_used'])

        return jsonify(serializable_devices)
    except Exception as e:
        logger.error(f"❌ Error serializing devices: {e}")
        return jsonify({'error': 'Serialization error'}), 500

@app.route('/api/positions')
def get_positions():
    return jsonify(dict(positions))

@app.route('/api/status')
def get_status():
    return jsonify({
        'system': system_status,
        'statistics': statistics
    })


def _update_active_anchors_from_config():
    """Обновляет активные якоря из конфигурации"""
    current_time = datetime.now().isoformat()

    for anchor_id, config in anchors_config.items():
        if config.get('enabled', True):
            # Если якорь уже активен - обновляем координаты
            if anchor_id in anchors:
                anchors[anchor_id].update({
                    'x': config['x'],
                    'y': config['y'],
                    'z': config['z'],
                    'last_update': current_time
                })
                logger.debug(f"🔄 Updated active anchor {anchor_id} coordinates")
            else:
                # Если якорь не активен - создаем новую запись
                anchors[anchor_id] = {
                    'x': config['x'],
                    'y': config['y'],
                    'z': config['z'],
                    'last_update': current_time,
                    'status': 'inactive',  # Будет активен после получения данных
                    'enabled': True,
                    'measurements_count': 0
                }
                logger.debug(f"🆕 Created new anchor {anchor_id} from config")

        # Если якорь отключен в конфигурации - удаляем из активных
        elif anchor_id in anchors and not config.get('enabled', True):
            del anchors[anchor_id]
            logger.debug(f"🗑️ Removed disabled anchor {anchor_id} from active anchors")

    logger.info(f"📊 Active anchors after config update: {list(anchors.keys())}")

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
            # ОБНОВЛЯЕМ АКТИВНЫЕ ЯКОРЯ С НОВЫМИ КООРДИНАТАМИ
            _update_active_anchors_from_config()

            # ОБНОВЛЯЕМ ДВИЖОК ТРИЛАТЕРАЦИИ С АКТУАЛЬНЫМИ ДАННЫМИ
            enabled_anchors = {k: v for k, v in anchors_config.items() if v.get('enabled', True)}
            trilateration_engine.update_room_config({
                'width': room_config['width'],
                'height': room_config['height'],
                'anchors': enabled_anchors
            })

            logger.info(
                f"✅ Room config updated: width={room_config['width']}, height={room_config['height']}, depth={room_config['depth']}")
            logger.info(f"📊 Trilateration engine updated with {len(enabled_anchors)} anchors")

            emit_log(f"Конфигурация комнаты обновлена: {room_config}", 'success')
            socketio.emit('room_config_updated', room_config)
            socketio.emit('anchors_data', anchors)
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

        # ОБНОВЛЯЕМ АКТИВНЫЕ ЯКОРЯ С НОВЫМИ КООРДИНАТАМИ
        _update_active_anchors_from_config()

        # ОБНОВЛЯЕМ ДВИЖОК ТРИЛАТЕРАЦИИ
        enabled_anchors = {k: v for k, v in anchors_config.items() if v.get('enabled', True)}
        trilateration_engine.update_room_config({
            'width': room_config['width'],
            'height': room_config['height'],
            'anchors': enabled_anchors
        })

        # ЛОГИРУЕМ ИЗМЕНЕНИЯ
        logger.info(f"🔧 Anchors config updated: {len(enabled_anchors)} enabled anchors")
        logger.info(f"📊 Trilateration engine updated with new anchors configuration")

        for anchor_id, new_config in data.items():
            if anchor_id in enabled_anchors:
                logger.info(f"📍 Anchor {anchor_id}: ({new_config['x']}, {new_config['y']}, {new_config['z']})")

        if save_anchors_config():
            emit_log("Конфигурация якорей обновлена", 'success')
            socketio.emit('anchors_config_updated', anchors_config)
            socketio.emit('anchors_data', anchors)
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

        # ОБНОВЛЯЕМ ИНФОРМАЦИЮ О ЯКОРЕ С АКТУАЛЬНЫМИ КООРДИНАТАМИ ИЗ КОНФИГУРАЦИИ
        anchor_config = anchors_config[anchor_id]
        if anchor_id in anchors:
            # Обновляем существующий якорь
            anchors[anchor_id].update({
                'x': anchor_config['x'],
                'y': anchor_config['y'],
                'z': anchor_config['z'],
                'last_update': datetime.now().isoformat(),
                'status': 'active',
                'measurements_count': len(measurements)
            })
        else:
            # Создаем новый активный якорь
            anchors[anchor_id] = {
                'x': anchor_config['x'],
                'y': anchor_config['y'],
                'z': anchor_config['z'],
                'last_update': datetime.now().isoformat(),
                'status': 'active',
                'enabled': True,
                'measurements_count': len(measurements)
            }

        logger.info(f"✅ Anchor {anchor_id} updated with coordinates ({anchor_config['x']}, {anchor_config['y']}, {anchor_config['z']})")

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


def _calculate_channel_consistency(mac):
    """Рассчитывает согласованность использования каналов"""
    if mac not in device_channel_data or len(device_channel_data[mac]) < 2:
        return 0.5  # Средняя уверенность при недостатке данных

    channels = [data['channel'] for data in device_channel_data[mac]]
    unique_channels = len(set(channels))
    total_measurements = len(channels)

    # Чем меньше разных каналов используется, тем выше согласованность
    consistency = 1.0 - (unique_channels / total_measurements) * 0.5

    return max(0.1, min(1.0, consistency))


def _process_anchor_measurements(anchor_id, measurements):
    logger.info(f"📊 Processing {len(measurements)} measurements from {anchor_id}")

    for measurement in measurements:
        # Проверяем структуру measurement от маяка
        if not isinstance(measurement, dict):
            logger.warning(f"⚠️ Invalid measurement type from anchor: {type(measurement)}")
            continue

        mac = measurement.get('mac')
        distance = measurement.get('distance')

        if mac and distance is not None:
            # Применяем фильтр Калмана к расстоянию
            filtered_distance = device_kalman_filters[mac].update(
                float(distance),
                measurement.get('packet_count', 1)
            )

            # Корректируем расстояние на основе частоты канала
            corrected_distance = apply_channel_correction(
                filtered_distance,
                measurement.get('channel', 1),
                measurement.get('rssi_filtered', measurement.get('rssi', -70))
            )

            # Сохраняем данные канала для анализа согласованности
            device_channel_data[mac].append({
                'channel': measurement.get('channel', 1),
                'timestamp': datetime.now().isoformat(),
                'anchor_id': anchor_id
            })

            # Рассчитываем согласованность канала
            channel_consistency = _calculate_channel_consistency(mac)

            # Рассчитываем уверенность в измерении
            distance_confidence = calculate_distance_confidence(
                measurement.get('rssi_filtered', measurement.get('rssi', -70)),
                measurement.get('packet_count', 1),
                channel_consistency
            )

            # Обновляем статистику пакетов
            if mac not in device_packet_stats:
                device_packet_stats[mac] = {
                    'count': 0,
                    'first_seen': datetime.now().isoformat()
                }
            device_packet_stats[mac]['count'] += 1

            # Сохраняем обогащенные данные
            enriched_measurement = {
                'anchor_id': anchor_id,
                'distance': corrected_distance,
                'distance_original': float(distance),
                'distance_filtered': filtered_distance,
                'rssi': measurement.get('rssi'),
                'rssi_filtered': measurement.get('rssi_filtered', measurement.get('rssi')),
                'channel': measurement.get('channel', 1),
                'packet_count': measurement.get('packet_count', 1),
                'distance_confidence': distance_confidence,
                'channel_consistency': channel_consistency,
                'timestamp': datetime.now().isoformat(),
                'device_timestamp': measurement.get('device_timestamp')
            }

            # ОГРАНИЧИВАЕМ КОЛИЧЕСТВО ИЗМЕРЕНИЙ (максимум 10)
            if len(anchor_data[mac]) >= 10:
                anchor_data[mac].pop(0)  # Удаляем самое старое измерение
            anchor_data[mac].append(enriched_measurement)

            if mac not in devices:
                devices[mac] = {
                    'mac': mac,
                    'first_seen': datetime.now().isoformat(),
                    'type': 'mobile_device',
                    'color': _generate_color_from_mac(mac),
                    'packet_count_total': 0,
                    'channels_used': [],
                    'avg_confidence': 0.0
                }
                logger.info(f"📱 New device detected: {mac}")

            # Обновляем статистику устройства
            devices[mac]['packet_count_total'] += 1
            channel = measurement.get('channel', 1)
            if channel not in devices[mac]['channels_used']:
                devices[mac]['channels_used'].append(channel)

            logger.debug(f"📏 Device {mac}: distance {corrected_distance:.2f}m "
                         f"(conf: {distance_confidence:.2f}, ch: {channel}, "
                         f"packets: {measurement.get('packet_count', 1)})")


def calculate_positions():
    try:
        logger.info(f"🎯 Starting position calculation for {len(anchor_data)} devices")
        logger.info(
            f"📊 Using anchors config: {len([k for k, v in anchors_config.items() if v.get('enabled', True)])} enabled anchors")

        calculated_positions = 0
        for mac, measurements_deque in anchor_data.items():
            # ПРЕОБРАЗУЕМ deque В LIST
            if isinstance(measurements_deque, deque):
                measurements_list = list(measurements_deque)
            else:
                measurements_list = measurements_deque

            if not isinstance(measurements_list, list):
                logger.warning(f"⚠️ Invalid measurements_list for {mac}: {type(measurements_list)}")
                continue

            if len(measurements_list) == 0:
                continue

            # Проверяем структуру первого измерения
            if not isinstance(measurements_list[0], dict):
                logger.warning(f"⚠️ Invalid measurement structure for {mac}: {type(measurements_list[0])}")
                continue

            if _calculate_device_position(mac, measurements_list):
                calculated_positions += 1

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


def _group_enhanced_measurements(measurements_list):
    """Группирует измерения по якорям с расширенными данными"""
    anchor_measurements = {}
    current_time = datetime.now()

    for measurement in measurements_list:
        # Проверяем структуру measurement
        if not isinstance(measurement, dict):
            logger.warning(f"⚠️ Invalid measurement type: {type(measurement)}")
            continue

        measure_time = datetime.fromisoformat(measurement['timestamp'])
        if (current_time - measure_time).total_seconds() <= 10:
            anchor_id = measurement['anchor_id']
            if anchor_id not in anchor_measurements:
                anchor_measurements[anchor_id] = []
            anchor_measurements[anchor_id].append(measurement)

    logger.debug(f"📊 Grouped measurements: {list(anchor_measurements.keys())}")
    return anchor_measurements


def _calculate_device_position(mac, measurements_list):
    try:
        logger.debug(f"🎯 Calculating position for {mac} with {len(measurements_list)} measurements")

        # Группируем измерения по якорям с расширенными данными
        anchor_measurements = _group_enhanced_measurements(measurements_list)

        if len(anchor_measurements) < 2:
            logger.debug(f"⚠️ Not enough anchors for {mac}: {len(anchor_measurements)}")
            return False

        # Передаем расчет позиции И уверенности движку трилатерации
        position = trilateration_engine.calculate_position(anchor_measurements)

        if position:
            # Берем confidence из результата движка
            confidence = position.get('confidence', 0.5)

            positions[mac] = {
                'position': position,  # position уже содержит confidence
                'timestamp': datetime.now().isoformat(),
                'confidence': confidence,
                'anchors_used': len(anchor_measurements),
                'avg_distance_confidence': np.mean(
                    [m[-1].get('distance_confidence', 0.5) for m in anchor_measurements.values() if m]),
                'type': devices[mac].get('type', 'unknown') if mac in devices else 'unknown'
            }

            statistics['position_updates'] += 1
            system_status['last_calculation'] = datetime.now().isoformat()
            _emit_position_update(mac, positions[mac])

            logger.info(
                f"📍 Position calculated for {mac}: ({position['x']:.2f}, {position['y']:.2f}, {position['z']:.2f}) "
                f"with confidence {confidence:.2f}")
            return True
        else:
            logger.debug(f"❌ Trilateration failed for {mac}")
            return False

    except Exception as e:
        logger.error(f"❌ Error calculating position for {mac}: {str(e)}")
        statistics['calculation_errors'] += 1
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

            # Отправка обновлений с обработкой ошибок сериализации
            try:
                socketio.emit('system_status', system_status)
                socketio.emit('statistics_update', statistics)
                socketio.emit('anchors_data', anchors)

                # Сериализуем devices правильно
                serializable_devices = {}
                for mac, device in devices.items():
                    serializable_devices[mac] = device.copy()
                    # Убеждаемся, что все данные сериализуемы
                    if 'channels_used' in serializable_devices[mac]:
                        serializable_devices[mac]['channels_used'] = list(serializable_devices[mac]['channels_used'])

                socketio.emit('devices_data', serializable_devices)
                socketio.emit('positions_data', positions)

            except Exception as e:
                logger.error(f"❌ Error emitting data: {e}")

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
    """Очищает старые измерения (теперь это делается автоматически при добавлении новых)"""
    # Теперь измерения автоматически ограничиваются до 10 последних
    # Удаляем устройства без измерений
    expired_devices = []
    for mac in list(anchor_data.keys()):
        if len(anchor_data[mac]) == 0:
            expired_devices.append(mac)

    for mac in expired_devices:
        if mac in devices:
            del devices[mac]
            if mac in anchor_data:
                del anchor_data[mac]
            if mac in device_kalman_filters:
                del device_kalman_filters[mac]
            if mac in device_channel_data:
                del device_channel_data[mac]
            if mac in device_packet_stats:
                del device_packet_stats[mac]
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