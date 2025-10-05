#include <WiFi.h>
#include <HTTPClient.h>
#include <esp_wifi.h>
#include <vector>
#include <map>

// Конфигурация сервера
const char* serverURL = "http://192.168.0.244:5000";
String anchor_id = "Якорь_2";

// Данные WiFi
const char* wifi_ssid = "DESKTOP-JVL1750 9295";
const char* wifi_password = "^74b470T";

// Расширенная структура для хранения данных устройства
struct DeviceInfo {
  String mac;
  String ssid;        // Добавлено поле для SSID
  bool hidden_ssid;   // Флаг скрытого SSID
  int rssi;
  float distance;
  unsigned long lastSeen;
  bool active;
  int channel;
  float rssi_filtered; // Отфильтрованное значение RSSI
  int packet_count;    // Количество измерений
  long timestamp;      // Точное время последнего измерения
};

// Динамический массив вместо фиксированного
std::vector<DeviceInfo> devices;

// Калибровочные параметры для разных частот
struct ChannelCalibration {
  int channel;
  float n;  // Коэффициент затухания
  float A;  // RSSI на 1 метре
};

ChannelCalibration channelCalibrations[] = {
  {1, 2.2, -45},  // 2.4 GHz
  {6, 2.3, -45},  // 2.4 GHz  
  {11, 2.4, -45}, // 2.4 GHz
  {36, 2.1, -40}, // 5 GHz
  {40, 2.1, -40}, // 5 GHz
  {44, 2.1, -40}, // 5 GHz
  {48, 2.1, -40}  // 5 GHz
};

// Упрощенный фильтр Калмана для RSSI
class KalmanFilter {
private:
  float Q = 0.1;  // Шум процесса
  float R = 2.0;  // Шум измерения
  float P = 1.0;  // Ковариация ошибки
  float X = 0.0;  // Оценка
  
public:
  float update(float measurement) {
    // Прогноз
    P = P + Q;
    
    // Коррекция
    float K = P / (P + R);
    X = X + K * (measurement - X);
    P = (1 - K) * P;
    
    return X;
  }
  
  void reset() {
    P = 1.0;
    X = 0.0;
  }
};

std::map<String, KalmanFilter> kalmanFilters;

WiFiClient wifiClient;

void setup() {
  Serial.begin(115200);
  delay(2000);
  
  Serial.println("🚀 Starting ESP32 Anchor (Improved Version)...");
  
  // Настройка WiFi для лучшего сканирования
  WiFi.mode(WIFI_STA);
  
  // Улучшенные настройки WiFi для точного сканирования
  esp_wifi_set_protocol(WIFI_IF_STA, WIFI_PROTOCOL_11B | WIFI_PROTOCOL_11G | WIFI_PROTOCOL_11N | WIFI_PROTOCOL_LR);
  esp_wifi_set_bandwidth(WIFI_IF_STA, WIFI_BW_HT20);
  
  Serial.printf("📶 Connecting to WiFi: %s\n", wifi_ssid);
  WiFi.begin(wifi_ssid, wifi_password);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(1000);
    Serial.print(".");
    attempts++;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n✅ WiFi connected successfully!");
    Serial.printf("  - IP Address: %s\n", WiFi.localIP().toString().c_str());
    Serial.printf("  - RSSI: %d dBm\n", WiFi.RSSI());
  } else {
    Serial.println("\n❌ WiFi connection failed!");
    return;
  }
  
  // Резервируем память для устройств
  devices.reserve(50);
  
  Serial.println("✅ System initialized and ready for scanning");
}

void loop() {
  static unsigned long lastScan = 0;
  unsigned long currentTime = millis();
  
  if (currentTime - lastScan > 2000) {
    Serial.println("\n=== SCAN CYCLE START ===");
    scanForDevices();
    sendDataToServer();
    lastScan = currentTime;
    Serial.println("=== SCAN CYCLE END ===\n");
  }
  
  static unsigned long lastCleanup = 0;
  if (currentTime - lastCleanup > 15000) {
    cleanupOldDevices();
    lastCleanup = currentTime;
  }
  
  delay(100);
}

void scanForDevices() {
  Serial.println("🔍 Starting advanced WiFi scan...");
  
  int scanResult = WiFi.scanNetworks(false, true);
  Serial.printf("  - Found %d networks\n", scanResult);
  
  if (scanResult == 0) {
    Serial.println("  - No networks found");
    return;
  }
  
  int newDevices = 0;
  int updatedDevices = 0;
  
  for (int i = 0; i < scanResult; ++i) {
    String mac = WiFi.BSSIDstr(i);
    String ssid = WiFi.SSID(i);  // Получаем SSID
    int rssi = WiFi.RSSI(i);
    int channel = WiFi.channel(i);
    
    if (mac.length() == 0 || isOurOwnDevice(mac)) {
      continue;
    }
    
    // Определяем, является ли SSID скрытым
    bool hidden_ssid = (ssid.length() == 0);
    
    // Для скрытых сетей используем специальное обозначение
    if (hidden_ssid) {
      ssid = "<Hidden_Network>";
    }
    
    if (updateDevice(mac, ssid, hidden_ssid, rssi, channel)) {
      newDevices++;
    } else {
      updatedDevices++;
    }
  }
  
  Serial.printf("  - New devices: %d\n", newDevices);
  Serial.printf("  - Updated devices: %d\n", updatedDevices);
  Serial.printf("  - Total active devices: %d\n", devices.size());
  
  WiFi.scanDelete();
}

bool updateDevice(String mac, String ssid, bool hidden_ssid, int rssi, int channel) {
  // Применяем фильтр Калмана к RSSI
  if (kalmanFilters.find(mac) == kalmanFilters.end()) {
    kalmanFilters[mac] = KalmanFilter();
  }
  
  float filtered_rssi = kalmanFilters[mac].update(rssi);
  
  // Ищем существующее устройство
  for(auto& device : devices) {
    if(device.active && device.mac == mac) {
      device.rssi = rssi;
      device.rssi_filtered = filtered_rssi;
      device.distance = calculateDistance(filtered_rssi, channel);
      device.lastSeen = millis();
      device.packet_count++;
      device.timestamp = esp_timer_get_time() / 1000; // мс
      
      // Обновляем SSID только если он был скрытым, а теперь стал известным
      if (device.hidden_ssid && !hidden_ssid) {
        device.ssid = ssid;
        device.hidden_ssid = false;
        Serial.printf("  - Revealed hidden SSID for %s: %s\n", mac.c_str(), ssid.c_str());
      }
      
      Serial.printf("  - Updated device: %s, SSID: %s, RSSI: %d (filtered: %.1f), Distance: %.2fm, Channel: %d\n", 
                   mac.c_str(), device.ssid.c_str(), rssi, filtered_rssi, device.distance, channel);
      return false;
    }
  }
  
  // Добавляем новое устройство
  DeviceInfo newDevice;
  newDevice.mac = mac;
  newDevice.ssid = ssid;
  newDevice.hidden_ssid = hidden_ssid;
  newDevice.rssi = rssi;
  newDevice.rssi_filtered = filtered_rssi;
  newDevice.channel = channel;
  newDevice.distance = calculateDistance(filtered_rssi, channel);
  newDevice.lastSeen = millis();
  newDevice.active = true;
  newDevice.packet_count = 1;
  newDevice.timestamp = esp_timer_get_time() / 1000;
  
  devices.push_back(newDevice);
  
  Serial.printf("  - NEW DEVICE: %s, SSID: %s, RSSI: %d (filtered: %.1f), Distance: %.2fm, Channel: %d\n", 
               mac.c_str(), ssid.c_str(), rssi, filtered_rssi, newDevice.distance, channel);
  return true;
}

float calculateDistance(float rssi, int channel) {
  // Получаем калибровочные параметры для канала
  float n = 2.5; // по умолчанию
  float A = -45; // по умолчанию
  
  for(const auto& cal : channelCalibrations) {
    if(cal.channel == channel) {
      n = cal.n;
      A = cal.A;
      break;
    }
  }
  
  if (rssi >= A) {
    return 0.1;
  }
  
  // Улучшенная формула с учетом разных частот
  float distance = pow(10, (A - rssi) / (10 * n));
  
  // Корректировка для 5GHz каналов
  if (channel > 14) {
    distance *= 0.9; // 5GHz сигналы затухают быстрее
  }
  
  // Ограничения
  if (distance > 50.0) distance = 50.0;
  if (distance < 0.1) distance = 0.1;
  
  return distance;
}

void sendDataToServer() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("❌ WiFi not connected, cannot send data");
    return;
  }
  
  HTTPClient http;
  
  String jsonData = "{\"anchor_id\":\"" + anchor_id + "\",\"timestamp\":" + 
                    String(millis()) + ",\"measurements\":[";
  
  bool first = true;
  
  for(const auto& device : devices) {
    if(device.active) {
      if(!first) jsonData += ",";
      jsonData += "{\"mac\":\"" + device.mac + 
                  "\",\"ssid\":\"" + device.ssid + 
                  "\",\"hidden_ssid\":" + String(device.hidden_ssid ? "true" : "false") +
                  ",\"rssi\":" + String(device.rssi) + 
                  ",\"rssi_filtered\":" + String(device.rssi_filtered, 1) +
                  ",\"distance\":" + String(device.distance, 2) +
                  ",\"channel\":" + String(device.channel) +
                  ",\"packet_count\":" + String(device.packet_count) +
                  ",\"device_timestamp\":" + String(device.timestamp) + "}";
      first = false;
    }
  }
  
  jsonData += "]}";
  
  String fullURL = String(serverURL) + "/api/anchor_data";
  
  Serial.printf("📡 Sending data to server:\n");
  Serial.printf("  - URL: %s\n", fullURL.c_str());
  Serial.printf("  - Active devices: %d\n", devices.size());
  
  http.begin(wifiClient, fullURL);
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(5000);
  
  int httpResponseCode = http.POST(jsonData);
  
  if (httpResponseCode > 0) {
    Serial.printf("✅ Data sent successfully: HTTP %d\n", httpResponseCode);
    String response = http.getString();
    Serial.printf("  - Server response: %s\n", response.c_str());
  } else {
    Serial.printf("❌ Send error: %d\n", httpResponseCode);
    Serial.printf("  - Error: %s\n", http.errorToString(httpResponseCode).c_str());
  }
  
  http.end();
}

void cleanupOldDevices() {
  unsigned long currentTime = millis();
  int removedCount = 0;
  
  for(auto it = devices.begin(); it != devices.end();) {
    if(it->active && (currentTime - it->lastSeen > 15000)) {
      Serial.printf("🗑️ Device removed (timeout): %s (SSID: %s)\n", it->mac.c_str(), it->ssid.c_str());
      // Удаляем также фильтр Калмана
      kalmanFilters.erase(it->mac);
      it = devices.erase(it);
      removedCount++;
    } else {
      ++it;
    }
  }
  
  if (removedCount > 0) {
    Serial.printf("  - Total devices removed: %d\n", removedCount);
  }
}

bool isOurOwnDevice(String mac) {
  String ourMacs[] = {
    "AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02", 
    "AA:BB:CC:DD:EE:03", "AA:BB:CC:DD:EE:04"
  };
  
  for (String ourMac : ourMacs) {
    if (mac == ourMac) {
      return true;
    }
  }
  return false;
}