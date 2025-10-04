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
        'Якорь_1': {'x': 0, 'y': 0, 'z': 2.5},
        'Якорь_2': {'x': 20, 'y': 0, 'z': 2.5},
        'Якорь_3': {'x': 20, 'y': 15, 'z': 2.5},
        'Якорь_4': {'x': 0, 'y': 15, 'z': 1.0}
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


def normalize_mac(mac):
    """Нормализуем MAC-адрес, убирая randomized части"""
    if not mac:
        return mac

    # Приводим к верхнему регистру и убираем разделители
    mac_clean = mac.upper().replace(':', '').replace('-', '')

    # Для некоторых устройств можем игнорировать первый байт
    if len(mac_clean) == 12:
        # Оставляем только последние 6 символов (3 байта) для идентификации
        return mac_clean[6:]

    return mac_clean


@app.route('/api/anchor_data', methods=['POST'])
def receive_anchor_data():
    """Принимаем данные от якорей"""
    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': 'Не получены данные'}), 400

        anchor_id = data.get('anchor_id')
        measurements = data.get('measurements', [])

        print(f"📨 Данные от {anchor_id}: {len(measurements)} измерений")

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

                print(f"   📍 {anchor_id} -> {mac}: {distance}m (RSSI: {rssi})")

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

        # Показываем общую статистику (ИСПРАВЛЕННАЯ ЧАСТЬ)
        print(f"📊 Всего устройств в системе: {len(anchor_data)}")
        for mac, measurements_list in anchor_data.items():
            # Берем последние 10 измерений или все, если меньше 10
            recent_measurements = list(measurements_list)[-10:] if len(measurements_list) > 10 else list(
                measurements_list)
            anchors_seen = set(m['anchor_id'] for m in recent_measurements)
            print(f"   📱 {mac}: видели якоря {list(anchors_seen)}")

        # Запускаем расчет позиций
        calculate_positions()

        return jsonify({'status': 'success', 'message': 'Данные получены'})

    except Exception as e:
        logger.error(f"Ошибка обработки данных от якоря: {e}")
        statistics['calculation_errors'] += 1
        return jsonify({'error': str(e)}), 500


def calculate_positions():
    """Вычисляем позиции устройств с улучшенной обработкой"""
    try:
        print(f"\n🔍 === НАЧАЛО РАСЧЕТА ПОЗИЦИЙ ===")

        for mac, measurements_list in anchor_data.items():
            print(f"\n🔍 Обработка устройства {mac}, всего измерений: {len(measurements_list)}")

            # Группируем измерения по якорям
            anchor_measurements = {}
            current_time = datetime.now()

            for measurement in measurements_list:
                measure_time = datetime.fromisoformat(measurement['timestamp'])
                if (current_time - measure_time).total_seconds() <= 10:
                    anchor_id = measurement['anchor_id']
                    if anchor_id not in anchor_measurements:
                        anchor_measurements[anchor_id] = []
                    anchor_measurements[anchor_id].append(measurement['distance'])

            print(f"📊 Активные якоря для {mac}: {list(anchor_measurements.keys())}")

            # Если есть минимум 2 якоря - рассчитываем позицию
            if len(anchor_measurements) >= 2:
                avg_distances = {}
                for anchor_id, distances in anchor_measurements.items():
                    avg_distances[anchor_id] = sum(distances) / len(distances)

                print(f"🎯 Якорей для расчета {mac}: {len(avg_distances)}")
                position = trilateration_3d(avg_distances)

                # Если позиция рассчитана, но вне комнаты - корректируем
                if position and not is_valid_position(position, room_config):
                    print(f"🔄 Корректируем позицию для {mac}")
                    position = correct_position(position, room_config)

                if position:
                    confidence = calculate_confidence(avg_distances, position)

                    positions[mac] = {
                        'position': position,
                        'timestamp': datetime.now().isoformat(),
                        'confidence': confidence * 0.8 if len(avg_distances) == 2 else confidence,
                        # Понижаем уверенность для 2 якорей
                        'anchors_used': len(avg_distances),
                        'type': devices[mac]['type'] if mac in devices else 'unknown'
                    }

                    statistics['position_updates'] += 1
                    system_status['last_calculation'] = datetime.now().isoformat()

                    socketio.emit('position_update', {
                        'device_id': mac,
                        'position': position,
                        'timestamp': positions[mac]['timestamp'],
                        'confidence': positions[mac]['confidence'],
                        'anchors_used': positions[mac]['anchors_used']
                    })

                    emit_log(f"Позиция для {mac}: ({position['x']:.1f}, {position['y']:.1f}, {position['z']:.1f})",
                             'success')
                else:
                    print(f"❌ Не удалось рассчитать позицию для {mac}")

            else:
                print(f"❌ Недостаточно якорей для {mac}: {len(anchor_measurements)}")

        statistics['devices_detected'] = len(devices)
        print(f"📈 Статистика: {statistics['position_updates']} обновлений позиций")

    except Exception as e:
        logger.error(f"Ошибка расчета позиций: {e}")
        statistics['calculation_errors'] += 1


def correct_position(position, room_config):
    """Корректируем позицию чтобы она была внутри комнаты"""
    x = max(0.5, min(room_config['width'] - 0.5, position['x']))
    y = max(0.5, min(room_config['height'] - 0.5, position['y']))
    z = max(0.5, min(3.0, position['z']))

    corrected = {'x': x, 'y': y, 'z': z}
    print(f"   📍 Скорректированная позиция: {corrected}")
    return corrected


def trilateration_3d(anchor_distances):
    """3D трилатерация с умным fallback на 2D"""
    try:
        print(f"🎯 Начало 3D трилатерации для {len(anchor_distances)} якорей")

        # Собираем координаты якорей и расстояния
        anchors_list = []
        distances_list = []

        for anchor_id, distance in anchor_distances.items():
            if anchor_id in room_config['anchors']:
                anchor = room_config['anchors'][anchor_id]
                anchors_list.append([anchor['x'], anchor['y'], anchor['z']])
                distances_list.append(distance)
                print(f"📍 Якорь {anchor_id}: ({anchor['x']}, {anchor['y']}, {anchor['z']}) -> {distance}m")

        if len(anchors_list) < 3:
            print("❌ Недостаточно якорей для трилатерации")
            return None

        # Проверяем, есть ли разница в Z-координатах для настоящей 3D
        z_coords = [anchor[2] for anchor in anchors_list]
        z_variation = max(z_coords) - min(z_coords)

        if z_variation < 0.5:  # Если высоты почти одинаковые
            print(f"⚠️  Малая вариация высот ({z_variation:.2f}m), используем 2D+ трилатерацию")
            return trilateration_2d_plus(anchor_distances)

        # Продолжаем с 3D трилатерацией...
        # ... ваш существующий код 3D трилатерации ...

    except Exception as e:
        print(f"❌ Ошибка 3D трилатерации: {e}")
        return trilateration_2d_plus(anchor_distances)


def trilateration_2d_plus(anchor_distances):
    """2D трилатерация с разумной оценкой Z-координаты"""
    try:
        print("🔄 Используем 2D+ трилатерацию с оценкой высоты")

        # Собираем координаты якорей и расстояния (игнорируем Z для расчета X,Y)
        anchors_list = []
        distances_list = []
        z_coords = []

        for anchor_id, distance in anchor_distances.items():
            if anchor_id in room_config['anchors']:
                anchor = room_config['anchors'][anchor_id]
                anchors_list.append([anchor['x'], anchor['y']])  # Только X, Y для 2D
                distances_list.append(distance)
                z_coords.append(anchor['z'])

        if len(anchors_list) < 3:
            return None

        # 2D трилатерация для X,Y
        A = []
        b = []

        for i in range(1, len(anchors_list)):
            xi, yi = anchors_list[i]
            x0, y0 = anchors_list[0]
            di = distances_list[i]
            d0 = distances_list[0]

            A_i = [2 * (xi - x0), 2 * (yi - y0)]
            b_i = (di ** 2 - d0 ** 2 - xi ** 2 + x0 ** 2 - yi ** 2 + y0 ** 2)

            A.append(A_i)
            b.append(b_i)

        A = np.array(A)
        b = np.array(b)

        if np.linalg.matrix_rank(A) < 2:
            print("❌ 2D матрица также вырождена, используем геометрический метод")
            return simple_geometric_method_3d(anchor_distances)

        position_2d = np.linalg.lstsq(A, b, rcond=None)[0]

        # Проверяем на NaN
        if np.any(np.isnan(position_2d)):
            return simple_geometric_method_3d(anchor_distances)

        # ОЦЕНИВАЕМ Z-координату разумным способом
        z_coordinate = estimate_smart_z_coordinate(position_2d[0], position_2d[1], anchor_distances)

        result = {
            'x': float(position_2d[0]),
            'y': float(position_2d[1]),
            'z': float(z_coordinate)  # Теперь это разумная оценка, а не 0!
        }

        print(f"✅ Успешная 2D+ трилатерация: {result}")
        return result

    except Exception as e:
        print(f"❌ Ошибка 2D+ трилатерации: {e}")
        return simple_geometric_method_3d(anchor_distances)


def estimate_smart_z_coordinate(x, y, anchor_distances):
    """Умная оценка Z-координаты на основе контекста"""
    try:
        # Собираем информацию о якорях
        anchors_info = []
        for anchor_id, distance in anchor_distances.items():
            if anchor_id in room_config['anchors']:
                anchor = room_config['anchors'][anchor_id]
                anchors_info.append({
                    'z': anchor['z'],
                    'distance': distance,
                    'x': anchor['x'],
                    'y': anchor['y']
                })

        # Метод 1: Средневзвешенная высота по расстояниям
        total_weight = 0
        z_weighted = 0

        for anchor in anchors_info:
            # Ближайшие якоря имеют больший вес в определении высоты
            weight = 1.0 / (anchor['distance'] + 0.1)
            z_weighted += anchor['z'] * weight
            total_weight += weight

        avg_z = z_weighted / total_weight if total_weight > 0 else 1.5

        # Метод 2: Учитываем позицию в комнате
        room_height = 3.0  # Предполагаемая высота комнаты

        # Если устройство близко к стенам - вероятно на полу или низко
        close_to_wall = (x < 2.0 or x > 18.0 or y < 2.0 or y > 13.0)

        # Если устройство в центре комнаты - вероятно на уровне человека
        in_center = (5.0 < x < 15.0 and 5.0 < y < 10.0)

        # Корректируем оценку based на позиции
        if close_to_wall:
            # У стен - вероятно на полу или низко расположенные объекты
            z_estimate = max(0.3, avg_z * 0.7)
        elif in_center:
            # В центре - вероятно человек (1.2-1.8м)
            z_estimate = min(room_height * 0.6, max(1.0, avg_z))
        else:
            # В остальных случаях - среднее значение
            z_estimate = avg_z

        # Ограничиваем разумными пределами
        z_estimate = max(0.3, min(room_height - 0.5, z_estimate))

        print(f"   📊 Умная оценка Z: {z_estimate:.2f}m (среднее: {avg_z:.2f}m)")
        return z_estimate

    except Exception as e:
        print(f"   ⚠️  Ошибка оценки Z, используем значение по умолчанию: {e}")
        return 1.5  # Рост человека по умолчанию


def simple_geometric_method_3d(anchor_distances):
    """Упрощенный геометрический метод с разумной Z-координатой"""
    try:
        print("🔄 Используем упрощенный 3D геометрический метод")

        anchor_ids = list(anchor_distances.keys())
        anchors = []
        distances = []

        for anchor_id in anchor_ids:
            if anchor_id in room_config['anchors']:
                anchor = room_config['anchors'][anchor_id]
                anchors.append(anchor)
                distances.append(anchor_distances[anchor_id])

        if len(anchors) < 2:
            return None

        # Метод взвешенного центра в 3D
        total_weight = 0
        x_sum = 0
        y_sum = 0
        z_sum = 0

        for i, anchor in enumerate(anchors):
            # Вес обратно пропорционален расстоянию
            weight = 1.0 / (distances[i] + 0.1)
            x_sum += anchor['x'] * weight
            y_sum += anchor['y'] * weight
            z_sum += anchor['z'] * weight
            total_weight += weight

        if total_weight > 0:
            x = x_sum / total_weight
            y = y_sum / total_weight
            z = z_sum / total_weight

            # Корректируем Z на основе логики
            z = estimate_smart_z_coordinate(x, y, anchor_distances)

            # Ограничиваем координаты комнатой
            x = max(0.5, min(room_config['width'] - 0.5, x))
            y = max(0.5, min(room_config['height'] - 0.5, y))
            z = max(0.5, min(3.0, z))

            result = {'x': x, 'y': y, 'z': z}
            print(f"✅ Упрощенный 3D метод: {result}")
            return result

        return None

    except Exception as e:
        print(f"❌ Ошибка упрощенного 3D метода: {e}")
        # Всегда возвращаем валидную позицию с разумной Z
        return {'x': 10.0, 'y': 7.5, 'z': 1.5}  # Центр комнаты, уровень человека


def is_valid_position(position, room_config):
    """Проверяем, что позиция находится в пределах комнаты в 3D"""
    x, y, z = position['x'], position['y'], position['z']
    valid = (0 <= x <= room_config['width'] and
             0 <= y <= room_config['height'] and
             0 <= z <= 4.0)  # Максимальная высота 4 метра

    if not valid:
        print(f"⚠️  Позиция вне комнаты: ({x:.2f}, {y:.2f}, {z:.2f})")

    return valid


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