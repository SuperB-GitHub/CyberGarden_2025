from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import json
import time
import threading
from datetime import datetime
import random
import math

app = Flask(__name__)
app.config['SECRET_KEY'] = 'indoor_nav_secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Хранилище данных системы
anchors = {}
clients = {}
positions = {}
system_status = {
    'is_running': True,
    'start_time': datetime.now().isoformat(),
    'update_interval': 100,
    'cycle_count': 0,
    'total_updates': 0
}

# Конфигурация помещения
room_config = {
    'width': 20,
    'height': 15,
    'anchors': {
        'Anchor_1': {'x': 0, 'y': 0, 'z': 2.5},
        'Anchor_2': {'x': 20, 'y': 0, 'z': 2.5},
        'Anchor_3': {'x': 20, 'y': 15, 'z': 2.5},
        'Anchor_4': {'x': 0, 'y': 15, 'z': 2.5}
    }
}

# Статистика системы
statistics = {
    'connections': 0,
    'position_updates': 0,
    'errors': 0
}

# Глобальные переменные для управления симуляцией
simulation_running = False
simulation_thread = None
simulation_lock = threading.Lock()


@app.route('/')
def index():
    return render_template('index.html', room_config=room_config)


@app.route('/api/status')
def api_status():
    return jsonify({
        'system': system_status,
        'statistics': statistics,
        'anchors_count': len(anchors),
        'clients_count': len(clients),
        'positions_count': len(positions),
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/anchors')
def get_anchors():
    return jsonify(anchors)


@app.route('/api/clients')
def get_clients():
    return jsonify(clients)


@app.route('/api/positions')
def get_positions():
    return jsonify(positions)


@app.route('/api/control', methods=['POST'])
def control_system():
    data = request.get_json()
    command = data.get('command')

    if command == 'reset':
        with simulation_lock:
            clients.clear()
            positions.clear()
        statistics['position_updates'] = 0
        socketio.emit('system_reset')
        emit_log('System has been completely reset', 'info')
        return jsonify({'status': 'system_reset'})

    return jsonify({'error': 'unknown_command'})


# WebSocket обработчики
@socketio.on('connect')
def handle_connect():
    statistics['connections'] += 1
    client_ip = request.remote_addr
    print(f'📡 Client connected: {request.sid} from {client_ip}')

    # Отправляем текущее состояние новому клиенту
    emit('system_status', system_status)
    emit('anchors_data', anchors)
    emit('clients_data', clients)
    emit('positions_data', positions)
    emit('statistics_update', statistics)

    emit_log(f'New client connected from {client_ip}', 'info')


@socketio.on('disconnect')
def handle_disconnect():
    statistics['connections'] = max(0, statistics['connections'] - 1)
    print(f'📡 Client disconnected: {request.sid}')

    emit_log('Client disconnected', 'warning')


@socketio.on('start_simulation')
def handle_start_simulation(data=None):
    """Запуск автоматической симуляции"""
    global simulation_running, simulation_thread

    with simulation_lock:
        if simulation_running:
            emit_log('Simulation is already running', 'warning')
            return {'status': 'already_running'}

        simulation_running = True

    print("🚀 Starting automatic simulation")

    # Регистрируем маяки если их нет
    for anchor_id, coords in room_config['anchors'].items():
        if anchor_id not in anchors:
            anchors[anchor_id] = {
                'coordinates': coords,
                'status': 'active',
                'registered_at': datetime.now().isoformat()
            }

    socketio.emit('anchors_data', anchors)

    # Создаем начальных клиентов
    add_client('Robot_1', 'robot')
    add_client('Operator_Ivan', 'human')

    # Запускаем поток симуляции
    simulation_thread = threading.Thread(target=simulation_worker, daemon=True)
    simulation_thread.start()

    emit_log('Simulation started with Robot_1 and Operator_Ivan', 'success')
    return {'status': 'started'}


@socketio.on('stop_simulation')
def handle_stop_simulation(data=None):
    """Остановка автоматической симуляции"""
    global simulation_running

    with simulation_lock:
        simulation_running = False

    print("🛑 Stopping automatic simulation")
    emit_log('Simulation stopped - all movement frozen', 'info')
    return {'status': 'stopped'}


@socketio.on('add_robot')
def handle_add_robot(data=None):
    """Добавление нового робота"""
    robot_id = f'Robot_{len(clients) + 1}'
    add_client(robot_id, 'robot')

    emit_log(f'Robot {robot_id} added to system', 'success')
    return {'status': 'added', 'device_id': robot_id}


@socketio.on('add_human')
def handle_add_human(data=None):
    """Добавление нового человека"""
    human_id = f'Operator_{len(clients) + 1}'
    add_client(human_id, 'human')

    emit_log(f'Human {human_id} added to system', 'success')
    return {'status': 'added', 'device_id': human_id}


@socketio.on('remove_client')
def handle_remove_client(data):
    """Удаление клиента из системы"""
    device_id = data.get('device_id')
    with simulation_lock:
        if device_id in clients:
            del clients[device_id]
            if device_id in positions:
                del positions[device_id]

    socketio.emit('client_removed', {'device_id': device_id})
    emit_log(f'Client {device_id} removed from system', 'info')
    return {'status': 'removed', 'device_id': device_id}


# Вспомогательные функции
def add_client(device_id, client_type):
    """Добавление нового клиента в систему"""
    position = {
        'x': random.uniform(2, room_config['width'] - 2),
        'y': random.uniform(2, room_config['height'] - 2),
        'z': 0.0 if client_type == 'robot' else 1.7
    }

    with simulation_lock:
        clients[device_id] = {
            'type': client_type,
            'status': 'active',
            'registered_at': datetime.now().isoformat(),
            'color': get_client_color(client_type)
        }

        positions[device_id] = {
            'position': position,
            'timestamp': datetime.now().isoformat(),
            'confidence': random.uniform(0.85, 0.98),
            'client_type': client_type
        }

    # Немедленно отправляем позицию клиенту
    socketio.emit('position_update', {
        'device_id': device_id,
        'position': position,
        'timestamp': datetime.now().isoformat(),
        'confidence': positions[device_id]['confidence'],
        'client_type': client_type
    })


def get_client_color(client_type):
    """Возвращает цвет для типа клиента"""
    colors = {
        'robot': '#e74c3c',
        'human': '#3498db'
    }
    return colors.get(client_type, '#95a5a6')


def move_client(device_id):
    """Перемещение клиента по карте"""
    with simulation_lock:
        if device_id not in positions:
            return None

        old_pos = positions[device_id]['position']
        client_type = clients[device_id]['type']

    # Разная логика движения для роботов и людей
    if client_type == 'robot':
        # Роботы движутся более предсказуемо
        angle = random.uniform(0, 2 * math.pi)
        distance = random.uniform(0.3, 1.5)
    else:
        # Люди движутся более случайно
        angle = random.uniform(0, 2 * math.pi)
        distance = random.uniform(0.1, 2.0)

    new_x = max(0.5, min(room_config['width'] - 0.5, old_pos['x'] + math.cos(angle) * distance))
    new_y = max(0.5, min(room_config['height'] - 0.5, old_pos['y'] + math.sin(angle) * distance))

    new_position = {
        'x': new_x,
        'y': new_y,
        'z': old_pos['z']
    }

    with simulation_lock:
        positions[device_id]['position'] = new_position
        positions[device_id]['timestamp'] = datetime.now().isoformat()
        positions[device_id]['confidence'] = random.uniform(0.8, 0.97)

    return new_position


def emit_log(message, log_type='info'):
    """Универсальная функция для отправки логов всем клиентам"""
    log_data = {
        'message': message,
        'type': log_type,
        'timestamp': datetime.now().isoformat()
    }
    socketio.emit('log_message', log_data)
    print(f"[{log_type.upper()}] {message}")


# Рабочий поток симуляции
def simulation_worker():
    """Фоновая работа симуляции - ОПТИМИЗИРОВАННАЯ ВЕРСИЯ"""
    global simulation_running

    emit_log('Simulation worker started', 'info')

    cycle = 0
    last_stat_update = 0

    try:
        while simulation_running:
            cycle += 1

            # Быстрое обновление позиций
            client_ids = []
            with simulation_lock:
                if not simulation_running:
                    break
                client_ids = list(clients.keys())
                system_status['cycle_count'] = cycle
                system_status['total_updates'] += len(client_ids)

            # Обновляем позиции всех клиентов
            for device_id in client_ids:
                if not simulation_running:
                    break

                new_position = move_client(device_id)
                if new_position:
                    with simulation_lock:
                        if not simulation_running:
                            break
                        statistics['position_updates'] += 1
                        confidence = positions[device_id]['confidence']
                        client_type = clients[device_id]['type']

                    # Быстрая отправка обновления
                    socketio.emit('position_update', {
                        'device_id': device_id,
                        'position': new_position,
                        'timestamp': datetime.now().isoformat(),
                        'confidence': confidence,
                        'client_type': client_type
                    }, skip_sid=None)

            # Обновляем статистику каждые 3 секунды (а не каждый цикл)
            current_time = time.time()
            if current_time - last_stat_update >= 3:
                socketio.emit('system_status', system_status)
                socketio.emit('statistics_update', statistics)
                last_stat_update = current_time

            # Короткая пауза для отзывчивости
            time.sleep(0.3)  # 300ms - плавное движение

    except Exception as e:
        statistics['errors'] += 1
        print(f"Simulation error: {e}")
        emit_log(f'Simulation error: {str(e)}', 'error')

    emit_log('Simulation worker stopped', 'info')


if __name__ == '__main__':
    print("🚀 Starting OPTIMIZED Indoor Positioning Server...")
    print("📊 Web interface: http://localhost:5000")
    print("⚡ Features: Fast response + Smooth movement")
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)