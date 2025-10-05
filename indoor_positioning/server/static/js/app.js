/**
 * Indoor Positioning System - Enhanced with Auto Anchor Detection
 */
class IndoorPositioningApp {
        constructor() {
            this.socket = io();
        this.roomConfig = {
            width: 20,
            height: 15,
            depth: 5
        };
        this.anchorsConfig = {};
        this.aclConfig = {
            enabled: false,
            allowed_macs: [],
            display_preference: 'ssid'
        };
        this.anchors = new Map();
        this.devices = new Map();
        this.positions = new Map();
        this.selectedDevice = null;
        this.autoRefreshInterval = null;
        this.isConfigOpen = false;

        this.deviceAnimations = new Map(); // Для хранения текущих анимаций
        this.animationDuration = 500; // Длительность анимации в мс

        this.init();
    }

    init() {
        this.setupSocketListeners();
        this.setupEventListeners();
        this.renderMap();
        this.updateStartTime();
        this.startAutoRefresh();
        this.loadConfigurations();
        this.loadACLConfig();
    }

    setupSocketListeners() {
        this.socket.on('connect', () => {
            this.addLog('Подключено к серверу', 'success');
            this.updateSystemStatus('АКТИВНА');
        });

        this.socket.on('disconnect', () => {
            this.addLog('Отключено от сервера', 'warning');
            this.updateSystemStatus('ОФФЛАЙН');
        });

        // Данные системы
        this.socket.on('anchors_data', (anchors) => {
            this.updateAnchorsData(anchors);
        });

        this.socket.on('devices_data', (devices) => {
            this.updateDevicesData(devices);
        });

        this.socket.on('positions_data', (positions) => {
            this.updatePositionsData(positions);
        });

        this.socket.on('position_update', (data) => {
            this.handlePositionUpdate(data);
        });

        this.socket.on('position_removed', (data) => {
            this.handlePositionRemoved(data.device_id);
        });

        this.socket.on('device_removed', (data) => {
            this.handleDeviceRemoved(data.device_id);
        });

        this.socket.on('anchor_removed', (data) => {
            this.handleAnchorRemoved(data.anchor_id);
        });

        // Конфигурации
        this.socket.on('room_config_updated', (config) => {
            this.roomConfig = config;
            this.renderMap();
            this.addLog('Конфигурация комнаты обновлена', 'success');
        });

        this.socket.on('anchors_config_updated', (config) => {
            this.anchorsConfig = config;
            this.renderAnchorsOnMap();
            this.renderAnchorsList();
            this.addLog('Конфигурация якорей обновлена', 'success');
        });

        this.socket.on('acl_config_updated', (config) => {
            this.aclConfig = config;
            this.renderDevicesList();
            this.renderDevicesOnMap();
            this.addLog('Настройки отображения обновлены', 'success');
        });

        this.socket.on('anchor_updated', (data) => {
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
    }

    loadConfigurations() {
        // Загрузка конфигурации комнаты
        fetch('/api/config/room')
            .then(response => response.json())
            .then(config => {
                this.roomConfig = config;
                this.renderMap();
            })
            .catch(error => console.error('Ошибка загрузки конфигурации комнаты:', error));

        // Загрузка конфигурации якорей
        fetch('/api/config/anchors')
            .then(response => response.json())
            .then(config => {
                this.anchorsConfig = config;
                this.renderAnchorsOnMap();
                this.renderAnchorsList();
            })
            .catch(error => console.error('Ошибка загрузки конфигурации якорей:', error));
    }

    loadACLConfig() {
        fetch('/api/config/acl')
            .then(response => response.json())
            .then(config => {
                this.aclConfig = config;
                this.renderDevicesList();
                this.renderDevicesOnMap();
            })
            .catch(error => console.error('Ошибка загрузки ACL конфигурации:', error));
    }

    startAutoRefresh() {
        this.autoRefreshInterval = setInterval(() => {
            this.requestInitialData();
        }, 2000);
    }

    stopAutoRefresh() {
        if (this.autoRefreshInterval) {
            clearInterval(this.autoRefreshInterval);
            this.autoRefreshInterval = null;
        }
    }

    togglePositioning() {
        const isRunning = !this.isSystemRunning();
        this.socket.emit('toggle_positioning', { is_running: isRunning });

        const button = document.getElementById('toggle-btn');
        if (button) {
            button.innerHTML = isRunning ? '⏹️ Остановить' : '▶️ Запустить';
            button.className = isRunning ? 'btn btn-warning' : 'btn btn-success';
        }

        this.updateSystemStatus(isRunning ? 'АКТИВНА' : 'ОСТАНОВЛЕНА');
    }

    isSystemRunning() {
        const statusElement = document.getElementById('system-status');
        return statusElement && statusElement.textContent === 'АКТИВНА';
    }

    // ACL и отображение
    getDeviceDisplayName(deviceId, deviceInfo) {
        // Если включено отображение по SSID и есть SSID
        if (this.aclConfig.display_preference === 'ssid') {
            if (deviceInfo && deviceInfo.ssid) {
                const ssid = deviceInfo.ssid;
                // Не показываем технические названия скрытых сетей
                if (ssid !== '<Hidden_Network>' && ssid !== '<Unknown_SSID>' && ssid !== '') {
                    return ssid;
                }
            }
        }

        // Fallback to MAC
        return this.formatMacAddress(deviceId);
    }

    isDeviceAllowed(deviceId) {
        if (!this.aclConfig.enabled) return true;

        // Приводим к верхнему регистру для сравнения
        const deviceIdUpper = deviceId.toUpperCase();
        return this.aclConfig.allowed_macs.some(mac =>
            mac.toUpperCase() === deviceIdUpper
        );
    }

    // Обновление данных
    updateAnchorsData(anchors) {
        const previousCount = this.anchors.size;
        this.anchors = new Map(Object.entries(anchors));

        this.renderAnchorsList();
        this.renderAnchorsOnMap();
        this.updateAnchorsCount();

        const currentCount = this.anchors.size;
        if (currentCount > previousCount) {
            this.addLog(`Обнаружены новые якоря: ${currentCount} активных`, 'info');
        } else if (currentCount < previousCount) {
            this.addLog(`Якоря отключились: ${currentCount} активных`, 'warning');
        }
    }

    updateDevicesData(devices) {
        const previousCount = this.devices.size;
        this.devices = new Map(Object.entries(devices));

        this.renderDevicesList();
        this.updateDevicesCount();

        const currentCount = this.devices.size;
        if (currentCount > previousCount) {
            this.addLog(`Обнаружены новые устройства: ${currentCount} всего`, 'info');
        } else if (currentCount < previousCount) {
            this.addLog(`Устройства пропали: ${currentCount} всего`, 'warning');
        }
    }

    updatePositionsData(positions) {
        this.positions = new Map(Object.entries(positions));
        this.renderDevicesOnMap();
        this.renderDevicesList();
    }

    handlePositionUpdate(data) {
        if (!this.isDeviceAllowed(data.device_id)) return;

        this.positions.set(data.device_id, data);
        this.updateDeviceOnMap(data);
        this.updateDeviceInList(data.device_id, data.position, data.confidence);

        if (this.selectedDevice === data.device_id) {
            this.showPositionDetails(data.device_id);
        }
    }

    handlePositionRemoved(deviceId) {
        this.positions.delete(deviceId);
        this.removeDeviceFromMap(deviceId);
        this.renderDevicesList();

        if (this.selectedDevice === deviceId) {
            this.selectedDevice = null;
            this.clearPositionDetails();
        }
    }

    handleDeviceRemoved(deviceId) {
        this.devices.delete(deviceId);
        this.positions.delete(deviceId);
        this.removeDeviceFromMap(deviceId);
        this.renderDevicesList();
        this.updateDevicesCount();

        if (this.selectedDevice === deviceId) {
            this.selectedDevice = null;
            this.clearPositionDetails();
        }
    }

    handleAnchorUpdate(data) {
        if (data.anchor_id && data.config) {
            this.anchors.set(data.anchor_id, data.config);
            this.updateAnchorOnMap(data.anchor_id, data.config);
            this.updateAnchorsCount();
        }
    }

    updateAnchorOnMap(anchorId, anchorData) {
        const anchorElement = document.querySelector(`[data-anchor-id="${anchorId}"]`);
        if (anchorElement) {
            const isActive = anchorData.status === 'active';
            anchorElement.className = isActive ? 'anchor-point active' : 'anchor-point inactive';

            const statusText = isActive ? 'АКТИВЕН' : 'НЕАКТИВЕН';
            const lastUpdate = new Date(anchorData.last_update).toLocaleTimeString();
            anchorElement.title = `${anchorId} (${statusText})\nКоординаты: (${anchorData.x}, ${anchorData.y}, ${anchorData.z})\nПоследнее обновление: ${lastUpdate}`;
        }
    }

    handleAnchorRemoved(anchorId) {
        const anchorElement = document.querySelector(`[data-anchor-id="${anchorId}"]`);
        if (anchorElement) {
            anchorElement.remove();
        }
        this.updateAnchorsCount();
    }

    // UI Management
    setupEventListeners() {
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

        window.openConfig = () => {
            this.openConfigurationModal();
        };
    }

    openConfigurationModal() {
        const modal = document.getElementById('config-modal');
        if (modal) {
            modal.style.display = 'block';
            this.populateConfigForm();
        }
    }

    closeConfigModal() {
        const modal = document.getElementById('config-modal');
        if (modal) {
            modal.style.display = 'none';
        }
    }

    populateConfigForm() {
        document.getElementById('room-width').value = this.roomConfig.width;
        document.getElementById('room-height').value = this.roomConfig.height;
        document.getElementById('room-depth').value = this.roomConfig.depth;

        const anchorsContainer = document.getElementById('anchors-config-container');
        anchorsContainer.innerHTML = '';

        Object.entries(this.anchorsConfig).forEach(([anchorId, config]) => {
            const anchorElement = document.createElement('div');
            anchorElement.className = 'anchor-config-item';
            anchorElement.innerHTML = `
                <h4>${anchorId}</h4>
                <div class="config-row">
                    <label>X (0-${this.roomConfig.width}):</label>
                    <input type="number" step="0.1" value="${config.x}"
                           data-anchor="${anchorId}" data-field="x"
                           min="0" max="${this.roomConfig.width}">
                </div>
                <div class="config-row">
                    <label>Y (0-${this.roomConfig.height}):</label>
                    <input type="number" step="0.1" value="${config.y}"
                           data-anchor="${anchorId}" data-field="y"
                           min="0" max="${this.roomConfig.height}">
                </div>
                <div class="config-row">
                    <label>Z (0-${this.roomConfig.depth}):</label>
                    <input type="number" step="0.1" value="${config.z}"
                           data-anchor="${anchorId}" data-field="z"
                           min="0" max="${this.roomConfig.depth}">
                </div>
                <div class="config-row">
                    <label>Включен:</label>
                    <input type="checkbox" ${config.enabled ? 'checked' : ''}
                           data-anchor="${anchorId}" data-field="enabled">
                </div>
            `;
            anchorsContainer.appendChild(anchorElement);
        });

        this.renderACLConfig();
        this.clearValidationMessages();
    }

    renderACLConfig() {
        const container = document.getElementById('acl-config-container');
        if (!container) return;

        container.innerHTML = `
            <div class="config-section">
                <h3>ACL Фильтрация и Отображение</h3>
                <div class="config-row">
                    <label>Включить фильтрацию по MAC:</label>
                    <input type="checkbox" id="acl-enabled" ${this.aclConfig.enabled ? 'checked' : ''}>
                </div>
                <div class="config-row">
                    <label>Отображать устройства как:</label>
                    <select id="display-preference">
                        <option value="ssid" ${this.aclConfig.display_preference === 'ssid' ? 'selected' : ''}>SSID (имя сети)</option>
                        <option value="mac" ${this.aclConfig.display_preference === 'mac' ? 'selected' : ''}>MAC-адрес</option>
                    </select>
                </div>
                <div class="config-row">
                    <label>Разрешенные MAC-адреса (по одному в строке):</label>
                    <textarea id="allowed-macs" rows="6" placeholder="AA:BB:CC:DD:EE:FF&#10;11:22:33:44:55:66">${this.aclConfig.allowed_macs.join('\n')}</textarea>
                </div>
                <div class="config-hint">
                    <strong>Подсказка:</strong> При включенной фильтрации отображаются только устройства из списка выше.
                    При отключенной фильтрации показываются все устройства.
                </div>
            </div>
        `;
    }

    clearValidationMessages() {
        const errorContainer = document.getElementById('config-errors');
        if (errorContainer) {
            errorContainer.innerHTML = '';
            errorContainer.style.display = 'none';
        }
    }

    showValidationErrors(errors) {
        const errorContainer = document.getElementById('config-errors');
        if (errorContainer) {
            errorContainer.innerHTML = errors.map(error =>
                `<div class="error-message">❌ ${error}</div>`
            ).join('');
            errorContainer.style.display = 'block';

            setTimeout(() => {
                this.clearValidationMessages();
            }, 5000);
        }
    }

    validateConfig() {
        const roomConfig = {
            width: parseFloat(document.getElementById('room-width').value),
            height: parseFloat(document.getElementById('room-height').value),
            depth: parseFloat(document.getElementById('room-depth').value)
        };

        const anchorsConfig = {};
        const inputs = document.querySelectorAll('#anchors-config-container input');

        inputs.forEach(input => {
            const anchorId = input.dataset.anchor;
            const field = input.dataset.field;

            if (!anchorsConfig[anchorId]) {
                anchorsConfig[anchorId] = {};
            }

            if (field === 'enabled') {
                anchorsConfig[anchorId][field] = input.checked;
            } else {
                const value = parseFloat(input.value);
                anchorsConfig[anchorId][field] = isNaN(value) ? 0 : value;
            }
        });

        return fetch('/api/config/validate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ room: roomConfig, anchors: anchorsConfig })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .catch(error => {
            console.error('Validation error:', error);
            return { valid: false, errors: ['Ошибка валидации конфигурации'] };
        });
    }

    saveRoomConfig() {
        const config = {
            width: parseFloat(document.getElementById('room-width').value),
            height: parseFloat(document.getElementById('room-height').value),
            depth: parseFloat(document.getElementById('room-depth').value)
        };

        this.validateConfig().then(result => {
            if (result.valid) {
                fetch('/api/config/room', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(config)
                })
                .then(response => {
                    if (!response.ok) {
                        throw new Error(`HTTP error! status: ${response.status}`);
                    }
                    return response.json();
                })
                .then(data => {
                    if (data.status === 'success') {
                        this.roomConfig = data.config;
                        this.addLog('Конфигурация комнаты сохранена', 'success');
                        this.clearValidationMessages();
                        this.renderMap();
                        setTimeout(() => {
                            this.closeConfigModal();
                        }, 1000);
                    } else {
                        this.showValidationErrors([data.error || 'Ошибка сохранения конфигурации комнаты']);
                    }
                })
                .catch(error => {
                    console.error('Save room config error:', error);
                    this.showValidationErrors(['Ошибка сети при сохранении конфигурации комнаты']);
                });
            } else {
                this.showValidationErrors(result.errors);
            }
        });
    }

    saveAnchorsConfig() {
        const config = {};

        const inputs = document.querySelectorAll('#anchors-config-container input');
        inputs.forEach(input => {
            const anchorId = input.dataset.anchor;
            const field = input.dataset.field;

            if (!config[anchorId]) {
                config[anchorId] = {};
            }

            if (field === 'enabled') {
                config[anchorId][field] = input.checked;
            } else {
                const value = parseFloat(input.value);
                config[anchorId][field] = isNaN(value) ? 0 : value;
            }
        });

        this.validateConfig().then(result => {
            if (result.valid) {
                fetch('/api/config/anchors', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(config)
                })
                .then(response => {
                    if (!response.ok) {
                        throw new Error(`HTTP error! status: ${response.status}`);
                    }
                    return response.json();
                })
                .then(data => {
                    if (data.status === 'success') {
                        this.addLog('Конфигурация якорей сохранена', 'success');
                        this.clearValidationMessages();
                        this.closeConfigModal();
                        setTimeout(() => {
                            this.loadConfigurations();
                        }, 500);
                    } else {
                        this.showValidationErrors(data.details || ['Ошибка сохранения конфигурации якорей']);
                    }
                })
                .catch(error => {
                    console.error('Save error:', error);
                    this.showValidationErrors(['Ошибка сети при сохранении конфигурации']);
                });
            } else {
                this.showValidationErrors(result.errors);
            }
        });
    }

    saveACLConfig() {
        const enabled = document.getElementById('acl-enabled').checked;
        const displayPreference = document.getElementById('display-preference').value;
        const allowedMacs = document.getElementById('allowed-macs').value
            .split('\n')
            .map(mac => mac.trim().toUpperCase())
            .filter(mac => mac.length > 0);

        const config = {
            enabled: enabled,
            display_preference: displayPreference,
            allowed_macs: allowedMacs
        };

        fetch('/api/config/acl', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                this.aclConfig = data.config;
                this.addLog('Настройки отображения сохранены', 'success');
                this.renderDevicesList();
                this.renderDevicesOnMap();
            } else {
                this.showValidationErrors([data.error || 'Ошибка сохранения настроек отображения']);
            }
        })
        .catch(error => {
            console.error('Save ACL config error:', error);
            this.showValidationErrors(['Ошибка сети при сохранении настроек отображения']);
        });
    }

    // Отрисовка
    renderMap() {
        const map = document.getElementById('map');
        const deviceElements = map.querySelectorAll('.device-point, .device-label, .confidence-circle');
        deviceElements.forEach(element => element.remove());

        this.positions.forEach((data, deviceId) => {
            if (this.isDeviceAllowed(deviceId)) {
                this.updateDeviceOnMap(data);
            }
        });

        this.renderAnchorsOnMap();
    }

    renderAnchorsOnMap() {
        const container = document.getElementById('anchors-container');
        if (!container) return;

        container.innerHTML = '';

        Object.entries(this.anchorsConfig).forEach(([anchorId, config]) => {
            if (!config.enabled) return;

            const point = document.createElement('div');
            const anchorData = this.anchors.get(anchorId);
            const isActive = anchorData && anchorData.status === 'active';

            point.className = isActive ? 'anchor-point active' : 'anchor-point inactive';
            point.setAttribute('data-anchor-id', anchorId);

            const x = (config.x / this.roomConfig.width) * 100;
            const y = (config.y / this.roomConfig.height) * 100;

            point.style.left = `${x}%`;
            point.style.top = `${y}%`;

            const statusText = isActive ? 'АКТИВЕН' : 'НЕАКТИВЕН';
            const lastUpdate = anchorData ? new Date(anchorData.last_update).toLocaleTimeString() : 'нет данных';
            point.title = `${anchorId} (${statusText})\nКоординаты: (${config.x}, ${config.y}, ${config.z})\nПоследнее обновление: ${lastUpdate}\n\nКликните для деталей`;

            point.addEventListener('click', () => {
                this.showAnchorDetails(anchorId);
            });

            container.appendChild(point);
        });
    }

    renderAnchorsList() {
        const container = document.getElementById('anchors-list');
        if (!container) return;

        container.innerHTML = '';

        this.anchors.forEach((anchor, anchorId) => {
            const anchorElement = document.createElement('div');
            anchorElement.className = `anchor-item ${anchor.status === 'active' ? 'active' : 'inactive'}`;
            anchorElement.innerHTML = `
                <div class="anchor-header">
                    <span class="anchor-id">${anchorId}</span>
                    <span class="anchor-status ${anchor.status === 'active' ? 'status-active' : 'status-inactive'}">
                        ${anchor.status === 'active' ? 'АКТИВЕН' : 'НЕАКТИВЕН'}
                    </span>
                </div>
                <div class="anchor-coords">
                    X: ${anchor.x}, Y: ${anchor.y}, Z: ${anchor.z}
                </div>
                <div class="anchor-update">
                    Обновлен: ${new Date(anchor.last_update).toLocaleTimeString()}
                </div>
            `;
            container.appendChild(anchorElement);
        });
    }

    renderDevicesList() {
        const container = document.getElementById('devices-list');
        if (!container) return;

        container.innerHTML = '';

        this.devices.forEach((device, deviceId) => {
            if (!this.isDeviceAllowed(deviceId)) return;

            const position = this.positions.get(deviceId);
            const deviceElement = document.createElement('div');
            deviceElement.className = `device-item ${this.selectedDevice === deviceId ? 'selected' : ''}`;
            deviceElement.setAttribute('data-device-id', deviceId);

            let positionInfo = 'Позиция не определена';
            let confidenceInfo = '';

            if (position) {
                positionInfo = `X: ${position.position.x.toFixed(2)}, Y: ${position.position.y.toFixed(2)}, Z: ${position.position.z.toFixed(2)}`;
                confidenceInfo = `Доверие: ${(position.confidence * 100).toFixed(1)}%`;
            }

            const displayName = this.getDeviceDisplayName(deviceId, device);

            deviceElement.innerHTML = `
                <div class="device-header">
                    <span class="device-name">${displayName}</span>
                    <span class="device-type">${device.type || 'mobile_device'}</span>
                </div>
                <div class="device-mac">MAC: ${this.formatMacAddress(deviceId)}</div>
                <div class="device-position">${positionInfo}</div>
                <div class="device-confidence">${confidenceInfo}</div>
                <div class="device-first-seen">
                    Обнаружен: ${new Date(device.first_seen).toLocaleTimeString()}
                </div>
            `;

            deviceElement.addEventListener('click', () => {
                this.selectDevice(deviceId);
            });

            container.appendChild(deviceElement);
        });
    }

    renderDevicesOnMap() {
        // Создаем Set разрешенных устройств
        const allowedDevices = new Set();

        this.positions.forEach((data, deviceId) => {
            if (this.isDeviceAllowed(deviceId)) {
                allowedDevices.add(deviceId);
                this.updateDeviceOnMap(data);
            }
        });

        // Удаляем устройства которых нет в allowedDevices
        const devicePoints = document.querySelectorAll('.device-point');
        devicePoints.forEach(point => {
            const deviceId = point.getAttribute('data-device-id');
            if (!allowedDevices.has(deviceId)) {
                this.removeDeviceFromMap(deviceId);
            }
        });

        const confidenceCircles = document.querySelectorAll('.confidence-circle');
        confidenceCircles.forEach(circle => {
            const deviceId = circle.getAttribute('data-device-id');
            if (!allowedDevices.has(deviceId)) {
                circle.remove();
            }
        });
    }


    selectDevice(deviceId) {
        this.selectedDevice = deviceId;

        document.querySelectorAll('.device-item').forEach(item => {
            item.classList.remove('selected');
        });

        const selectedElement = document.querySelector(`[data-device-id="${deviceId}"]`);
        if (selectedElement) {
            selectedElement.classList.add('selected');
        }

        this.showPositionDetails(deviceId);
    }

    showPositionDetails(deviceId) {
        const device = this.devices.get(deviceId);
        const position = this.positions.get(deviceId);
        const detailsContainer = document.getElementById('position-details');

        if (!detailsContainer) return;

        if (!device || !position) {
            detailsContainer.innerHTML = '<div class="no-selection">Выберите устройство для просмотра деталей</div>';
            return;
        }

        const displayName = this.getDeviceDisplayName(deviceId, device);

        detailsContainer.innerHTML = `
            <h3>Детали позиции</h3>
            <div class="device-details">
                <p><strong>Имя:</strong> ${displayName}</p>
                <p><strong>MAC адрес:</strong> ${this.formatMacAddress(deviceId)}</p>
                <p><strong>SSID:</strong> ${device.ssid || 'Неизвестно'}</p>
                <p><strong>Тип:</strong> ${device.type || 'mobile_device'}</p>
                <p><strong>Первое обнаружение:</strong> ${new Date(device.first_seen).toLocaleString()}</p>
                <p><strong>Позиция:</strong> X: ${position.position.x.toFixed(2)}, Y: ${position.position.y.toFixed(2)}, Z: ${position.position.z.toFixed(2)}</p>
                <p><strong>Доверие:</strong> ${(position.confidence * 100).toFixed(1)}%</p>
                <p><strong>Якорей использовано:</strong> ${position.anchors_used}</p>
                <p><strong>Последнее обновление:</strong> ${new Date(position.timestamp).toLocaleString()}</p>
            </div>
        `;
    }

    clearPositionDetails() {
        const detailsContainer = document.getElementById('position-details');
        if (detailsContainer) {
            detailsContainer.innerHTML = '<div class="no-selection">Выберите устройство для просмотра деталей</div>';
        }
    }

    updateDeviceInList(deviceId, position, confidence) {
        const deviceElement = document.querySelector(`[data-device-id="${deviceId}"]`);
        if (!deviceElement) return;

        const positionElement = deviceElement.querySelector('.device-position');
        const confidenceElement = deviceElement.querySelector('.device-confidence');

        if (positionElement) {
            positionElement.textContent = `X: ${position.x.toFixed(2)}, Y: ${position.y.toFixed(2)}, Z: ${position.z.toFixed(2)}`;
        }

        if (confidenceElement) {
            confidenceElement.textContent = `Доверие: ${(confidence * 100).toFixed(1)}%`;
        }
    }

    updateDeviceOnMap(data) {
        const container = document.getElementById('devices-container');
        const confidenceContainer = document.getElementById('confidence-circles');
        if (!container || !confidenceContainer) return;

        let point = document.getElementById(`device-${data.device_id}`);
        let confidenceCircle = document.getElementById(`confidence-${data.device_id}`);

        // Если точки нет - создаем
        if (!point) {
            point = document.createElement('div');
            point.id = `device-${data.device_id}`;
            point.className = 'device-point';
            point.setAttribute('data-device-id', data.device_id);

            const deviceInfo = this.devices.get(data.device_id);
            const color = deviceInfo ? deviceInfo.color : '#3498db';
            point.style.background = color;
            point.style.border = `3px solid ${this.darkenColor(color, 20)}`;
            point.style.transition = `all ${this.animationDuration}ms ease-out`; // ДОБАВЬТЕ ПЕРЕХОД

            const label = document.createElement('div');
            label.className = 'device-label';
            point.appendChild(label);

            point.addEventListener('click', (e) => {
                e.stopPropagation();
                this.selectDevice(data.device_id);
            });

            container.appendChild(point);
        }

        // Если круга уверенности нет - создаем
        if (!confidenceCircle) {
            confidenceCircle = document.createElement('div');
            confidenceCircle.id = `confidence-${data.device_id}`;
            confidenceCircle.className = 'confidence-circle';
            confidenceCircle.setAttribute('data-device-id', data.device_id);
            confidenceCircle.style.transition = `all ${this.animationDuration}ms ease-out`; // ДОБАВЬТЕ ПЕРЕХОД
            confidenceContainer.appendChild(confidenceCircle);
        }

        // ОБНОВЛЯЕМ ПОЗИЦИИ С АНИМАЦИЕЙ
        const x = (data.position.x / this.roomConfig.width) * 100;
        const y = (data.position.y / this.roomConfig.height) * 100;

        // Плавное перемещение
        point.style.left = `${x}%`;
        point.style.top = `${y}%`;

        const radius = (1 - data.confidence) * 50 + 20;
        confidenceCircle.style.left = `${x}%`;
        confidenceCircle.style.top = `${y}%`;
        confidenceCircle.style.width = `${radius * 2}px`;
        confidenceCircle.style.height = `${radius * 2}px`;

        const confidenceClass = data.confidence > 0.8 ? 'confidence-high' :
                               data.confidence > 0.6 ? 'confidence-medium' : 'confidence-low';
        confidenceCircle.className = `confidence-circle ${confidenceClass}`;

        const showConfidence = document.getElementById('show-confidence').checked;
        confidenceCircle.style.display = showConfidence ? 'block' : 'none';

        // ОБНОВЛЯЕМ LABEL С SSID
        const deviceInfo = this.devices.get(data.device_id);
        const label = point.querySelector('.device-label');
        if (label) {
            label.textContent = this.getDeviceDisplayName(data.device_id, deviceInfo);
        }
    }

    removeDeviceFromMap(deviceId) {
        const point = document.getElementById(`device-${deviceId}`);
        const confidenceCircle = document.getElementById(`confidence-${deviceId}`);

        if (point) point.remove();
        if (confidenceCircle) confidenceCircle.remove();
    }

    showAnchorDetails(anchorId) {
        const anchor = this.anchors.get(anchorId);
        const config = this.anchorsConfig[anchorId];

        if (!anchor || !config) return;

        const details = `
            <h3>${anchorId}</h3>
            <div class="anchor-details">
                <p><strong>Статус:</strong> <span class="${anchor.status === 'active' ? 'status-active' : 'status-inactive'}">${anchor.status === 'active' ? 'АКТИВЕН' : 'НЕАКТИВЕН'}</span></p>
                <p><strong>Координаты:</strong> X: ${config.x}, Y: ${config.y}, Z: ${config.z}</p>
                <p><strong>Последнее обновление:</strong> ${new Date(anchor.last_update).toLocaleString()}</p>
                <p><strong>Количество измерений:</strong> ${anchor.measurements_count || 0}</p>
                <p><strong>Включен в системе:</strong> ${config.enabled ? 'Да' : 'Нет'}</p>
            </div>
        `;

        console.log('Anchor details:', details);
        this.addLog(`Детали якоря ${anchorId}: ${anchor.status === 'active' ? 'активен' : 'неактивен'}`, 'info');
    }

    // Вспомогательные методы
    formatMacAddress(mac) {
        if (mac.length <= 12) return mac;
        return mac.match(/.{1,2}/g).join(':').toUpperCase();
    }

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

    // Методы обновления UI
    updateSystemStatus(status) {
        const element = document.getElementById('system-status');
        if (element) {
            element.textContent = status;
            element.className = `status-value status-${status.toLowerCase()}`;
        }
    }

    updateSystemInfo(status) {
        if (status.total_updates !== undefined) {
            document.getElementById('total-updates').textContent = status.total_updates;
        }
        if (status.last_calculation) {
            document.getElementById('last-update').textContent =
                new Date(status.last_calculation).toLocaleTimeString();
        }
    }

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
        if (stats.active_anchors !== undefined) {
            document.getElementById('anchors-count').textContent = stats.active_anchors;
        }
    }

    updateAnchorsCount() {
        // Значение обновляется через updateStatistics
    }

    updateDevicesCount() {
        const countElement = document.getElementById('devices-count');
        if (countElement) {
            // Подсчитываем только разрешенные устройства
            let allowedCount = 0;
            this.devices.forEach((device, deviceId) => {
                if (this.isDeviceAllowed(deviceId)) {
                    allowedCount++;
                }
            });
            countElement.textContent = allowedCount;
        }
    }

    addLog(message, type = 'info') {
        const log = document.getElementById('system-log');
        if (log) {
            if (log.children.length > 50) {
                log.removeChild(log.children[1]);
            }

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

    requestInitialData() {
        if (!this.isSystemRunning()) return;

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
}

// Глобальные функции
window.togglePositioning = () => {
    if (app) app.togglePositioning();
};

window.openConfig = () => {
    if (app) app.openConfigurationModal();
};

window.closeConfigModal = () => {
    if (app) app.closeConfigModal();
};

window.saveRoomConfig = () => {
    if (app) app.saveRoomConfig();
};

window.saveAnchorsConfig = () => {
    if (app) app.saveAnchorsConfig();
};

window.saveACLConfig = () => {
    if (app) app.saveACLConfig();
};

window.openConfigTab = (tabName) => {
    document.querySelectorAll('.config-tab').forEach(tab => {
        tab.classList.remove('active');
    });

    document.querySelectorAll('.tab-button').forEach(button => {
        button.classList.remove('active');
    });

    document.getElementById(tabName).classList.add('active');
    event.target.classList.add('active');

    if (tabName === 'acl-tab' && app) {
        app.renderACLConfig();
    }
};

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

// Инициализация приложения
let app;
document.addEventListener('DOMContentLoaded', () => {
    app = new IndoorPositioningApp();
});