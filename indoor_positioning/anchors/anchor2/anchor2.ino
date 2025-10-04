#include <WiFi.h>
#include <HTTPClient.h>

// Конфигурация сервера
const char* serverURL = "http://192.168.0.244:5000";
String anchor_id = "Якорь_2";

// Данные WiFi
const char* wifi_ssid = "DESKTOP-JVL1750 9295";
const char* wifi_password = "^74b470T";

WiFiClient wifiClient;

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
  
  Serial.println("🚀 Starting ESP32 Anchor...");
  Serial.println("📋 System Information:");
  Serial.printf("  - Anchor ID: %s\n", anchor_id.c_str());
  Serial.printf("  - Server URL: %s\n", serverURL);
  Serial.printf("  - Max devices: %d\n", maxDevices);
  
  WiFi.mode(WIFI_STA);
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
  
  // Инициализация устройств
  for(int i = 0; i < maxDevices; i++) {
    devices[i].active = false;
  }
  
  Serial.println("✅ System initialized and ready for scanning");
}

void loop() {
  static unsigned long lastScan = 0;
  if (millis() - lastScan > 2000) {
    Serial.println("\n=== SCAN CYCLE START ===");
    scanForDevices();
    sendDataToServer();
    lastScan = millis();
    Serial.println("=== SCAN CYCLE END ===\n");
  }
  
  static unsigned long lastCleanup = 0;
  if (millis() - lastCleanup > 15000) {
    cleanupOldDevices();
    lastCleanup = millis();
  }
  
  delay(100);
}

void scanForDevices() {
  Serial.println("🔍 Starting WiFi scan...");
  
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
    int rssi = WiFi.RSSI(i);
    
    if (mac.length() == 0 || isOurOwnDevice(mac)) {
      continue;
    }
    
    if (updateDevice(mac, rssi)) {
      newDevices++;
    } else {
      updatedDevices++;
    }
  }
  
  Serial.printf("  - New devices: %d\n", newDevices);
  Serial.printf("  - Updated devices: %d\n", updatedDevices);
  Serial.printf("  - Total active devices: %d\n", countActiveDevices());
  
  WiFi.scanDelete();
}

bool isOurOwnDevice(String mac) {
  String ourMacs[] = {
    "AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02", 
    "AA:BB:CC:DD:EE:03", "AA:BB:CC:DD:EE:04"
  };
  
  for (String ourMac : ourMacs) {
    if (mac == ourMac) {
      Serial.printf("  - Ignoring our own device: %s\n", mac.c_str());
      return true;
    }
  }
  return false;
}

bool updateDevice(String mac, int rssi) {
  // Ищем существующее устройство
  for(int i = 0; i < maxDevices; i++) {
    if(devices[i].active && devices[i].mac == mac) {
      devices[i].rssi = rssi;
      devices[i].distance = calculateDistance(rssi);
      devices[i].lastSeen = millis();
      Serial.printf("  - Updated device: %s, RSSI: %d, Distance: %.2fm\n", 
                   mac.c_str(), rssi, devices[i].distance);
      return false;
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
      
      Serial.printf("  - NEW DEVICE: %s, RSSI: %d, Distance: %.2fm\n", 
                   mac.c_str(), rssi, devices[i].distance);
      return true;
    }
  }
  
  Serial.printf("  - Device list full, cannot add: %s\n", mac.c_str());
  return false;
}

void sendDataToServer() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("❌ WiFi not connected, cannot send data");
    return;
  }
  
  HTTPClient http;
  
  String jsonData = "{\"anchor_id\":\"" + anchor_id + "\",\"measurements\":[";
  
  bool first = true;
  int activeCount = 0;
  
  for(int i = 0; i < maxDevices; i++) {
    if(devices[i].active) {
      if(!first) jsonData += ",";
      jsonData += "{\"mac\":\"" + devices[i].mac + 
                  "\",\"rssi\":" + String(devices[i].rssi) + 
                  ",\"distance\":" + String(devices[i].distance) + "}";
      first = false;
      activeCount++;
    }
  }
  
  jsonData += "]}";
  
  String fullURL = String(serverURL) + "/api/anchor_data";
  
  Serial.printf("📡 Sending data to server:\n");
  Serial.printf("  - URL: %s\n", fullURL.c_str());
  Serial.printf("  - Active devices: %d\n", activeCount);
  Serial.printf("  - Data size: %d bytes\n", jsonData.length());
  
  if (activeCount > 0) {
    Serial.printf("  - JSON data: %s\n", jsonData.c_str());
  }
  
  http.begin(wifiClient, fullURL);
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(5000);
  
  Serial.println("  - Sending HTTP POST request...");
  int httpResponseCode = http.POST(jsonData);
  
  if (httpResponseCode > 0) {
    Serial.printf("✅ Data sent successfully: HTTP %d\n", httpResponseCode);
    
    // Читаем ответ сервера
    String response = http.getString();
    Serial.printf("  - Server response: %s\n", response.c_str());
  } else {
    Serial.printf("❌ Send error: %d\n", httpResponseCode);
    Serial.printf("  - Error description: %s\n", http.errorToString(httpResponseCode).c_str());
  }
  
  http.end();
}

void cleanupOldDevices() {
  unsigned long currentTime = millis();
  int removedCount = 0;
  
  for(int i = 0; i < maxDevices; i++) {
    if(devices[i].active && (currentTime - devices[i].lastSeen > 15000)) {
      Serial.printf("🗑️ Device removed (timeout): %s\n", devices[i].mac.c_str());
      devices[i].active = false;
      removedCount++;
    }
  }
  
  if (removedCount > 0) {
    Serial.printf("  - Total devices removed: %d\n", removedCount);
  }
}

int countActiveDevices() {
  int count = 0;
  for(int i = 0; i < maxDevices; i++) {
    if(devices[i].active) count++;
  }
  return count;
}

float calculateDistance(int rssi) {
  float n = 2.5;
  float A = -45;
  
  if (rssi >= A) {
    Serial.printf("  - RSSI %d >= reference %d, using minimum distance\n", rssi, A);
    return 0.1;
  }
  
  float distance = pow(10, (A - rssi) / (10 * n));
  
  if (distance > 20.0) distance = 20.0;
  if (distance < 0.1) distance = 0.1;
  
  Serial.printf("  - RSSI: %d dBm -> Distance: %.2f m\n", rssi, distance);
  return distance;
}