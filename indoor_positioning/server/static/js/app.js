/**
 * Indoor Positioning System - Frontend Application
 *
 * Основной клиентский модуль системы позиционирования.
 * Обеспечивает веб-интерфейс для отображения позиций в реальном времени,
 * управление системой и визуализацию данных.
 */
class IndoorPositioningApp {
    constructor() {
        this.socket = io();
        this.roomConfig = {
            width: 20,
            height: 15
        };
        this.anchors = new Map();      // Активные якоря
        this.devices = new Map();      // Обнаруженные устройства
        this.positions = new Map();    // Рассчитанные позиции
        this.selectedDevice = null;    // Выбранное устройство на карте

        this.init();
    }

    /**
     * Инициализация приложения
     */
    init() {
        this.setupSocketListeners();
        this.setupEventListeners();
        this.renderMap();
        this.updateStartTime();
        this.requestInitialData();
    }

    /**
     * Настройка обработчиков WebSocket событий
     */
    setupSocketListeners() {
        // События подключения
        this.socket.on('connect', () => {
            this.addLog('Подключено к серверу позиционирования', 'success');
            this.updateSystemStatus('АКТИВНА');
        });

        this.socket.on('disconnect', () => {
            this.addLog('Отключено от сервера', 'warning');
            this.updateSystemStatus('ОФФЛАЙН');
        });

        this.socket.on('connect_error', (error) => {
            console.error('Ошибка подключения:', error);
            this.addLog('Ошибка подключения: ' + error.message, 'error');
            this.updateSystemStatus('ОФФЛАЙН');
        });

        // События данных
        this.socket.on('anchors_data', (anchors) => {
            console.log('📡 Данные якорей получены:', anchors);
            this.updateAnchorsData(anchors);
        });

        this.socket.on('devices_data', (devices) => {
            console.log('📱 Данные устройств получены:', devices);
            this.updateDevicesData(devices);
        });

        this.socket.on('positions_data', (positions) => {
            console.log('📍 Данные позиций получены:', positions);
            this.updatePositionsData(positions);
        });

        this.socket.on('position_update', (data) => {
            console.log('🔄 Обновление позиции:', data);
            this.handlePositionUpdate(data);
        });

        this.socket.on('anchor_update', (data) => {
            console.log('📡 Обновление якоря:', data);
            this.handleAnchorUpdate(data);
        });

        // Системные события
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
            this.anchors.clear();
            this.devices.clear();
            this.positions.clear();
            this.selectedDevice = null;
            this.renderAnchorsList();
            this.renderDevicesList();
            this.renderMap();
            this.clearPositionDetails();
            this.addLog('Система была сброшена', 'info');
        });
    }

    /**
     * Обновление данных якорей
     */
    updateAnchorsData(anchors) {
        this.anchors = new Map(Object.entries(anchors));
        console.log('📊 Якоря обновлены:', this.anchors.size);
        this.renderAnchorsList();
        this.renderAnchorsOnMap();
        this.updateAnchorsCount();
    }

    /**
     * Обновление данных устройств
     */
    updateDevicesData(devices) {
        this.devices = new Map(Object.entries(devices));
        console.log('📊 Устройства обновлены:', this.devices.size);
        this.renderDevicesList();
        this.updateDevicesCount();
    }

    /**
     * Обновление данных позиций
     */
    updatePositionsData(positions) {
        this.positions = new Map(Object.entries(positions));
        console.log('📊 Позиции обновлены:', this.positions.size);
        this.renderDevicesOnMap();
        this.renderDevicesList();
    }

    /**
     * Обработка обновления позиции устройства
     */
    handlePositionUpdate(data) {
        this.positions.set(data.device_id, data);
        this.updateDeviceOnMap(data);
        this.updateDeviceInList(data.device_id, data.position, data.confidence);

        // Обновляем детали если устройство выбрано
        if (this.selectedDevice === data.device_id) {
            this.showPositionDetails(data.device_id);
        }
    }

    /**
     * Обработка обновления данных якоря
     */
    handleAnchorUpdate(data) {
        this.addLog(`Якорь ${data.anchor_id} обновил данные`, 'info');
    }

    /**
     * Настройка обработчиков событий UI
     */
    setupEventListeners() {
        // Системные контролы
        window.resetSystem = () => {
            if (confirm('Вы уверены, что хотите сбросить систему? Все данные будут удалены.')) {
                this.setButtonLoading('reset-btn', true);
                this.socket.emit('reset_system', {}, (response) => {
                    this.setButtonLoading('reset-btn', false);
                    if (response && response.status === 'success') {
                        this.addLog('Система сброшена', 'success');
                    }
                });
            }
        };

        window.refreshData = () => {
            this.setButtonLoading('refresh-btn', true);
            this.requestInitialData();
            setTimeout(() => {
                this.setButtonLoading('refresh-btn', false);
                this.addLog('Данные обновлены', 'info');
            }, 1000);
        };

        // Контролы отображения
        window.toggleConfidenceCircles = () => {
            const show = document.getElementById('show-confidence').checked;
            const circles = document.querySelectorAll('.confidence-circle');
            circles.forEach(circle => {
                circle.style.display = show ? 'block' : 'none';
            });
        };

        window.toggleAnchorsVisibility = () => {
            const show = document.getElementById('show-anchors').checked;
            const anchors = document.querySelectorAll('.anchor-point');
            anchors.forEach(anchor => {
                anchor.style.display = show ? 'block' : 'none';
            });
        };
    }

    /**
     * Установка состояния загрузки для кнопок
     */
    setButtonLoading(buttonId, isLoading) {
        const button = document.getElementById(buttonId);
        if (!button) return;

        const originalTexts = {
            'reset-btn': '🔄 Сбросить систему',
            'refresh-btn': '🔁 Обновить данные'
        };

        if (isLoading) {
            button.disabled = true;
            button.classList.add('btn-loading');
        } else {
            button.disabled = false;
            button.classList.remove('btn-loading');
            const originalText = originalTexts[buttonId];
            if (originalText) {
                button.innerHTML = originalText;
            }
        }
    }

    /**
     * Отрисовка карты позиционирования
     */
    renderMap() {
        const map = document.getElementById('map');

        // Очищаем только элементы устройств
        const deviceElements = map.querySelectorAll('.device-point, .device-label, .confidence-circle');
        deviceElements.forEach(element => element.remove());

        // Перерисовываем все устройства на карте
        this.positions.forEach((data, deviceId) => {
            this.updateDeviceOnMap(data);
        });

        // Отрисовываем якоря если они есть
        if (this.anchors.size > 0) {
            this.renderAnchorsOnMap();
        }
    }

    /**
     * Отрисовка якорей на карте
     */
    renderAnchorsOnMap() {
        const container = document.getElementById('anchors-container');
        if (!container) return;

        container.innerHTML = '';

        this.anchors.forEach((anchor, anchorId) => {
            const point = document.createElement('div');
            point.className = 'anchor-point active';
            point.setAttribute('data-anchor-id', anchorId);

            const x = (anchor.x / this.roomConfig.width) * 100;
            const y = (anchor.y / this.roomConfig.height) * 100;

            point.style.left = `${x}%`;
            point.style.top = `${y}%`;

            // Tooltip с координатами якоря
            point.title = `${anchorId}\nКоординаты: (${anchor.x}, ${anchor.y}, ${anchor.z})`;

            point.addEventListener('click', () => {
                this.showAnchorDetails(anchorId);
            });

            container.appendChild(point);
        });
    }

    /**
     * Отрисовка устройств на карте
     */
    renderDevicesOnMap() {
        const container = document.getElementById('devices-container');
        const confidenceContainer = document.getElementById('confidence-circles');
        if (!container || !confidenceContainer) return;

        container.innerHTML = '';
        confidenceContainer.innerHTML = '';

        this.positions.forEach((data, deviceId) => {
            this.updateDeviceOnMap(data);
        });
    }

    /**
     * Обновление отображения устройства на карте
     */
    updateDeviceOnMap(data) {
        const container = document.getElementById('devices-container');
        const confidenceContainer = document.getElementById('confidence-circles');
        if (!container || !confidenceContainer) return;

        let point = document.getElementById(`device-${data.device_id}`);
        let confidenceCircle = document.getElementById(`confidence-${data.device_id}`);

        // Создаем или обновляем точку устройства
        if (!point) {
            point = document.createElement('div');
            point.id = `device-${data.device_id}`;
            point.className = 'device-point';
            point.setAttribute('data-device-id', data.device_id);

            const deviceInfo = this.devices.get(data.device_id);
            const color = deviceInfo ? deviceInfo.color : '#3498db';
            point.style.background = color;
            point.style.border = `3px solid ${this.darkenColor(color, 20)}`;

            // Добавляем метку с MAC-адресом
            const label = document.createElement('div');
            label.className = 'device-label';
            label.textContent = this.formatMacAddress(data.device_id);
            point.appendChild(label);

            point.addEventListener('click', (e) => {
                e.stopPropagation();
                this.selectDevice(data.device_id);
            });

            container.appendChild(point);
        }

        // Создаем или обновляем круг точности
        if (!confidenceCircle) {
            confidenceCircle = document.createElement('div');
            confidenceCircle.id = `confidence-${data.device_id}`;
            confidenceCircle.className = 'confidence-circle';
            confidenceCircle.setAttribute('data-device-id', data.device_id);
            confidenceContainer.appendChild(confidenceCircle);
        }

        // Обновляем позиции
        const x = (data.position.x / this.roomConfig.width) * 100;
        const y = (data.position.y / this.roomConfig.height) * 100;

        point.style.left = `${x}%`;
        point.style.top = `${y}%`;

        // Обновляем круг точности
        const radius = (1 - data.confidence) * 50 + 20; // Радиус зависит от уверенности
        confidenceCircle.style.left = `${x}%`;
        confidenceCircle.style.top = `${y}%`;
        confidenceCircle.style.width = `${radius * 2}px`;
        confidenceCircle.style.height = `${radius * 2}px`;

        // Устанавливаем цвет в зависимости от уверенности
        const confidenceClass = data.confidence > 0.8 ? 'confidence-high' :
                               data.confidence > 0.6 ? 'confidence-medium' : 'confidence-low';
        confidenceCircle.className = `confidence-circle ${confidenceClass}`;

        // Обновляем видимость в зависимости от настроек
        const showConfidence = document.getElementById('show-confidence').checked;
        confidenceCircle.style.display = showConfidence ? 'block' : 'none';
    }

    /**
     * Выбор устройства на карте
     */
    selectDevice(deviceId) {
        // Снимаем выделение с предыдущего устройства
        if (this.selectedDevice) {
            const prevPoint = document.getElementById(`device-${this.selectedDevice}`);
            if (prevPoint) {
                prevPoint.classList.remove('selected');
            }
        }

        // Выделяем новое устройство
        this.selectedDevice = deviceId;
        const point = document.getElementById(`device-${deviceId}`);
        if (point) {
            point.classList.add('selected');
        }

        this.showPositionDetails(deviceId);
    }

    /**
     * Показ деталей позиции устройства
     */
    showPositionDetails(deviceId) {
        const position = this.positions.get(deviceId);
        const device = this.devices.get(deviceId);

        if (!position || !device) return;

        const container = document.getElementById('position-details');
        container.innerHTML = `
            <div class="detail-item">
                <span class="detail-label">MAC-адрес:</span>
                <span class="detail-value">${deviceId}</span>
            </div>
            <div class="detail-item">
                <span class="detail-label">Координаты (3D):</span>
                <span class="detail-value">X: ${position.position.x.toFixed(2)}м, Y: ${position.position.y.toFixed(2)}м, Z: ${position.position.z.toFixed(2)}м</span>
            </div>
            <div class="detail-item">
                <span class="detail-label">Точность:</span>
                <span class="detail-value">${(position.confidence * 100).toFixed(1)}%</span>
            </div>
            <div class="detail-item">
                <span class="detail-label">Якорей использовано:</span>
                <span class="detail-value">${position.anchors_used || 'Н/Д'}</span>
            </div>
            <div class="detail-item">
                <span class="detail-label">Последнее обновление:</span>
                <span class="detail-value">${new Date(position.timestamp).toLocaleTimeString()}</span>
            </div>
            <div class="detail-item">
                <span class="detail-label">Тип устройства:</span>
                <span class="detail-value">${this.getDeviceTypeText(device.type)}</span>
            </div>
        `;
    }

    /**
     * Показ деталей якоря
     */
    showAnchorDetails(anchorId) {
        const anchor = this.anchors.get(anchorId);
        if (!anchor) return;

        const container = document.getElementById('position-details');
        container.innerHTML = `
            <div class="detail-item">
                <span class="detail-label">ID якоря:</span>
                <span class="detail-value">${anchorId}</span>
            </div>
            <div class="detail-item">
                <span class="detail-label">Координаты (3D):</span>
                <span class="detail-value">X: ${anchor.x}m, Y: ${anchor.y}m, Z: ${anchor.z}m</span>
            </div>
            <div class="detail-item">
                <span class="detail-label">Статус:</span>
                <span class="detail-value">${this.getAnchorStatusText(anchor.status)}</span>
            </div>
            <div class="detail-item">
                <span class="detail-label">Последнее обновление:</span>
                <span class="detail-value">${new Date(anchor.last_update).toLocaleTimeString()}</span>
            </div>
        `;
    }

    /**
     * Очистка деталей позиции
     */
    clearPositionDetails() {
        const container = document.getElementById('position-details');
        container.innerHTML = '<div class="no-data">Выберите устройство на карте</div>';
    }

    /**
     * Обновление устройства в списке
     */
    updateDeviceInList(deviceId, position, confidence) {
        const deviceElement = document.querySelector(`[data-device-id="${deviceId}"]`);
        if (deviceElement) {
            const positionElement = deviceElement.querySelector('.device-position');
            if (positionElement) {
                positionElement.textContent = `(${position.x.toFixed(1)}, ${position.y.toFixed(1)})`;
            }

            const confidenceElement = deviceElement.querySelector('.device-confidence');
            if (confidenceElement) {
                confidenceElement.textContent = `${(confidence * 100).toFixed(0)}%`;
            }
        } else {
            // Перерисовываем список если элемента нет
            this.renderDevicesList();
        }
    }

    /**
     * Отрисовка списка якорей
     */
    renderAnchorsList() {
        const container = document.getElementById('anchors-list');
        if (!container) return;

        if (this.anchors.size === 0) {
            container.innerHTML = '<div class="no-data">Нет активных якорей</div>';
            return;
        }

        container.innerHTML = '';
        this.anchors.forEach((anchor, anchorId) => {
            const anchorElement = document.createElement('div');
            anchorElement.className = 'anchor-item';
            anchorElement.setAttribute('data-anchor-id', anchorId);

            anchorElement.innerHTML = `
                <div class="anchor-info">
                    <div class="anchor-name">${anchorId}</div>
                    <div class="anchor-status ${anchor.status}">${this.getAnchorStatusText(anchor.status)}</div>
                </div>
                <div class="anchor-coordinates">
                    (${anchor.x}, ${anchor.y}, ${anchor.z})
                </div>
            `;

            anchorElement.addEventListener('click', () => {
                this.showAnchorDetails(anchorId);
            });

            container.appendChild(anchorElement);
        });
    }

    /**
     * Отрисовка списка устройств
     */
    renderDevicesList() {
        const container = document.getElementById('devices-list');
        if (!container) return;

        if (this.devices.size === 0) {
            container.innerHTML = '<div class="no-data">Устройства не обнаружены</div>';
            return;
        }

        container.innerHTML = '';
        this.devices.forEach((device, deviceId) => {
            const position = this.positions.get(deviceId);
            const deviceElement = document.createElement('div');
            deviceElement.className = 'device-item';
            deviceElement.setAttribute('data-device-id', deviceId);

            const positionText = position ?
                `(${position.position.x.toFixed(1)}, ${position.position.y.toFixed(1)}, ${position.position.z.toFixed(1)})` :
                'Нет данных';

            const confidenceText = position ?
                `${(position.confidence * 100).toFixed(0)}%` :
                'Н/Д';

            deviceElement.innerHTML = `
                <div class="device-info">
                    <div class="device-mac">${this.formatMacAddress(deviceId)}</div>
                    <div class="device-type">${this.getDeviceTypeText(device.type)}</div>
                </div>
                <div style="text-align: right;">
                    <div class="device-position">${positionText}</div>
                    <div class="device-confidence" style="font-size: 0.8em; color: #7f8c8d;">${confidenceText}</div>
                </div>
            `;

            deviceElement.addEventListener('click', () => {
                this.selectDevice(deviceId);
            });

            container.appendChild(deviceElement);
        });
    }

    /**
     * Обновление статуса системы
     */
    updateSystemStatus(status) {
        const element = document.getElementById('system-status');
        if (element) {
            element.textContent = status;
            element.className = `status-value status-${status.toLowerCase()}`;
        }
    }

    /**
     * Обновление системной информации
     */
    updateSystemInfo(status) {
        if (status.total_updates !== undefined) {
            document.getElementById('total-updates').textContent = status.total_updates;
        }
        if (status.last_calculation) {
            document.getElementById('last-update').textContent =
                new Date(status.last_calculation).toLocaleTimeString();
        }
    }

    /**
     * Обновление статистики
     */
    updateStatistics(stats) {
        if (stats.connections !== undefined) {
            document.getElementById('connections-count').textContent = stats.connections;
        }
        if (stats.position_updates !== undefined) {
            document.getElementById('updates-count').textContent = stats.position_updates;
        }
        if (stats.devices_detected !== undefined) {
            document.getElementById('devices-count').textContent = stats.devices_detected;
        }
        if (stats.calculation_errors !== undefined) {
            document.getElementById('errors-count').textContent = stats.calculation_errors;
        }
    }

    /**
     * Обновление счетчика якорей
     */
    updateAnchorsCount() {
        const countElement = document.getElementById('anchors-count');
        if (countElement) {
            countElement.textContent = this.anchors.size;
        }
    }

    /**
     * Обновление счетчика устройств
     */
    updateDevicesCount() {
        const countElement = document.getElementById('devices-count');
        if (countElement) {
            countElement.textContent = this.devices.size;
        }
    }

    /**
     * Добавление записи в системный лог
     */
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

    /**
     * Обновление времени старта системы
     */
    updateStartTime() {
        const startTimeElement = document.getElementById('start-time');
        if (startTimeElement) {
            startTimeElement.textContent = new Date().toLocaleTimeString();
        }
    }

    /**
     * Запрос начальных данных с сервера
     */
    requestInitialData() {
        fetch('/api/anchors')
            .then(response => response.json())
            .then(anchors => this.updateAnchorsData(anchors))
            .catch(error => console.error('Ошибка загрузки якорей:', error));

        fetch('/api/devices')
            .then(response => response.json())
            .then(devices => this.updateDevicesData(devices))
            .catch(error => console.error('Ошибка загрузки устройств:', error));

        fetch('/api/positions')
            .then(response => response.json())
            .then(positions => this.updatePositionsData(positions))
            .catch(error => console.error('Ошибка загрузки позиций:', error));

        fetch('/api/status')
            .then(response => response.json())
            .then(status => {
                this.updateSystemInfo(status.system);
                this.updateStatistics(status.statistics);
            })
            .catch(error => console.error('Ошибка загрузки статуса:', error));
    }

    // Вспомогательные функции

    /**
     * Форматирование MAC-адреса
     */
    formatMacAddress(mac) {
        if (mac.length <= 12) return mac;
        return mac.match(/.{1,2}/g).join(':').toUpperCase();
    }

    /**
     * Получение текстового описания типа устройства
     */
    getDeviceTypeText(type) {
        const types = {
            'mobile_device': 'Мобильное устройство',
            'robot': 'Робот',
            'human': 'Оператор',
            'unknown': 'Неизвестно'
        };
        return types[type] || type;
    }

    /**
     * Получение текстового описания статуса якоря
     */
    getAnchorStatusText(status) {
        const statuses = {
            'active': 'Активен',
            'inactive': 'Неактивен',
            'error': 'Ошибка'
        };
        return statuses[status] || status;
    }

    /**
     * Затемнение цвета
     */
    darkenColor(color, percent) {
        const num = parseInt(color.replace("#", ""), 16);
        const amt = Math.round(2.55 * percent);
        const R = (num >> 16) - amt;
        const G = (num >> 8 & 0x00FF) - amt;
        const B = (num & 0x0000FF) - amt;
        return "#" + (0x1000000 + (R < 255 ? R < 1 ? 0 : R : 255) * 0x10000 +
            (G < 255 ? G < 1 ? 0 : G : 255) * 0x100 +
            (B < 255 ? B < 1 ? 0 : B : 255)).toString(16).slice(1);
    }
}

// Обработчик клика вне элементов для снятия выделения
document.addEventListener('click', (e) => {
    if (!e.target.closest('.device-point') && !e.target.closest('.anchor-point')) {
        if (app && app.selectedDevice) {
            const point = document.getElementById(`device-${app.selectedDevice}`);
            if (point) {
                point.classList.remove('selected');
            }
            app.selectedDevice = null;
            app.clearPositionDetails();
        }
    }
});

// Инициализация приложения
let app;
document.addEventListener('DOMContentLoaded', () => {
    app = new IndoorPositioningApp();
});

// Глобальная функция очистки лога
window.clearLog = () => {
    const logContainer = document.getElementById('system-log');
    if (logContainer) {
        const firstEntry = logContainer.querySelector('.log-entry:first-child');
        logContainer.innerHTML = '';
        if (firstEntry) {
            logContainer.appendChild(firstEntry);
        }
        if (app) {
            app.addLog('Лог очищен', 'info');
        }
    }
};