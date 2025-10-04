class EnhancedPositioningApp {
    constructor() {
        this.socket = io();
        this.roomConfig = {
            width: 20,
            height: 15
        };
        this.clients = new Map();
        this.positions = new Map();
        this.anchorsRendered = false; // Флаг для отслеживания отрисованных якорей

        this.init();
    }

    init() {
        this.setupSocketListeners();
        this.setupEventListeners();
        this.renderMap();
        this.updateStartTime();
        this.addMapLegend();
    }

    setupSocketListeners() {
        // Connection events
        this.socket.on('connect', () => {
            this.addLog('Подключено к серверу позиционирования', 'success');
            this.updateSystemStatus('ОНЛАЙН');
        });

        this.socket.on('disconnect', () => {
            this.addLog('Отключено от сервера', 'warning');
            this.updateSystemStatus('ОФФЛАЙН');
        });

        // Error handlers
        this.socket.on('connect_error', (error) => {
            console.error('Ошибка подключения:', error);
            this.addLog('Ошибка подключения: ' + error.message, 'error');
            this.updateSystemStatus('ОФФЛАЙН');
        });

        this.socket.on('reconnect_attempt', () => {
            console.log('Попытка переподключения...');
            this.addLog('Переподключение к серверу...', 'warning');
        });

        this.socket.on('reconnect', () => {
            console.log('Успешно переподключено');
            this.addLog('Переподключено к серверу', 'success');
            this.updateSystemStatus('ОНЛАЙН');
        });

        // Data events
        this.socket.on('anchors_data', (anchors) => {
            console.log('📌 Данные якорей получены:', anchors);
            this.renderAnchors(anchors);
        });

        this.socket.on('clients_data', (clients) => {
            console.log('📋 Данные клиентов получены:', clients);
            this.updateClientsData(clients);
        });

        this.socket.on('positions_data', (positions) => {
            console.log('📍 Данные позиций получены:', positions);
            this.updatePositionsData(positions);
        });

        this.socket.on('position_update', (data) => {
            console.log('🔄 Обновление позиции:', data);
            this.handlePositionUpdate(data);
        });

        this.socket.on('client_removed', (data) => {
            console.log('🗑️ Клиент удален:', data);
            this.removeClientFromUI(data.device_id);
        });

        // System events
        this.socket.on('system_status', (status) => {
            this.updateSystemInfo(status);
        });

        this.socket.on('statistics_update', (stats) => {
            this.updateStatistics(stats);
        });

        this.socket.on('log_message', (log) => {
            this.addLog(log.message, log.type);
        });

        this.socket.on('system_reset', () => {
            this.clients.clear();
            this.positions.clear();
            this.renderClientsList();
            this.renderMap();
            this.addLog('Система была сброшена', 'info');
        });
    }

    updateClientsData(clients) {
        this.clients = new Map(Object.entries(clients));
        console.log('📊 Клиенты обновлены:', this.clients.size);
        this.renderClientsList();
        this.updateClientsCount();
    }

    updatePositionsData(positions) {
        this.positions = new Map(Object.entries(positions));
        console.log('📊 Позиции обновлены:', this.positions.size);
        this.renderMap();
        this.renderClientsList();
    }

    handlePositionUpdate(data) {
        // Update position in positions map
        this.positions.set(data.device_id, data);

        // Update or create client on map
        this.updateClientOnMap(data);

        // Update client in list
        this.updateClientInList(data.device_id, data.position);

        // Ensure client exists in clients list
        if (!this.clients.has(data.device_id)) {
            this.clients.set(data.device_id, {
                type: data.client_type,
                status: 'active'
            });
            this.renderClientsList();
        }
    }

    setupEventListeners() {
        // Основные кнопки управления
        window.startSimulation = () => {
            console.log('🚀 Запуск симуляции...');
            this.setButtonLoading('start-sim', true);
            this.socket.emit('start_simulation', {}, (response) => {
                console.log('Ответ запуска симуляции:', response);
                this.setButtonLoading('start-sim', false);
                if (response && response.status === 'started') {
                    this.addLog('Симуляция успешно запущена', 'success');
                }
            });
        };

        window.stopSimulation = () => {
            console.log('🛑 Остановка симуляции...');
            this.setButtonLoading('stop-sim', true);
            this.socket.emit('stop_simulation', {}, (response) => {
                console.log('Ответ остановки симуляции:', response);
                this.setButtonLoading('stop-sim', false);
                if (response && response.status === 'stopped') {
                    this.addLog('Симуляция остановлена', 'info');
                }
            });
        };

        window.addRobot = () => {
            console.log('🤖 Добавление робота...');
            this.setButtonLoading('add-robot', true);
            this.socket.emit('add_robot', {}, (response) => {
                console.log('Ответ добавления робота:', response);
                this.setButtonLoading('add-robot', false);
                if (response && response.status === 'added') {
                    this.addLog(`Робот ${response.device_id} добавлен`, 'success');
                }
            });
        };

        window.addHuman = () => {
            console.log('👤 Добавление оператора...');
            this.setButtonLoading('add-human', true);
            this.socket.emit('add_human', {}, (response) => {
                console.log('Ответ добавления оператора:', response);
                this.setButtonLoading('add-human', false);
                if (response && response.status === 'added') {
                    this.addLog(`Оператор ${response.device_id} добавлен`, 'success');
                }
            });
        };

        window.resetSystem = () => {
            if (confirm('Вы уверены, что хотите сбросить систему? Все клиенты будут удалены.')) {
                this.setButtonLoading('reset-btn', true);
                fetch('/api/control', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ command: 'reset' })
                }).then(response => response.json())
                  .then(data => {
                      console.log('Ответ сброса:', data);
                      this.setButtonLoading('reset-btn', false);
                      if (data.status === 'system_reset') {
                          this.addLog('Сброс системы завершен', 'success');
                      }
                  })
                  .catch(error => {
                      console.error('Ошибка сброса:', error);
                      this.addLog('Ошибка сброса: ' + error, 'error');
                      this.setButtonLoading('reset-btn', false);
                  });
            }
        };

        // Быстрые действия
        window.addMultipleRobots = (count) => {
            this.addLog(`Добавление ${count} роботов...`, 'info');
            for (let i = 0; i < count; i++) {
                setTimeout(() => {
                    this.socket.emit('add_robot', {});
                }, i * 500);
            }
        };

        window.addMultipleHumans = (count) => {
            this.addLog(`Добавление ${count} операторов...`, 'info');
            for (let i = 0; i < count; i++) {
                setTimeout(() => {
                    this.socket.emit('add_human', {});
                }, i * 500);
            }
        };

        window.removeAllClients = () => {
            const clientCount = this.clients.size;
            if (clientCount === 0) {
                this.addLog('Нет клиентов для удаления', 'warning');
                return;
            }

            if (confirm(`Удалить всех ${clientCount} клиентов из системы?`)) {
                this.clients.forEach((client, deviceId) => {
                    this.socket.emit('remove_client', { device_id: deviceId });
                });
                this.addLog(`Инициировано удаление ${clientCount} клиентов`, 'info');
            }
        };

        window.clearLog = () => {
            const logContainer = document.getElementById('system-log');
            if (logContainer) {
                // Сохраняем только первую запись (время запуска)
                const firstEntry = logContainer.querySelector('.log-entry:first-child');
                logContainer.innerHTML = '';
                if (firstEntry) {
                    logContainer.appendChild(firstEntry);
                }
                this.addLog('Лог очищен', 'info');
            }
        };
    }

    setButtonLoading(buttonId, isLoading) {
        const button = document.getElementById(buttonId);
        if (!button) return;

        const originalTexts = {
            'start-sim': '▶ Запустить симуляцию',
            'stop-sim': '⏹ Остановить симуляцию',
            'add-robot': '🤖 Добавить робота',
            'add-human': '👤 Добавить оператора',
            'reset-btn': '🔄 Сбросить систему'
        };

        if (isLoading) {
            button.disabled = true;
            button.style.opacity = '0.6';
            button.innerHTML = '⏳ Загрузка...';
        } else {
            button.disabled = false;
            button.style.opacity = '1';
            const originalText = originalTexts[buttonId];
            if (originalText) {
                button.innerHTML = originalText;
            }
        }
    }

    renderMap() {
        const map = document.getElementById('map');

        // Очищаем только клиентов, но не якоря и легенду
        const elementsToRemove = map.querySelectorAll('.client-point, .client-label, .confidence-bar');
        elementsToRemove.forEach(element => element.remove());

        // Re-render all clients on map
        this.positions.forEach((data, deviceId) => {
            this.updateClientOnMap(data);
        });

        // Если якоря еще не отрисованы, запрашиваем их
        if (!this.anchorsRendered) {
            this.socket.emit('request_anchors');
        }

        // Добавляем легенду если её нет
        if (!document.querySelector('.map-legend')) {
            this.addMapLegend();
        }
    }

    renderAnchors(anchors) {
        const map = document.getElementById('map');

        // Очищаем только старые якоря
        const oldAnchors = map.querySelectorAll('.anchor-point');
        oldAnchors.forEach(anchor => anchor.remove());

        Object.entries(anchors).forEach(([id, anchor]) => {
            const point = document.createElement('div');
            point.className = 'anchor-point';
            point.title = `${id}\n(${anchor.coordinates.x}, ${anchor.coordinates.y}, ${anchor.coordinates.z})`;

            const x = (anchor.coordinates.x / this.roomConfig.width) * 100;
            const y = (anchor.coordinates.y / this.roomConfig.height) * 100;

            point.style.left = `${x}%`;
            point.style.top = `${y}%`;

            map.appendChild(point);
        });

        this.anchorsRendered = true;
        this.addLog(`Якоря размещены: ${Object.keys(anchors).length}`, 'info');
    }

    updateClientOnMap(data) {
        let point = document.getElementById(`client-${data.device_id}`);

        if (!point) {
            point = document.createElement('div');
            point.id = `client-${data.device_id}`;
            point.className = `client-point client-${data.client_type}-point`;

            // Add label
            const label = document.createElement('div');
            label.className = 'client-label';
            label.textContent = data.device_id;
            point.appendChild(label);

            // Add confidence bar
            const confidenceBar = document.createElement('div');
            confidenceBar.className = 'confidence-bar';
            const confidenceFill = document.createElement('div');
            confidenceFill.className = 'confidence-fill';
            confidenceBar.appendChild(confidenceFill);
            point.appendChild(confidenceBar);

            document.getElementById('map').appendChild(point);
        } else {
            // Update class if needed
            point.className = `client-point client-${data.client_type}-point`;
        }

        const x = (data.position.x / this.roomConfig.width) * 100;
        const y = (data.position.y / this.roomConfig.height) * 100;

        point.style.left = `${x}%`;
        point.style.top = `${y}%`;

        // Update confidence
        const confidenceFill = point.querySelector('.confidence-fill');
        if (confidenceFill) {
            confidenceFill.style.width = `${data.confidence * 100}%`;
            confidenceFill.style.background = data.confidence > 0.9 ? '#27ae60' :
                                             data.confidence > 0.7 ? '#f39c12' : '#e74c3c';
        }
    }

    updateClientInList(deviceId, position) {
        const clientElement = document.querySelector(`[data-device-id="${deviceId}"]`);
        if (clientElement) {
            const positionElement = clientElement.querySelector('.client-position');
            if (positionElement) {
                positionElement.textContent = `(${position.x.toFixed(1)}, ${position.y.toFixed(1)})`;
            }
        } else {
            // If client element doesn't exist, re-render the list
            this.renderClientsList();
        }
    }

    renderClientsList() {
        const container = document.getElementById('clients-list');
        container.innerHTML = '';

        console.log('🔄 Отрисовка списка клиентов:', this.clients.size, 'клиентов');

        this.clients.forEach((client, deviceId) => {
            const position = this.positions.get(deviceId);
            const clientElement = document.createElement('div');
            clientElement.className = `client-item client-${client.type}`;
            clientElement.setAttribute('data-device-id', deviceId);

            const positionText = position ?
                `(${position.position.x.toFixed(1)}, ${position.position.y.toFixed(1)})` :
                'Нет данных о позиции';

            const typeText = client.type === 'robot' ? 'Робот' : 'Оператор';

            clientElement.innerHTML = `
                <div class="client-info">
                    <div class="client-name">${deviceId}</div>
                    <div class="client-type">${typeText}</div>
                </div>
                <div class="client-position">${positionText}</div>
                <button class="remove-btn" onclick="app.removeClient('${deviceId}')" title="Удалить клиента">
                    ×
                </button>
            `;
            container.appendChild(clientElement);
        });

        this.updateClientsCount();
    }

    removeClient(deviceId) {
        console.log('Удаление клиента:', deviceId);
        this.socket.emit('remove_client', { device_id: deviceId });
    }

    removeClientFromUI(deviceId) {
        // Remove from clients map
        this.clients.delete(deviceId);
        this.positions.delete(deviceId);

        // Remove from DOM
        const clientElement = document.querySelector(`[data-device-id="${deviceId}"]`);
        if (clientElement) {
            clientElement.remove();
        }

        // Remove from map
        const mapElement = document.getElementById(`client-${deviceId}`);
        if (mapElement) {
            mapElement.remove();
        }

        this.updateClientsCount();
        this.addLog(`Клиент ${deviceId} удален`, 'info');
    }

    updateSystemStatus(status) {
        const element = document.getElementById('system-status');
        if (element) {
            element.textContent = status;
            element.className = `status-value status-${status.toLowerCase()}`;
        }
    }

    updateSystemInfo(status) {
        if (status.cycle_count !== undefined) {
            document.getElementById('cycle-count').textContent = status.cycle_count;
        }
        if (status.total_updates !== undefined) {
            document.getElementById('total-updates').textContent = status.total_updates;
        }
        if (status.is_running !== undefined) {
            // Обновляем статус симуляции
            const startBtn = document.getElementById('start-sim');
            const stopBtn = document.getElementById('stop-sim');
            if (status.is_running) {
                startBtn.disabled = true;
                stopBtn.disabled = false;
            } else {
                startBtn.disabled = false;
                stopBtn.disabled = true;
            }
        }
    }

    updateStatistics(stats) {
        if (stats.connections !== undefined) {
            document.getElementById('connections-count').textContent = stats.connections;
        }
        if (stats.position_updates !== undefined) {
            document.getElementById('updates-count').textContent = stats.position_updates;
        }
        if (stats.errors !== undefined) {
            document.getElementById('errors-count').textContent = stats.errors;
        }
    }

    updateClientsCount() {
        const countElement = document.getElementById('clients-count');
        if (countElement) {
            countElement.textContent = this.clients.size;
            console.log('👥 Количество клиентов обновлено:', this.clients.size);
        }
    }

    addLog(message, type = 'info') {
        const log = document.getElementById('system-log');
        if (log) {
            const entry = document.createElement('div');
            entry.className = 'log-entry';

            entry.innerHTML = `
                <span class="log-time">${new Date().toLocaleTimeString()}</span>
                <span class="log-message log-type-${type}">${message}</span>
            `;

            log.appendChild(entry);
            log.scrollTop = log.scrollHeight;
        }
    }

    updateStartTime() {
        const startTimeElement = document.getElementById('start-time');
        if (startTimeElement) {
            startTimeElement.textContent = new Date().toLocaleTimeString();
        }
    }

    addMapLegend() {
        const map = document.getElementById('map');
        if (map && !document.querySelector('.map-legend')) {
            const legend = document.createElement('div');
            legend.className = 'map-legend';
            legend.style.cssText = `
                position: absolute;
                bottom: 10px;
                right: 10px;
                background: rgba(255, 255, 255, 0.95);
                padding: 10px;
                border-radius: 5px;
                font-size: 12px;
                z-index: 1000;
                border: 1px solid #ddd;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            `;
            legend.innerHTML = `
                <div style="font-weight: bold; margin-bottom: 5px; color: #2c3e50;">Легенда</div>
                <div style="display: flex; align-items: center; margin: 3px 0;">
                    <div style="width: 12px; height: 12px; background: #e74c3c; border: 2px solid #c0392b; border-radius: 50%; margin-right: 8px;"></div>
                    <span style="color: #2c3e50;">Якорь</span>
                </div>
                <div style="display: flex; align-items: center; margin: 3px 0;">
                    <div style="width: 12px; height: 12px; background: #e74c3c; border: 2px solid #c0392b; border-radius: 50%; margin-right: 8px;"></div>
                    <span style="color: #2c3e50;">Робот</span>
                </div>
                <div style="display: flex; align-items: center; margin: 3px 0;">
                    <div style="width: 12px; height: 12px; background: #3498db; border: 2px solid #2980b9; border-radius: 50%; margin-right: 8px;"></div>
                    <span style="color: #2c3e50;">Оператор</span>
                </div>
            `;
            map.appendChild(legend);

            // Добавляем обработчик для предотвращения удаления легенды
            legend.setAttribute('data-legend', 'true');
        }
    }
}

// Initialize application
let app;
document.addEventListener('DOMContentLoaded', () => {
    app = new EnhancedPositioningApp();
});