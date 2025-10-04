from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import time
import threading
from datetime import datetime
import math
import numpy as np
from collections import defaultdict, deque
import logging

app = Flask(__name__)
app.config['SECRET_KEY'] = 'indoor_positioning_secret'

socketio = SocketIO(app,
                    cors_allowed_origins="*",
                    async_mode='threading',
                    logger=False,
                    engineio_logger=False)

# Хранилище данных системы
anchors = {}  # Данные от якорей
devices = {}  # Обнаруженные устройства
positions = {}  # Рассчитанные позиции
anchor_data = defaultdict(lambda: deque(maxlen=10))  # Последние данные от якорей

system_status = {
    'is_running': True,
    'start_time': datetime.now().isoformat(),
    'total_updates': 0,
    'last_calculation': None
}

# Конфигурация помещения и якорей
room_config = {
    'width': 20,
    'height': 15,
    'anchors': {
        'Якорь_1': {'x': 0, 'y': 0, 'z': 2.5, 'ip': '192.168.4.1'},
        'Якорь_2': {'x': 20, 'y': 0, 'z': 2.5, 'ip': '192.168.4.1'},
        'Якорь_3': {'x': 20, 'y': 15, 'z': 2.5, 'ip': '192.168.4.1'},
        'Якорь_4': {'x': 0, 'y': 15, 'z': 2.5, 'ip': '192.168.4.1'}
    }
}

# Статистика системы
statistics = {
    'connections': 0,
    'position_updates': 0,
    'anchor_updates': 0,
    'devices_detected': 0,
    'calculation_errors': 0
}

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@app.route('/')
def index():
    return render_template('index.html', room_config=room_config)


@app.route('/api/status')
def api_status():
    return jsonify({
        'system': system_status,
        'statistics': statistics,
        'anchors_count': len(anchors),
        'devices_count': len(devices),
        'positions_count': len(positions),
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/anchors')
def get_anchors():
    return jsonify(anchors)


@app.route('/api/devices')
def get_devices():
    return jsonify(devices)


@app.route('/api/positions')
def get_positions():
    return jsonify(positions)


@app.route('/api/anchor_data', methods=['POST'])
def receive_anchor_data():
    """Принимаем данные от якорей"""
    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': 'Не получены данные'}), 400

        anchor_id = data.get('anchor_id')
        measurements = data.get('measurements', [])

        if not anchor_id:
            return jsonify({'error': 'Отсутствует anchor_id'}), 400

        # Обновляем информацию о якоре
        anchors[anchor_id] = {
            'x': data.get('x', 0),
            'y': data.get('y', 0),
            'z': data.get('z', 2.5),
            'last_update': datetime.now().isoformat(),
            'status': 'active'
        }

        # Сохраняем измерения
        for measurement in measurements:
            mac = measurement.get('mac')
            distance = measurement.get('distance')
            rssi = measurement.get('rssi')

            if mac and distance is not None:
                # Сохраняем данные для трилатерации
                anchor_data[mac].append({
                    'anchor_id': anchor_id,
                    'distance': float(distance),
                    'rssi': rssi,
                    'timestamp': datetime.now().isoformat()
                })

                # Обновляем информацию об устройстве
                if mac not in devices:
                    devices[mac] = {
                        'mac': mac,
                        'first_seen': datetime.now().isoformat(),
                        'type': 'mobile_device',
                        'color': generate_color_from_mac(mac)
                    }

        statistics['anchor_updates'] += 1
        system_status['total_updates'] += 1

        # Запускаем расчет позиций
        calculate_positions()

        # Отправляем обновления через WebSocket
        socketio.emit('anchor_update', {
            'anchor_id': anchor_id,
            'measurements': measurements
        })

        emit_log(f'Данные получены от {anchor_id}', 'success')

        return jsonify({'status': 'success', 'message': 'Данные получены'})

    except Exception as e:
        logger.error(f"Ошибка обработки данных от якоря: {e}")
        statistics['calculation_errors'] += 1
        return jsonify({'error': str(e)}), 500


def calculate_positions():
    """Вычисляем позиции устройств методом трилатерации"""
    try:
        for mac, measurements_list in anchor_data.items():
            if len(measurements_list) < 3:  # Нужно минимум 3 якоря
                continue

            # Группируем измерения по времени (последние 5 секунд)
            recent_measurements = []
            current_time = datetime.now()

            for measurement in list(measurements_list):
                measure_time = datetime.fromisoformat(measurement['timestamp'])
                if (current_time - measure_time).total_seconds() <= 5:
                    recent_measurements.append(measurement)

            if len(recent_measurements) < 3:
                continue

            # Подготавливаем данные для трилатерации
            anchor_distances = {}
            for measurement in recent_measurements:
                anchor_id = measurement['anchor_id']
                distance = measurement['distance']

                # Используем среднее значение, если несколько измерений от одного якоря
                if anchor_id in anchor_distances:
                    anchor_distances[anchor_id].append(distance)
                else:
                    anchor_distances[anchor_id] = [distance]

            # Усредняем расстояния для каждого якоря
            avg_distances = {}
            for anchor_id, distances in anchor_distances.items():
                avg_distances[anchor_id] = sum(distances) / len(distances)

            if len(avg_distances) >= 3:
                position = trilateration_3d(avg_distances)

                if position and is_valid_position(position, room_config):
                    positions[mac] = {
                        'position': position,
                        'timestamp': datetime.now().isoformat(),
                        'confidence': calculate_confidence(avg_distances, position),
                        'anchors_used': len(avg_distances),
                        'type': devices[mac]['type'] if mac in devices else 'unknown'
                    }

                    statistics['position_updates'] += 1
                    system_status['last_calculation'] = datetime.now().isoformat()

                    # Отправляем обновление позиции
                    socketio.emit('position_update', {
                        'device_id': mac,
                        'position': position,
                        'timestamp': positions[mac]['timestamp'],
                        'confidence': positions[mac]['confidence'],
                        'anchors_used': positions[mac]['anchors_used']
                    })

        statistics['devices_detected'] = len(devices)

    except Exception as e:
        logger.error(f"Ошибка расчета позиций: {e}")
        statistics['calculation_errors'] += 1


def trilateration_3d(anchor_distances):
    """3D трилатерация методом наименьших квадратов"""
    try:
        if len(anchor_distances) < 3:
            return None

        # Собираем координаты якорей и расстояния
        anchors_list = []
        distances_list = []

        for anchor_id, distance in anchor_distances.items():
            if anchor_id in room_config['anchors']:
                anchor = room_config['anchors'][anchor_id]
                anchors_list.append([anchor['x'], anchor['y'], anchor['z']])
                distances_list.append(distance)

        if len(anchors_list) < 3:
            return None

        # Преобразуем в numpy массивы
        A = np.array(anchors_list)
        d = np.array(distances_list)

        # Метод наименьших квадратов для решения системы уравнений
        # (x - xi)^2 + (y - yi)^2 + (z - zi)^2 = di^2

        # Вычитаем первое уравнение из остальных чтобы линеаризовать
        A = A[1:] - A[0]
        b = []

        for i in range(1, len(anchors_list)):
            b.append(d[i] ** 2 - d[0] ** 2 -
                     np.linalg.norm(anchors_list[i]) ** 2 +
                     np.linalg.norm(anchors_list[0]) ** 2)

        b = np.array(b) / 2

        # Решаем систему
        if np.linalg.matrix_rank(A) < 3:
            return None

        position = np.linalg.lstsq(A, b, rcond=None)[0]

        # Проверяем на NaN
        if np.any(np.isnan(position)):
            return None

        return {
            'x': float(position[0]),
            'y': float(position[1]),
            'z': float(position[2]) if len(position) > 2 else 0.0
        }

    except Exception as e:
        logger.error(f"Ошибка трилатерации: {e}")
        return None


def is_valid_position(position, room_config):
    """Проверяем, что позиция находится в пределах комнаты"""
    x, y, z = position['x'], position['y'], position['z']
    return (0 <= x <= room_config['width'] and
            0 <= y <= room_config['height'] and
            0 <= z <= 3)  # Максимальная высота 3 метра


def calculate_confidence(distances, position):
    """Вычисляем уверенность в расчете позиции"""
    try:
        # На основе согласованности расстояний
        variance = np.var(list(distances.values()))
        confidence = max(0.1, 1.0 - variance / 10.0)  # Нормализуем

        # Учитываем количество якорей
        anchor_count = len(distances)
        confidence *= min(1.0, anchor_count / 4.0)

        return round(confidence, 2)
    except:
        return 0.5


def generate_color_from_mac(mac):
    """Генерируем цвет на основе MAC-адреса"""
    import hashlib
    hash_obj = hashlib.md5(mac.encode())
    hash_hex = hash_obj.hexdigest()[:6]
    return f'#{hash_hex}'


# WebSocket обработчики
@socketio.on('connect')
def handle_connect():
    statistics['connections'] += 1
    emit('system_status', system_status)
    emit('anchors_data', anchors)
    emit('devices_data', devices)
    emit('positions_data', positions)
    emit('statistics_update', statistics)
    emit_log('Новый клиент подключился', 'info')


@socketio.on('disconnect')
def handle_disconnect():
    statistics['connections'] = max(0, statistics['connections'] - 1)
    emit_log('Клиент отключился', 'warning')


@socketio.on('reset_system')
def handle_reset_system():
    anchors.clear()
    devices.clear()
    positions.clear()
    anchor_data.clear()
    statistics.update({
        'position_updates': 0,
        'anchor_updates': 0,
        'devices_detected': 0,
        'calculation_errors': 0
    })
    socketio.emit('system_reset')
    emit_log('Система сброшена', 'info')


def emit_log(message, log_type='info'):
    log_data = {
        'message': message,
        'type': log_type,
        'timestamp': datetime.now().isoformat()
    }
    socketio.emit('log_message', log_data)
    logger.info(f"[{log_type.upper()}] {message}")


# Фоновая задача для обслуживания данных
def background_task():
    """Фоновая задача для очистки старых данных"""
    while True:
        try:
            current_time = datetime.now()

            # Очищаем старые позиции (больше 10 секунд)
            expired_positions = []
            for mac, pos_data in positions.items():
                pos_time = datetime.fromisoformat(pos_data['timestamp'])
                if (current_time - pos_time).total_seconds() > 10:
                    expired_positions.append(mac)

            for mac in expired_positions:
                del positions[mac]

            # Очищаем старые измерения
            for mac in list(anchor_data.keys()):
                anchor_data[mac] = deque(
                    [m for m in anchor_data[mac]
                     if (current_time - datetime.fromisoformat(m['timestamp'])).total_seconds() <= 10],
                    maxlen=10
                )

            # Периодически отправляем обновления статистики
            socketio.emit('system_status', system_status)
            socketio.emit('statistics_update', statistics)

        except Exception as e:
            logger.error(f"Ошибка фоновой задачи: {e}")

        time.sleep(2)


if __name__ == '__main__':
    print("🚀 Запуск системы позиционирования в помещении...")
    print("📡 Ожидание данных от ESP32 якорей...")
    print("📍 Веб-интерфейс: http://localhost:5000")

    # Запускаем фоновую задачу
    bg_thread = threading.Thread(target=background_task, daemon=True)
    bg_thread.start()

    socketio.run(app,
                 host='0.0.0.0',
                 port=5000,
                 debug=False,
                 use_reloader=False,
                 allow_unsafe_werkzeug=True)