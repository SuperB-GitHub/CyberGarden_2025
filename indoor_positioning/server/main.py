"""
Indoor Positioning System - Main Server Module

Этот модуль реализует серверную часть системы позиционирования в помещении.
Обрабатывает данные от ESP32 якорей, вычисляет позиции устройств и предоставляет
веб-интерфейс для визуализации в реальном времени.
"""

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import time
import threading
from datetime import datetime
from collections import defaultdict, deque
import logging

from trilateration import TrilaterationEngine, calculate_confidence

# Инициализация Flask приложения и SocketIO
app = Flask(__name__)
app.config['SECRET_KEY'] = 'indoor_positioning_secret'

socketio = SocketIO(app,
                    cors_allowed_origins="*",
                    async_mode='threading',
                    logger=False,
                    engineio_logger=False)

# Хранилища данных системы
anchors = {}  # Данные от якорей {anchor_id: anchor_data}
devices = {}  # Обнаруженные устройства {mac: device_info}
positions = {}  # Рассчитанные позиции {mac: position_data}
anchor_data = defaultdict(lambda: deque(maxlen=10))  # Последние измерения от якорей

# Статус системы
system_status = {
    'is_running': True,
    'start_time': datetime.now().isoformat(),
    'total_updates': 0,
    'last_calculation': None
}

# Конфигурация помещения и расположения якорей
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

# Инициализация движка трилатерации
trilateration_engine = TrilaterationEngine(room_config)

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
def index() -> str:
    """Главная страница - отображение веб-интерфейса позиционирования."""
    return render_template('index.html', room_config=room_config)


@app.route('/api/status')
def api_status() -> jsonify:
    """API endpoint для получения статуса системы и статистики."""
    return jsonify({
        'system': system_status,
        'statistics': statistics,
        'anchors_count': len(anchors),
        'devices_count': len(devices),
        'positions_count': len(positions),
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/anchors')
def get_anchors() -> jsonify:
    """API endpoint для получения списка активных якорей."""
    return jsonify(anchors)


@app.route('/api/devices')
def get_devices() -> jsonify:
    """API endpoint для получения списка обнаруженных устройств."""
    return jsonify(devices)


@app.route('/api/positions')
def get_positions() -> jsonify:
    """API endpoint для получения рассчитанных позиций устройств."""
    return jsonify(positions)


def normalize_mac(mac: str) -> str:
    """
    Нормализует MAC-адрес, убирая randomized части.

    Args:
        mac: Исходный MAC-адрес

    Returns:
        Нормализованный MAC-адрес (последние 6 символов для randomized MAC)
    """
    if not mac:
        return mac

    mac_clean = mac.upper().replace(':', '').replace('-', '')

    # Для randomized MAC оставляем только последние 6 символов
    if len(mac_clean) == 12:
        return mac_clean[6:]

    return mac_clean


@app.route('/api/anchor_data', methods=['POST'])
def receive_anchor_data() -> tuple[jsonify, int]:
    """
    Принимает и обрабатывает данные измерений от ESP32 якорей.

    Args:
        JSON данные от якоря содержащие измерения RSSI

    Returns:
        JSON ответ с статусом обработки
    """
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

        # Обрабатываем измерения от якоря
        _process_anchor_measurements(anchor_id, measurements)

        statistics['anchor_updates'] += 1
        system_status['total_updates'] += 1

        # Показываем статистику по устройствам
        _print_devices_statistics()

        # Запускаем расчет позиций
        calculate_positions()

        return jsonify({'status': 'success', 'message': 'Данные получены'})

    except Exception as e:
        logger.error(f"Ошибка обработки данных от якоря: {e}")
        statistics['calculation_errors'] += 1
        return jsonify({'error': str(e)}), 500


def _process_anchor_measurements(anchor_id: str, measurements: list) -> None:
    """
    Обрабатывает измерения от конкретного якоря.

    Args:
        anchor_id: Идентификатор якоря
        measurements: Список измерений RSSI
    """
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

            # Создаем запись об устройстве если его еще нет
            if mac not in devices:
                devices[mac] = {
                    'mac': mac,
                    'first_seen': datetime.now().isoformat(),
                    'type': 'mobile_device',
                    'color': _generate_color_from_mac(mac)
                }


def _print_devices_statistics() -> None:
    """Выводит статистику по обнаруженным устройствам."""
    print(f"📊 Всего устройств в системе: {len(anchor_data)}")
    for mac, measurements_list in anchor_data.items():
        recent_measurements = list(measurements_list)[-10:] if len(measurements_list) > 10 else list(measurements_list)
        anchors_seen = set(m['anchor_id'] for m in recent_measurements)
        print(f"   📱 {mac}: видели якоря {list(anchors_seen)}")


def calculate_positions() -> None:
    """
    Вычисляет позиции всех устройств на основе полученных измерений.

    Использует модуль трилатерации для расчета координат. Для каждого устройства
    требуется минимум 2 якоря с актуальными измерениями.
    """
    try:
        print(f"\n🔍 === НАЧАЛО РАСЧЕТА ПОЗИЦИЙ ===")

        for mac, measurements_list in anchor_data.items():
            print(f"\n🔍 Обработка устройства {mac}, всего измерений: {len(measurements_list)}")

            # Группируем измерения по якорям за последние 10 секунд
            anchor_measurements = _group_recent_measurements(measurements_list)

            print(f"📊 Активные якоря для {mac}: {list(anchor_measurements.keys())}")

            # Рассчитываем позицию если есть достаточно якорей
            if len(anchor_measurements) >= 2:
                _calculate_device_position(mac, anchor_measurements)
            else:
                print(f"❌ Недостаточно якорей для {mac}: {len(anchor_measurements)}")

        statistics['devices_detected'] = len(devices)
        print(f"📈 Статистика: {statistics['position_updates']} обновлений позиций")

    except Exception as e:
        logger.error(f"Ошибка расчета позиций: {e}")
        statistics['calculation_errors'] += 1


def _group_recent_measurements(measurements_list: list) -> dict:
    """
    Группирует измерения по якорям за последние 10 секунд.

    Args:
        measurements_list: Список всех измерений для устройства

    Returns:
        Словарь {anchor_id: [distances]} с актуальными измерениями
    """
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


def _calculate_device_position(mac: str, anchor_measurements: dict) -> None:
    """
    Вычисляет позицию конкретного устройства и отправляет обновление.

    Args:
        mac: MAC-адрес устройства
        anchor_measurements: Измерения от якорей для этого устройства
    """
    # Вычисляем средние расстояния до каждого якоря
    avg_distances = {}
    for anchor_id, distances in anchor_measurements.items():
        avg_distances[anchor_id] = sum(distances) / len(distances)

    print(f"🎯 Якорей для расчета {mac}: {len(avg_distances)}")

    # Используем модуль трилатерации для расчета позиции
    position = trilateration_engine.calculate_position(avg_distances)

    if position:
        confidence = calculate_confidence(avg_distances, position)

        # Сохраняем позицию
        positions[mac] = {
            'position': position,
            'timestamp': datetime.now().isoformat(),
            'confidence': confidence * 0.8 if len(avg_distances) == 2 else confidence,
            'anchors_used': len(avg_distances),
            'type': devices[mac]['type'] if mac in devices else 'unknown'
        }

        statistics['position_updates'] += 1
        system_status['last_calculation'] = datetime.now().isoformat()

        # Отправляем обновление через WebSocket
        _emit_position_update(mac, positions[mac])

        emit_log(f"Позиция для {mac}: ({position['x']:.1f}, {position['y']:.1f}, {position['z']:.1f})", 'success')
    else:
        print(f"❌ Не удалось рассчитать позицию для {mac}")


def _emit_position_update(mac: str, position_data: dict) -> None:
    """
    Отправляет обновление позиции через WebSocket.

    Args:
        mac: MAC-адрес устройства
        position_data: Данные позиции устройства
    """
    socketio.emit('position_update', {
        'device_id': mac,
        'position': position_data['position'],
        'timestamp': position_data['timestamp'],
        'confidence': position_data['confidence'],
        'anchors_used': position_data['anchors_used']
    })


def _generate_color_from_mac(mac: str) -> str:
    """
    Генерирует уникальный цвет на основе MAC-адреса.

    Args:
        mac: MAC-адрес устройства

    Returns:
        HEX код цвета в формате #RRGGBB
    """
    import hashlib
    hash_obj = hashlib.md5(mac.encode())
    hash_hex = hash_obj.hexdigest()[:6]
    return f'#{hash_hex}'


# WebSocket обработчики
@socketio.on('connect')
def handle_connect() -> None:
    """Обрабатывает подключение нового WebSocket клиента."""
    statistics['connections'] += 1
    emit('system_status', system_status)
    emit('anchors_data', anchors)
    emit('devices_data', devices)
    emit('positions_data', positions)
    emit('statistics_update', statistics)
    emit_log('Новый клиент подключился', 'info')


@socketio.on('disconnect')
def handle_disconnect() -> None:
    """Обрабатывает отключение WebSocket клиента."""
    statistics['connections'] = max(0, statistics['connections'] - 1)
    emit_log('Клиент отключился', 'warning')


@socketio.on('reset_system')
def handle_reset_system() -> None:
    """Сбрасывает систему, очищая все данные и статистику."""
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


def emit_log(message: str, log_type: str = 'info') -> None:
    """
    Отправляет сообщение в системный лог через WebSocket.

    Args:
        message: Текст сообщения
        log_type: Тип сообщения (info, warning, error, success)
    """
    log_data = {
        'message': message,
        'type': log_type,
        'timestamp': datetime.now().isoformat()
    }
    socketio.emit('log_message', log_data)
    logger.info(f"[{log_type.upper()}] {message}")


def background_task() -> None:
    """
    Фоновая задача для обслуживания данных системы.

    Выполняет:
    - Очистку устаревших позиций (>10 секунд)
    - Очистку старых измерений
    - Периодическую отправку статистики
    """
    while True:
        try:
            current_time = datetime.now()

            # Очищаем устаревшие позиции
            _cleanup_old_positions(current_time)

            # Очищаем старые измерения
            _cleanup_old_measurements(current_time)

            # Отправляем обновления статистики
            socketio.emit('system_status', system_status)
            socketio.emit('statistics_update', statistics)

        except Exception as e:
            logger.error(f"Ошибка фоновой задачи: {e}")

        time.sleep(2)


def _cleanup_old_positions(current_time: datetime) -> None:
    """Очищает позиции старше 10 секунд."""
    expired_positions = []
    for mac, pos_data in positions.items():
        pos_time = datetime.fromisoformat(pos_data['timestamp'])
        if (current_time - pos_time).total_seconds() > 10:
            expired_positions.append(mac)

    for mac in expired_positions:
        del positions[mac]


def _cleanup_old_measurements(current_time: datetime) -> None:
    """Очищает измерения старше 10 секунд."""
    for mac in list(anchor_data.keys()):
        anchor_data[mac] = deque(
            [m for m in anchor_data[mac]
             if (current_time - datetime.fromisoformat(m['timestamp'])).total_seconds() <= 10],
            maxlen=10
        )


if __name__ == '__main__':
    """Точка входа для запуска сервера позиционирования."""
    print("🚀 Запуск системы позиционирования в помещении...")
    print("📡 Ожидание данных от ESP32 якорей...")
    print("📍 Веб-интерфейс: http://localhost:5000")

    # Запускаем фоновую задачу
    bg_thread = threading.Thread(target=background_task, daemon=True)
    bg_thread.start()

    # Запускаем Flask сервер
    socketio.run(app,
                 host='0.0.0.0',
                 port=5000,
                 debug=False,
                 use_reloader=False,
                 allow_unsafe_werkzeug=True)
