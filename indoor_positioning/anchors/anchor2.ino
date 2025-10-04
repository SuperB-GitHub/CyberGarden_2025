#include <WiFi.h>
#include <HTTPClient.h>

// Конфигурация сервера
const char* serverURL = "http://192.168.0.244:5000";

// Координаты якоря
float anchor_x = 20.0;
float anchor_y = 0.0;  
float anchor_z = 2.5;
String anchor_id = "Якорь_2";

// Данные WiFi для подключения к роутеру
const char* wifi_ssid = "DESKTOP-JVL1750 9295";
const char* wifi_password = "^74b470T";

WiFiClient wifiClient;

// Структура для обнаруженных устройств
struct DeviceInfo {
  String mac;
  int rssi;
  float distance;
  unsigned long lastSeen;
  bool active;
};

DeviceInfo devices[10];
int maxDevices = 10;

void setup() {
  Serial.begin(115200);
  delay(2000);
  
  Serial.println("🚀 Starting ESP32 Anchor (WiFi Scanner only)...");
  
  // Только STA режим - подключаемся к роутеру
  WiFi.mode(WIFI_STA);
  
  Serial.println("📶 Connecting to WiFi...");
  WiFi.begin(wifi_ssid, wifi_password);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(1000);
    Serial.print(".");
    attempts++;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n✅ Connected to WiFi!");
    Serial.print("📡 IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\n❌ Failed to connect to WiFi");
  }
  
  // Инициализация устройств
  for(int i = 0; i < maxDevices; i++) {
    devices[i].active = false;
  }
  
  Serial.println("✅ System ready for scanning");
}

void loop() {
  // Сканируем WiFi сети каждые 2 секунды (было 3)
  static unsigned long lastScan = 0;
  if (millis() - lastScan > 2000) {
    scanForDevices();
    sendDataToServer();
    lastScan = millis();
  }
  
  // Очищаем старые устройства каждые 15 секунд (было 10)
  static unsigned long lastCleanup = 0;
  if (millis() - lastCleanup > 15000) {
    cleanupOldDevices();
    lastCleanup = millis();
  }
  
  delay(100);
}

void scanForDevices() {
  Serial.println("🔍 Scanning for WiFi devices...");
  
  int scanResult = WiFi.scanNetworks(false, true); // async, show hidden
  
  if (scanResult == 0) {
    Serial.println("❌ No networks found");
    return;
  }
  
  for (int i = 0; i < scanResult; ++i) {
    String mac = WiFi.BSSIDstr(i);
    int rssi = WiFi.RSSI(i);
    
    // Игнорируем наши якоря и роутеры
    if (mac.length() == 0 || isOurOwnDevice(mac)) {
      continue;
    }
    
    // Обновляем или добавляем устройство
    updateDevice(mac, rssi);
  }
  
  WiFi.scanDelete();
  printDevicesStatus();
}

bool isOurOwnDevice(String mac) {
  // Игнорируем MAC-адреса наших ESP32 якорей
  String ourMacs[] = {
    "AA:BB:CC:DD:EE:01", // Якорь_1
    "AA:BB:CC:DD:EE:02", // Якорь_2  
    "AA:BB:CC:DD:EE:03", // Якорь_3
    "AA:BB:CC:DD:EE:04"  // Якорь_4
  };
  
  for (String ourMac : ourMacs) {
    if (mac == ourMac) {
      return true;
    }
  }
  return false;
}

void updateDevice(String mac, int rssi) {
  // Ищем существующее устройство
  for(int i = 0; i < maxDevices; i++) {
    if(devices[i].active && devices[i].mac == mac) {
      devices[i].rssi = rssi;
      devices[i].distance = calculateDistance(rssi);
      devices[i].lastSeen = millis();
      return;
    }
  }
  
  // Добавляем новое устройство
  for(int i = 0; i < maxDevices; i++) {
    if(!devices[i].active) {
      devices[i].mac = mac;
      devices[i].rssi = rssi;
      devices[i].distance = calculateDistance(rssi);
      devices[i].lastSeen = millis();
      devices[i].active = true;
      
      Serial.print("✅ NEW DEVICE: ");
      Serial.print(mac);
      Serial.print(" | RSSI: ");
      Serial.print(rssi);
      Serial.print(" dBm | Distance: ");
      Serial.print(devices[i].distance);
      Serial.println(" m");
      return;
    }
  }
}

void sendDataToServer() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("❌ WiFi not connected");
    return;
  }
  
  HTTPClient http;
  
  // Формируем JSON с данными измерений
  String jsonData = "{\"anchor_id\":\"" + anchor_id + 
                    "\",\"x\":" + String(anchor_x) + 
                    ",\"y\":" + String(anchor_y) + 
                    ",\"z\":" + String(anchor_z) + 
                    ",\"measurements\":[";
  
  bool first = true;
  for(int i = 0; i < maxDevices; i++) {
    if(devices[i].active) {
      if(!first) jsonData += ",";
      jsonData += "{\"mac\":\"" + devices[i].mac + 
                  "\",\"rssi\":" + String(devices[i].rssi) + 
                  ",\"distance\":" + String(devices[i].distance) + "}";
      first = false;
    }
  }
  
  jsonData += "]}";
  
  String fullURL = String(serverURL) + "/api/anchor_data";
  
  if (!first) { // Если есть данные
    Serial.println("📡 Sending data: " + jsonData);
  }
  
  http.begin(wifiClient, fullURL);
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(10000);
  
  int httpResponseCode = http.POST(jsonData);
  
  if (httpResponseCode > 0) {
    Serial.println("✅ Data sent: HTTP " + String(httpResponseCode));
  } else {
    Serial.println("❌ Send error: " + String(httpResponseCode));
  }
  
  http.end();
}

void cleanupOldDevices() {
  unsigned long currentTime = millis();
  for(int i = 0; i < maxDevices; i++) {
    if(devices[i].active && (currentTime - devices[i].lastSeen > 15000)) {
      Serial.print("🗑️ Device removed: ");
      Serial.println(devices[i].mac);
      devices[i].active = false;
    }
  }
}

void printDevicesStatus() {
  int activeCount = 0;
  for(int i = 0; i < maxDevices; i++) {
    if(devices[i].active) activeCount++;
  }
  
  if (activeCount > 0) {
    Serial.println("=== DEVICES: " + String(activeCount) + " ===");
    for(int i = 0; i < maxDevices; i++) {
      if(devices[i].active) {
        Serial.print("  ");
        Serial.print(devices[i].mac);
        Serial.print(" | RSSI: ");
        Serial.print(devices[i].rssi);
        Serial.print(" dBm | ");
        Serial.print(devices[i].distance);
        Serial.println(" m");
      }
    }
  }
}

float calculateDistance(int rssi) {
  float n = 2.5;
  float A = -45;
  
  if (rssi >= A) return 0.1;
  
  float distance = pow(10, (A - rssi) / (10 * n));
  
  if (distance > 20.0) distance = 20.0;
  if (distance < 0.1) distance = 0.1;
  
  return distance;
}