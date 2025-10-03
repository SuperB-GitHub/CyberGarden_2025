class EnhancedPositioningApp {
    constructor() {
        this.socket = io();
        this.roomConfig = {
            width: 20,
            height: 15
        };
        this.clients = new Map();
        this.positions = new Map();

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
            this.addLog('Connected to positioning server', 'success');
            this.updateSystemStatus('ONLINE');
        });

        this.socket.on('disconnect', () => {
            this.addLog('Disconnected from server', 'warning');
            this.updateSystemStatus('OFFLINE');
        });

        // Data events
        this.socket.on('anchors_data', (anchors) => {
            this.renderAnchors(anchors);
        });

        this.socket.on('clients_data', (clients) => {
            console.log('📋 Clients data received:', clients);
            this.updateClientsData(clients);
        });

        this.socket.on('positions_data', (positions) => {
            console.log('📍 Positions data received:', positions);
            this.updatePositionsData(positions);
        });

        this.socket.on('position_update', (data) => {
            console.log('🔄 Position update:', data);
            this.handlePositionUpdate(data);
        });

        this.socket.on('client_removed', (data) => {
            console.log('🗑️ Client removed:', data);
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
            this.addLog('System has been reset', 'info');
        });
    }

    updateClientsData(clients) {
        this.clients = new Map(Object.entries(clients));
        console.log('📊 Clients updated:', this.clients.size);
        this.renderClientsList();
        this.updateClientsCount();
    }

    updatePositionsData(positions) {
        this.positions = new Map(Object.entries(positions));
        console.log('📊 Positions updated:', this.positions.size);
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
            console.log('🚀 Starting simulation...');
            this.setButtonLoading('start-sim', true);
            this.socket.emit('start_simulation', {}, (response) => {
                console.log('Start simulation response:', response);
                this.setButtonLoading('start-sim', false);
            });
        };

        window.stopSimulation = () => {
            console.log('🛑 Stopping simulation...');
            this.setButtonLoading('stop-sim', true);
            this.socket.emit('stop_simulation', {}, (response) => {
                console.log('Stop simulation response:', response);
                this.setButtonLoading('stop-sim', false);
            });
        };

        window.addRobot = () => {
            console.log('🤖 Adding robot...');
            this.setButtonLoading('add-robot', true);
            this.socket.emit('add_robot', {}, (response) => {
                console.log('Add robot response:', response);
                this.setButtonLoading('add-robot', false);
            });
        };

        window.addHuman = () => {
            console.log('👤 Adding human...');
            this.setButtonLoading('add-human', true);
            this.socket.emit('add_human', {}, (response) => {
                console.log('Add human response:', response);
                this.setButtonLoading('add-human', false);
            });
        };

        window.resetSystem = () => {
            if (confirm('Are you sure you want to reset the system? All clients will be removed.')) {
                this.setButtonLoading('reset-btn', true);
                fetch('/api/control', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ command: 'reset' })
                }).then(response => response.json())
                  .then(data => {
                      console.log('Reset response:', data);
                      this.setButtonLoading('reset-btn', false);
                  })
                  .catch(error => {
                      this.addLog('Reset failed: ' + error, 'error');
                      this.setButtonLoading('reset-btn', false);
                  });
            }
        };

        // Быстрые действия
        window.addMultipleRobots = (count) => {
            this.addLog(`Adding ${count} robots...`, 'info');
            for (let i = 0; i < count; i++) {
                setTimeout(() => {
                    this.socket.emit('add_robot', {});
                }, i * 300);
            }
        };

        window.addMultipleHumans = (count) => {
            this.addLog(`Adding ${count} humans...`, 'info');
            for (let i = 0; i < count; i++) {
                setTimeout(() => {
                    this.socket.emit('add_human', {});
                }, i * 300);
            }
        };

        window.removeAllClients = () => {
            const clientCount = this.clients.size;
            if (clientCount === 0) {
                this.addLog('No clients to remove', 'warning');
                return;
            }

            if (confirm(`Remove all ${clientCount} clients from the system?`)) {
                this.clients.forEach((client, deviceId) => {
                    this.socket.emit('remove_client', { device_id: deviceId });
                });
                this.addLog(`Removal initiated for ${clientCount} clients`, 'info');
            }
        };

        window.clearLog = () => {
            const logContainer = document.getElementById('system-log');
            const startTimeElement = document.getElementById('start-time');
            const startTime = startTimeElement.textContent;

            logContainer.innerHTML = `
                <div class="log-entry">
                    <span class="log-time">${startTime}</span>
                    <span class="log-message log-type-info">Log cleared</span>
                </div>
            `;
        };
    }

    setButtonLoading(buttonId, isLoading) {
        const button = document.getElementById(buttonId);
        if (!button) return;

        if (isLoading) {
            button.disabled = true;
            button.style.opacity = '0.6';
            button.innerHTML = '⏳ Loading...';
        } else {
            button.disabled = false;
            button.style.opacity = '1';
            // Восстанавливаем оригинальный текст кнопки
            const originalText = {
                'start-sim': '▶ Start Simulation',
                'stop-sim': '⏹ Stop Simulation',
                'add-robot': '🤖 Add Robot',
                'add-human': '👤 Add Human',
                'reset-btn': '🔄 Reset System'
            }[buttonId];
            if (originalText) {
                button.innerHTML = originalText;
            }
        }
    }

    renderMap() {
        const map = document.getElementById('map');

        // Сохраняем легенду если она существует
        const existingLegend = document.querySelector('.map-legend');

        // Очищаем только клиентов и якоря, но не легенду
        const elementsToRemove = map.querySelectorAll('.anchor-point, .client-point, .client-label, .confidence-bar');
        elementsToRemove.forEach(element => element.remove());

        // Re-render all clients on map
        this.positions.forEach((data, deviceId) => {
            this.updateClientOnMap(data);
        });

        // Если легенда была удалена, восстанавливаем её
        if (!existingLegend && !document.querySelector('.map-legend')) {
            this.addMapLegend();
        }
    }

    renderAnchors(anchors) {
        const map = document.getElementById('map');

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

        this.addLog(`Anchors placed: ${Object.keys(anchors).length}`, 'info');
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

        console.log('🔄 Rendering clients list:', this.clients.size, 'clients');

        this.clients.forEach((client, deviceId) => {
            const position = this.positions.get(deviceId);
            const clientElement = document.createElement('div');
            clientElement.className = `client-item client-${client.type}`;
            clientElement.setAttribute('data-device-id', deviceId);

            const positionText = position ?
                `(${position.position.x.toFixed(1)}, ${position.position.y.toFixed(1)})` :
                'No position data';

            clientElement.innerHTML = `
                <div class="client-info">
                    <div class="client-name">${deviceId}</div>
                    <div class="client-type">${client.type.toUpperCase()}</div>
                </div>
                <div class="client-position">${positionText}</div>
                <button class="remove-btn" onclick="app.removeClient('${deviceId}')" title="Remove client">
                    ×
                </button>
            `;
            container.appendChild(clientElement);
        });

        this.updateClientsCount();
    }

    removeClient(deviceId) {
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
        this.addLog(`Client ${deviceId} removed`, 'info');
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
            console.log('👥 Clients count updated:', this.clients.size);
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
                z-index: 1000; /* Увеличиваем z-index */
                border: 1px solid #ddd;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            `;
            legend.innerHTML = `
                <div style="font-weight: bold; margin-bottom: 5px; color: #2c3e50;">Legend</div>
                <div style="display: flex; align-items: center; margin: 3px 0;">
                    <div style="width: 12px; height: 12px; background: #e74c3c; border: 2px solid #c0392b; border-radius: 50%; margin-right: 8px;"></div>
                    <span style="color: #2c3e50;">Anchor</span>
                </div>
                <div style="display: flex; align-items: center; margin: 3px 0;">
                    <div style="width: 12px; height: 12px; background: #e74c3c; border: 2px solid #c0392b; border-radius: 50%; margin-right: 8px;"></div>
                    <span style="color: #2c3e50;">Robot</span>
                </div>
                <div style="display: flex; align-items: center; margin: 3px 0;">
                    <div style="width: 12px; height: 12px; background: #3498db; border: 2px solid #2980b9; border-radius: 50%; margin-right: 8px;"></div>
                    <span style="color: #2c3e50;">Human</span>
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