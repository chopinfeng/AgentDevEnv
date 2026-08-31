/*
 * AgentDevEnv —— ESP32 设备端固件（min 方言）
 *
 * 设备不做 Agent，只做"手和眼"：把本机能力声明成工具，等云端 Agent 调用。
 * 依据：ESP32-S3 上跑 260K 参数模型约 19 tok/s，29M 参数约 9.5 tok/s ——
 * 这个量级没有指令跟随与工具调用能力，Agent 循环必须在云端。
 *
 * 依赖（Arduino 库管理器安装）：
 *   - WebSockets by Markus Sattler   (arduinoWebSockets)
 *   - ArduinoJson by Benoit Blanchon (v7)
 *
 * 内存占用很小：不实现 JSON-RPC、不做 schema 协商、不维护 session。
 * 工具 schema 是编译期常量字符串，不占堆。
 *
 * 若设备已经在跑 Espressif 官方 mcp-c-sdk 或小智固件，
 * 改用 dialect=mcp 连接即可，云端会以 MCP Client 身份发 tools/list。
 */

#include <WiFi.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>

// ── 配置 ─────────────────────────────────────────────────────
static const char* WIFI_SSID = "your-ssid";
static const char* WIFI_PASS = "your-password";

static const char* AGENT_HOST = "api.yourdomain.com";
static const uint16_t AGENT_PORT = 443;
static const bool AGENT_TLS = true;

// 设备挂到哪个 Agent 会话；device 是本机标识，会成为工具名前缀
static const char* DEVICE_ID = "lamp-01";
static const char* AGENT_PATH =
    "/agents/main-agent/home?role=device&dialect=min&device=lamp-01";

static const int LED_PIN = 2;

// ── 能力声明 ─────────────────────────────────────────────────
// 编译期常量：不占堆，MCU 上这点很重要。
static const char* HELLO_FRAME =
    "{\"t\":\"hello\",\"device\":\"lamp-01\",\"tools\":["
    "{\"name\":\"set_lamp\",\"description\":\"开关灯。on=true 开，false 关。\","
    "\"schema\":{\"type\":\"object\",\"properties\":{\"on\":{\"type\":\"boolean\"}},"
    "\"required\":[\"on\"]}},"
    "{\"name\":\"read_temp\",\"description\":\"读取当前温度，单位摄氏度。\","
    "\"schema\":{\"type\":\"object\",\"properties\":{}}}"
    "]}";

WebSocketsClient ws;

// ── 工具实现 ─────────────────────────────────────────────────

static void sendResult(const char* id, bool ok, const char* data) {
  JsonDocument doc;
  doc["t"] = "result";
  doc["id"] = id;
  doc["ok"] = ok;
  doc["data"] = data;

  String out;
  serializeJson(doc, out);
  ws.sendTXT(out);
}

/** 主动上报事件（按钮、传感器越限）。云端会落库供 Agent 后续引用。 */
static void sendEvent(const char* name, const char* data) {
  JsonDocument doc;
  doc["t"] = "event";
  doc["name"] = name;
  doc["data"] = data;

  String out;
  serializeJson(doc, out);
  ws.sendTXT(out);
}

static void handleInvoke(JsonDocument& doc) {
  const char* id = doc["id"];
  const char* tool = doc["tool"];
  if (!id || !tool) return;

  if (strcmp(tool, "set_lamp") == 0) {
    bool on = doc["args"]["on"] | false;
    digitalWrite(LED_PIN, on ? HIGH : LOW);
    sendResult(id, true, on ? "灯已打开" : "灯已关闭");

  } else if (strcmp(tool, "read_temp") == 0) {
    // 换成真实传感器读数
    float celsius = temperatureRead();
    char buf[32];
    snprintf(buf, sizeof(buf), "%.1f°C", celsius);
    sendResult(id, true, buf);

  } else {
    sendResult(id, false, "unknown tool");
  }
}

// ── WebSocket 事件 ───────────────────────────────────────────

static void onWsEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      Serial.println("[ws] connected, sending hello");
      ws.sendTXT(HELLO_FRAME);   // min 方言：设备主动声明能力
      break;

    case WStype_DISCONNECTED:
      Serial.println("[ws] disconnected");
      break;

    case WStype_TEXT: {
      JsonDocument doc;
      if (deserializeJson(doc, payload, length)) {
        Serial.println("[ws] bad json");
        return;
      }
      const char* t = doc["t"];
      if (t && strcmp(t, "invoke") == 0) handleInvoke(doc);
      break;
    }

    default:
      break;
  }
}

// ── 主流程 ───────────────────────────────────────────────────

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\n[wifi] %s\n", WiFi.localIP().toString().c_str());

  if (AGENT_TLS) {
    ws.beginSSL(AGENT_HOST, AGENT_PORT, AGENT_PATH);
  } else {
    ws.begin(AGENT_HOST, AGENT_PORT, AGENT_PATH);
  }
  ws.onEvent(onWsEvent);
  // 断线自动重连。云端 DO 侧连接标签会持久化，重连后身份仍然成立。
  ws.setReconnectInterval(5000);
  // 心跳：保活并及时发现掉线
  ws.enableHeartbeat(15000, 3000, 2);
}

void loop() {
  ws.loop();
}
