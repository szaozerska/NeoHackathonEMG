// Arduino-ESP32 3.3.11; ESP32 classic/Bluedroid. USB is power/UART only.
#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEHIDDevice.h>
#include <BLE2902.h>
#include <BLESecurity.h>
#include <Preferences.h>
#include <esp_random.h>
#include <esp_gatts_api.h>
#include "AxoPhoneProtocol.h"
#include "AxoPhoneSerial.h"
#include "AxoPhoneReportMap.h"

#if !defined(CONFIG_BLUEDROID_ENABLED)
#error "This version targets the bundled Bluedroid stack on ESP32 classic."
#endif

using namespace AxoPhone;
constexpr uint32_t idleLimitMs = 1500;
constexpr uint32_t queuedLimitMs = 150;
constexpr uint32_t pairingWindowMs = 120000;
constexpr uint32_t localArmLimitMs = 30000;
constexpr uint32_t transmitLimitMs = 350;
constexpr size_t queueCapacity = 8;
constexpr uint16_t noConnection = 0xffff;
// A physical-console diagnostic only. Public USB/BLE decoding still accepts
// opcodes 1...7, so the host cannot request this internal diagnostic opcode.
constexpr Opcode localNudge = static_cast<Opcode>(0xf0);

BLEServer *server = nullptr;
esp_gatt_if_t registeredInterface = ESP_GATT_IF_NONE;
BLEHIDDevice *hidDevice = nullptr;
BLECharacteristic *keyboardInput = nullptr;
BLECharacteristic *mouseInput = nullptr;
BLECharacteristic *statusCharacteristic = nullptr;
QueueHandle_t commands = nullptr;
portMUX_TYPE stateMux = portMUX_INITIALIZER_UNLOCKED;

struct LinkState {
  uint32_t generation = 1;
  uint32_t connectionEpoch = 0;
  uint16_t handle = noConnection;
  uint8_t address[6] = {};
  bool connected = false;
  bool authenticated = false;
  bool provisioned = false;
  bool provisionPending = false;
  bool clearingPairings = false;
  bool suspended = false;
  bool reportProtocol = true;
  bool congested = false;
  Reason reason = startup;
  uint32_t pairingUntil = 0;
};
LinkState linkState;
struct PendingCommand {
  Command command;
  uint32_t receivedAt;
  uint32_t generation;
  bool local;
};
enum class Phase { none, keyPress, keyRelease, wheelEvent, mousePress, mouseRelease };
struct Transmission {
  Phase phase = Phase::none;
  uint16_t connection = noConnection;
  uint16_t attribute = 0;
  uint8_t bytes[8] = {};
  size_t length = 0;
  uint32_t sentAt = 0;
  bool complete = false;
  esp_gatt_status_t status = ESP_GATT_OK;
};
Transmission transmission;
uint32_t configuredPasskey = 0;
uint32_t observedGeneration = 0;
uint32_t observedConnectionEpoch = 0;
uint32_t sessionToken = 0;
uint16_t lastAcceptedSequence = 0;
uint32_t lastAcceptedAt = 0;
uint32_t localArmUntil = 0;
uint32_t nextReleaseAt = 0;
bool controlsArmed = false;
bool localTransaction = false;
bool keyboardReleasePending = true;
bool mouseReleasePending = true;
bool statusDirty = true;
bool serialStatusRequested = true;
bool previousOutputReady = false;
bool outputFaulted = false;
Reason currentReason = startup;
enum class PairingReset { none, disconnecting, waitingForRemoval };
PairingReset pairingReset = PairingReset::none;
uint32_t pairingResetDeadline = 0;

LinkState snapshot() {
  portENTER_CRITICAL(&stateMux);
  LinkState result = linkState;
  portEXIT_CRITICAL(&stateMux);
  return result;
}
esp_gatt_if_t gattInterface() {
  portENTER_CRITICAL(&stateMux);
  const esp_gatt_if_t result = registeredInterface;
  portEXIT_CRITICAL(&stateMux);
  return result;
}
bool pairingOpen() {
  const uint32_t deadline = snapshot().pairingUntil;
  return deadline && int32_t(deadline - millis()) > 0;
}
void boundary(Reason reason) {
  portENTER_CRITICAL(&stateMux);
  ++linkState.generation;
  linkState.reason = reason;
  portEXIT_CRITICAL(&stateMux);
}
uint32_t newSession() {
  uint32_t token = 0;
  while (!token) token = esp_random();
  return token;
}
bool subscribed(BLECharacteristic *characteristic) {
  if (!characteristic) return false;
  BLE2902 *cccd = static_cast<BLE2902 *>(characteristic->getDescriptorByUUID("2902"));
  return cccd && cccd->getNotifications();
}
void clearSubscriptions() {
  BLECharacteristic *characteristics[] = {keyboardInput, mouseInput, statusCharacteristic};
  for (BLECharacteristic *characteristic : characteristics) {
    if (!characteristic) continue;
    BLE2902 *cccd = static_cast<BLE2902 *>(characteristic->getDescriptorByUUID("2902"));
    if (cccd) { cccd->setNotifications(false); cccd->setIndications(false); }
  }
}
bool outputReady() {
  const LinkState current = snapshot();
  return !outputFaulted && current.connected && current.authenticated && !current.suspended
    && current.reportProtocol && !current.congested && subscribed(keyboardInput) && subscribed(mouseInput);
}
void clearReportValues() {
  const uint8_t empty[8] = {};
  if (keyboardInput) keyboardInput->setValue(empty, 8);
  if (mouseInput) mouseInput->setValue(empty, 5);
}
void stopOutput(Reason reason) {
  controlsArmed = false;
  localTransaction = false;
  localArmUntil = 0;
  keyboardReleasePending = true;
  mouseReleasePending = true;
  xQueueReset(commands);
  // A reconnecting host may read the report before subscribing. Never expose
  // a previous held key or relative movement through the stored GATT value.
  clearReportValues();
  currentReason = reason;
  statusDirty = true;
}
void failTransmission() {
  // A timed-out notification completion has no transaction ID. Never reuse
  // its slot on this live link: disconnect, retain neutral cleanup, and start
  // a new connection epoch before another report can be sent.
  outputFaulted = true;
  stopOutput(hidSendFailed);
  const LinkState current = snapshot();
  if (current.connected) server->disconnect(current.handle);
}

class ServerCallbacks final : public BLEServerCallbacks {
  void onConnect(BLEServer *activeServer, esp_ble_gatts_cb_param_t *event) override {
    if (!event) return;
    const LinkState before = snapshot();
    if (before.connected || before.clearingPairings) { activeServer->disconnect(event->connect.conn_id); return; }
    clearSubscriptions();
    clearReportValues();
    // A saved iPhone bond may reconnect with a private address. Admit the link
    // before encryption, but no input can pass until authenticated. A new
    // passkey exchange outside the local PAIR window is rejected below.
    portENTER_CRITICAL(&stateMux);
    linkState.connected = true;
    linkState.authenticated = false;
    linkState.provisionPending = false;
    linkState.handle = event->connect.conn_id;
    memcpy(linkState.address, event->connect.remote_bda, 6);
    linkState.suspended = false;
    linkState.reportProtocol = true;
    linkState.congested = false;
    ++linkState.generation;
    ++linkState.connectionEpoch;
    linkState.reason = connectionChanged;
    portEXIT_CRITICAL(&stateMux);
  }
  void onDisconnect(BLEServer *, esp_ble_gatts_cb_param_t *event) override {
    const LinkState before = snapshot();
    if (event && event->disconnect.conn_id == before.handle) { clearSubscriptions(); clearReportValues(); }
    portENTER_CRITICAL(&stateMux);
    if (event && event->disconnect.conn_id == linkState.handle) {
      linkState.connected = false;
      linkState.authenticated = false;
      linkState.provisionPending = false;
      linkState.handle = noConnection;
      ++linkState.generation;
      ++linkState.connectionEpoch;
      linkState.reason = connectionChanged;
    }
    portEXIT_CRITICAL(&stateMux);
  }
};
class SecurityCallbacks final : public BLESecurityCallbacks {
  uint32_t onPassKeyRequest() override { return pairingOpen() ? configuredPasskey : 0; }
  void onPassKeyNotify(uint32_t passkey) override {
    // Codes are disclosed only by an explicit physical-UART PAIR command.
    if (!pairingOpen() || passkey != configuredPasskey) {
      const LinkState current = snapshot();
      boundary(authenticationFailed);
      if (current.connected) server->disconnect(current.handle);
    }
  }
  bool onConfirmPIN(uint32_t) override { return false; }
  bool onSecurityRequest() override { return snapshot().connected; }
  void onAuthenticationComplete(esp_ble_auth_cmpl_t event) override {
    const uint8_t required = ESP_LE_AUTH_REQ_SC_MITM_BOND;
    const LinkState before = snapshot();
    const bool newEnrollment = pairingOpen();
    const bool authenticated = event.success && (event.auth_mode & required) == required
      && (before.provisioned || newEnrollment);
    bool matched = false;
    portENTER_CRITICAL(&stateMux);
    if (linkState.connected && memcmp(linkState.address, event.bd_addr, 6) == 0) {
      matched = true;
      linkState.provisionPending = authenticated && !linkState.provisioned;
      linkState.authenticated = authenticated && linkState.provisioned;
      ++linkState.generation;
      linkState.reason = authenticated ? connectionChanged : authenticationFailed;
      if (linkState.authenticated) linkState.pairingUntil = 0;
    }
    portEXIT_CRITICAL(&stateMux);
    if (matched && !authenticated) server->disconnect(snapshot().handle);
  }
};
class CommandCallbacks final : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *characteristic, esp_ble_gatts_cb_param_t *event) override {
    const LinkState current = snapshot();
    if (!event || !current.connected || !current.authenticated || event->write.conn_id != current.handle) return;
    const String value = characteristic->getValue();
    Command parsed;
    if (!decode(reinterpret_cast<const uint8_t *>(value.c_str()), value.length(), parsed)) {
      boundary(invalidCommand);
      return;
    }
    const PendingCommand pending = {parsed, millis(), current.generation, false};
    if (xQueueSend(commands, &pending, 0) != pdTRUE) boundary(queueOverflow);
  }
};
class HIDControlCallbacks final : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *characteristic, esp_ble_gatts_cb_param_t *event) override {
    const LinkState current = snapshot();
    if (!event || event->write.conn_id != current.handle) return;
    const String value = characteristic->getValue();
    if (value.length() != 1 || (value[0] != 0 && value[0] != 1)) return;
    portENTER_CRITICAL(&stateMux);
    linkState.suspended = value[0] == 0;
    ++linkState.generation;
    linkState.reason = hidChanged;
    portEXIT_CRITICAL(&stateMux);
  }
};
class ProtocolCallbacks final : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *characteristic, esp_ble_gatts_cb_param_t *event) override {
    const LinkState current = snapshot();
    if (!event || event->write.conn_id != current.handle) return;
    const String value = characteristic->getValue();
    if (value.length() != 1) return;
    portENTER_CRITICAL(&stateMux);
    linkState.reportProtocol = value[0] == 1;
    ++linkState.generation;
    linkState.reason = hidChanged;
    portEXIT_CRITICAL(&stateMux);
  }
};
ServerCallbacks serverCallbacks;
SecurityCallbacks securityCallbacks;
CommandCallbacks commandCallbacks;
HIDControlCallbacks hidControlCallbacks;
ProtocolCallbacks protocolCallbacks;

bool persistProvisioned(bool provisioned) {
  Preferences settings;
  if (!settings.begin("axo-phone", false)) return false;
  const bool saved = settings.putBool("provisioned", provisioned) == 1;
  settings.end();
  return saved;
}
void beginPairingReset() {
  stopOutput(explicitDisarm);
  const LinkState before = snapshot();
  portENTER_CRITICAL(&stateMux);
  linkState.provisioned = false;
  linkState.provisionPending = false;
  linkState.clearingPairings = true;
  linkState.authenticated = false;
  linkState.pairingUntil = 0;
  ++linkState.generation;
  linkState.reason = explicitDisarm;
  portEXIT_CRITICAL(&stateMux);
  if (!persistProvisioned(false)) {
    Serial.println("Cannot save disabled pairing state; enrollment remains closed.");
    return;
  }
  if (before.connected) server->disconnect(before.handle);
  pairingReset = PairingReset::disconnecting;
  pairingResetDeadline = millis() + 10000;
  Serial.println("Replacing this ESP32's Bluetooth pairings; waiting for disconnection and bond removal.");
}
void servicePairingReset() {
  if (pairingReset == PairingReset::none) return;
  if (int32_t(pairingResetDeadline - millis()) <= 0) {
    pairingReset = PairingReset::none;
    Serial.println("Pairing cleanup timed out; enrollment remains closed. Type PAIR to retry.");
    return;
  }
  if (snapshot().connected) return;
  int count = esp_ble_get_bond_device_num();
  if (count < 0 || count > 16) {
    pairingReset = PairingReset::none;
    Serial.println("Cannot inspect bounded Bluetooth pairing list; enrollment remains closed.");
    return;
  }
  if (count > 0 && pairingReset == PairingReset::disconnecting) {
    esp_ble_bond_dev_t records[16];
    int capacity = 16;
    if (esp_ble_get_bond_device_list(&capacity, records) != ESP_OK || capacity > 16) {
      pairingReset = PairingReset::none;
      Serial.println("Cannot inspect Bluetooth pairings; enrollment remains closed.");
      return;
    }
    for (int i = 0; i < capacity; ++i) {
      if (esp_ble_remove_bond_device(records[i].bd_addr) != ESP_OK) {
        pairingReset = PairingReset::none;
        Serial.println("Bluetooth pairing removal failed; enrollment remains closed.");
        return;
      }
    }
    pairingReset = PairingReset::waitingForRemoval;
    return;
  }
  if (count != 0) return;  // Asynchronous removals must actually finish first.
  if (!BLE2902::deleteAllPersistedValues()) {
    pairingReset = PairingReset::none;
    Serial.println("Cannot clear old Bluetooth subscription cache; enrollment remains closed.");
    return;
  }
  clearSubscriptions();
  Preferences settings;
  do { configuredPasskey = 100000 + esp_random() % 900000; } while (configuredPasskey == BLE_SM_DEFAULT_PASSKEY);
  if (!settings.begin("axo-phone", false)) { pairingReset = PairingReset::none; return; }
  const bool saved = settings.putUInt("pair-pin", configuredPasskey) == sizeof(configuredPasskey);
  settings.end();
  pairingReset = PairingReset::none;
  if (!saved) { Serial.println("Cannot save new passkey; enrollment remains closed."); return; }
  BLESecurity::setPassKey(true, configuredPasskey);
  portENTER_CRITICAL(&stateMux);
  linkState.clearingPairings = false;
  linkState.pairingUntil = millis() + pairingWindowMs;
  portEXIT_CRITICAL(&stateMux);
  Serial.printf("Pairing open for 120 seconds. Enter this code in the iPhone's Bluetooth pairing dialog: %06lu\n",
                static_cast<unsigned long>(configuredPasskey));
}
void finishProvisioning() {
  const LinkState before = snapshot();
  if (!before.connected || !before.provisionPending) return;
  const bool saved = pairingOpen() && persistProvisioned(true);
  portENTER_CRITICAL(&stateMux);
  if (linkState.connected && linkState.handle == before.handle && linkState.provisionPending
      && linkState.generation == before.generation && memcmp(linkState.address, before.address, 6) == 0) {
    linkState.provisionPending = false;
    linkState.provisioned = saved;
    linkState.authenticated = saved;
    linkState.pairingUntil = 0;
    ++linkState.generation;
    linkState.reason = saved ? connectionChanged : authenticationFailed;
  }
  portEXIT_CRITICAL(&stateMux);
  if (!saved) server->disconnect(before.handle);
}

void gattsEvent(esp_gatts_cb_event_t event, esp_gatt_if_t interface, esp_ble_gatts_cb_param_t *value) {
  if (!value) return;
  if (event == ESP_GATTS_REG_EVT) {
    // createServer() registers asynchronously before it returns. Its public
    // app ID identifies our registration even while the global server pointer
    // has not yet been assigned. Do not call the library's private getGattsIf.
    BLEServer *created = BLEDevice::getServer();
    if (created && value->reg.status == ESP_GATT_OK && value->reg.app_id == created->m_gattAppId) {
      portENTER_CRITICAL(&stateMux);
      registeredInterface = interface;
      portEXIT_CRITICAL(&stateMux);
    }
    return;
  }
  if (!server || interface != gattInterface()) return;
  portENTER_CRITICAL(&stateMux);
  if (event == ESP_GATTS_CONGEST_EVT && value->congest.conn_id == linkState.handle) {
    linkState.congested = value->congest.congested;
  } else if (event == ESP_GATTS_CONF_EVT && linkState.connected && transmission.phase != Phase::none
      && value->conf.conn_id == linkState.handle
      && value->conf.conn_id == transmission.connection && value->conf.handle == transmission.attribute) {
    // Actual Bluedroid success events omit value/len, despite the header's
    // wording. Exactly one report is in flight; interface/connection/attribute
    // identify it. On any failure/timeout the live link is abandoned, so a late
    // completion cannot clear a newer release on that same connection.
    transmission.complete = true;
    transmission.status = value->conf.status;
  }
  portEXIT_CRITICAL(&stateMux);
}

bool transmitting() {
  portENTER_CRITICAL(&stateMux);
  const bool result = transmission.phase != Phase::none;
  portEXIT_CRITICAL(&stateMux);
  return result;
}
bool sendReport(BLECharacteristic *characteristic, const uint8_t *bytes, size_t length, Phase phase) {
  const LinkState current = snapshot();
  if (!outputReady() || !characteristic || length > 8 || transmitting()) return false;
  portENTER_CRITICAL(&stateMux);
  transmission = {};
  transmission.phase = phase;
  transmission.connection = current.handle;
  transmission.attribute = characteristic->getHandle();
  transmission.length = length;
  transmission.sentAt = millis();
  memcpy(transmission.bytes, bytes, length);
  portEXIT_CRITICAL(&stateMux);
  characteristic->setValue(bytes, length);
  const esp_err_t result = esp_ble_gatts_send_indicate(gattInterface(), current.handle,
    characteristic->getHandle(), length, const_cast<uint8_t *>(bytes), false);
  if (result != ESP_OK) {
    failTransmission();
    return false;
  }
  return true;
}
void serviceTransmission() {
  if (outputFaulted) return;
  portENTER_CRITICAL(&stateMux);
  const Transmission current = transmission;
  portEXIT_CRITICAL(&stateMux);
  if (current.phase == Phase::none) return;
  if (!current.complete && millis() - current.sentAt < transmitLimitMs) return;
  if (!current.complete || current.status != ESP_GATT_OK) {
    failTransmission();
    return;
  }
  portENTER_CRITICAL(&stateMux);
  transmission = {};
  portEXIT_CRITICAL(&stateMux);
  if (current.phase == Phase::keyRelease) keyboardReleasePending = false;
  if (current.phase == Phase::mouseRelease) mouseReleasePending = false;
  if (localTransaction && !keyboardReleasePending && !mouseReleasePending) {
    controlsArmed = false;
    localTransaction = false;
    currentReason = explicitDisarm;
    statusDirty = true;
  }
}
bool releaseOutput() {
  if (!outputReady() || transmitting() || int32_t(millis() - nextReleaseAt) < 0) return false;
  const uint8_t empty[8] = {};
  if (keyboardReleasePending) {
    if (!sendReport(keyboardInput, empty, 8, Phase::keyRelease)) nextReleaseAt = millis() + 20;
    return false;
  }
  if (mouseReleasePending) {
    if (!sendReport(mouseInput, empty, 5, Phase::mouseRelease)) nextReleaseAt = millis() + 20;
    return false;
  }
  return true;
}

void accept(const PendingCommand &pending, uint32_t now) {
  const Command &command = pending.command;
  if (pending.generation != observedGeneration) return;
  if (now - pending.receivedAt > queuedLimitMs) { stopOutput(staleQueuedCommand); return; }
  const LinkState current = snapshot();
  if (!current.connected || !current.authenticated || current.generation != observedGeneration) return;
  if (pending.local) {
    if (!localArmUntil || int32_t(localArmUntil - now) <= 0) return;
    localArmUntil = 0;
    localTransaction = true;
    controlsArmed = true;
  } else {
    if (command.session != sessionToken || command.sequence <= lastAcceptedSequence) return;
    lastAcceptedSequence = command.sequence;  // Protocol acceptance, not confirmation of a phone action.
    statusDirty = true;
    if (command.opcode == disarm) { stopOutput(explicitDisarm); return; }
    if (command.opcode == arm) {
      if (!outputReady() || keyboardReleasePending || mouseReleasePending) return;
      controlsArmed = true;
      lastAcceptedAt = now;
      currentReason = armed;
      return;
    }
  }
  if (!controlsArmed) return;
  lastAcceptedAt = now;
  if (command.opcode == heartbeat) return;
  if (!outputReady() || transmitting()) { stopOutput(hidSendFailed); return; }
  if (command.opcode == key) {
    uint8_t report[8] = {command.second, 0, command.first, 0, 0, 0, 0, 0};
    keyboardReleasePending = true;  // Retain this even after ambiguous submission/completion failure.
    if (!sendReport(keyboardInput, report, sizeof(report), Phase::keyPress)) stopOutput(hidSendFailed);
  } else if (command.opcode == wheel) {
    const uint8_t report[5] = {0, 0, 0, command.first, command.second};
    if (!sendReport(mouseInput, report, sizeof(report), Phase::wheelEvent)) stopOutput(hidSendFailed);
    // Never retry a relative movement after an ambiguous failure.
  } else if (pending.local && command.opcode == localNudge) {
    const uint8_t report[5] = {0, 16, 16, 0, 0};
    if (!sendReport(mouseInput, report, sizeof(report), Phase::wheelEvent)) stopOutput(hidSendFailed);
  } else if (command.opcode == pointerMove) {
    uint8_t report[5];
    pointerMoveReport(report, command);
    if (!sendReport(mouseInput, report, sizeof(report), Phase::wheelEvent)) stopOutput(hidSendFailed);
    // Positioning is explicit and momentary; arming/scrolling never moves X/Y.
  } else if (command.opcode == pointerClick) {
    uint8_t report[5];
    pointerClickReport(report);
    // Retain the release obligation before any submission, including an
    // ambiguous failure. releaseOutput() blocks all following commands until
    // the neutral report's completion; failed/uncertain presses are not retried.
    mouseReleasePending = true;
    if (!sendReport(mouseInput, report, sizeof(report), Phase::mousePress)) stopOutput(hidSendFailed);
  }
}

void serialSetup() {
  static SerialLine parser;
  // Service HID completions, neutral reports, and the watchdog even if a host
  // floods this physical console. Complete lines retain no queue of their own.
  for (size_t count = 0; count < 64 && Serial.available(); ++count) {
    const SerialLine::Result result = parser.push(Serial.read());
    if (result == SerialLine::Result::rejected) { boundary(invalidCommand); continue; }
    if (result == SerialLine::Result::ready) {
      const char *line = parser.data();
      if (strcmp(line, "HELLO") == 0) {
        serialStatusRequested = true;
      } else if (strncmp(line, "USB", 3) == 0) {
        Command command;
        if (!serialCommand(line, parser.size(), command)) { boundary(invalidCommand); continue; }
        const LinkState current = snapshot();
        const PendingCommand pending = {command, millis(), current.generation, false};
        if (xQueueSend(commands, &pending, 0) != pdTRUE) boundary(queueOverflow);
      } else if (strcmp(line, "PAIR") == 0) {
        beginPairingReset();
      } else if (strcmp(line, "DISARM") == 0) {
        stopOutput(explicitDisarm);
      } else if (strcmp(line, "ARM") == 0) {
        stopOutput(explicitDisarm);
        localArmUntil = millis() + localArmLimitMs;
        Serial.println("One local navigation test authorized for 30 seconds; TAB, UP, DOWN, F13, or NUDGE.");
      } else if (strcmp(line, "TAB") == 0 || strcmp(line, "F13") == 0
          || strcmp(line, "UP") == 0 || strcmp(line, "DOWN") == 0 || strcmp(line, "NUDGE") == 0) {
        const bool keyboard = strcmp(line, "TAB") == 0 || strcmp(line, "F13") == 0;
        const bool nudge = strcmp(line, "NUDGE") == 0;
        const uint8_t argument = keyboard ? (strcmp(line, "TAB") == 0 ? 0x2b : 0x68)
          : (nudge ? 0 : (strcmp(line, "UP") == 0 ? 1 : 0xff));
        const Command command = {nudge ? localNudge : (keyboard ? key : wheel), 0, 0, argument, 0};
        const PendingCommand pending = {command, millis(), snapshot().generation, true};
        if (!localArmUntil || int32_t(localArmUntil - millis()) <= 0) Serial.println("Type ARM before a local test.");
        else if (!outputReady()) Serial.println("HID output is not ready; pair the phone and enable keyboard/mouse access.");
        else if (xQueueSend(commands, &pending, 0) != pdTRUE) boundary(queueOverflow);
      }
    }
  }
}
void publishStatus() {
  if (!statusDirty && !serialStatusRequested) return;
  uint8_t bytes[packetSize];
  status(bytes, controlsArmed, lastAcceptedSequence, sessionToken, currentReason, outputReady());
  if (statusDirty) {
    if (statusCharacteristic) {
      statusCharacteristic->setValue(bytes, sizeof(bytes));
      if (snapshot().authenticated) statusCharacteristic->notify();
    }
    serialStatusRequested = true;
    statusDirty = false;
  }
  if (serialStatusRequested && Serial.availableForWrite() >= static_cast<int>(serialStatusLength)) {
    char line[serialStatusLength];
    serialStatus(line, bytes);
    Serial.write(reinterpret_cast<const uint8_t *>(line), sizeof(line));
    serialStatusRequested = false;
  }
}

void setup() {
  Serial.begin(115200);
  commands = xQueueCreate(queueCapacity, sizeof(PendingCommand));
  Preferences settings;
  if (!commands || !settings.begin("axo-phone", false)) {
    Serial.println("Adapter setup failed; output remains disabled.");
    while (true) delay(1000);
  }
  configuredPasskey = settings.getUInt("pair-pin", 0);
  linkState.provisioned = settings.getBool("provisioned", false);
  if (configuredPasskey < 100000 || configuredPasskey > 999999 || configuredPasskey == BLE_SM_DEFAULT_PASSKEY) {
    do { configuredPasskey = 100000 + esp_random() % 900000; } while (configuredPasskey == BLE_SM_DEFAULT_PASSKEY);
    if (settings.putUInt("pair-pin", configuredPasskey) != sizeof(configuredPasskey)) {
      settings.end();
      while (true) delay(1000);
    }
  }
  settings.end();
  if (!BLEDevice::init("Axo Phone Bridge")) {
    Serial.println("Bluetooth setup failed; output remains disabled.");
    while (true) delay(1000);
  }
  BLESecurity::setInitEncryptionKey();
  BLESecurity::setRespEncryptionKey();
  BLESecurity::setKeySize(16);
  BLESecurity::setCapability(ESP_IO_CAP_OUT);
  BLESecurity::setAuthenticationMode(true, true, true);
  BLESecurity::setEncryptionLevel(ESP_BLE_SEC_ENCRYPT_MITM);
  BLESecurity::setPassKey(true, configuredPasskey);
  BLEDevice::setSecurityCallbacks(&securityCallbacks);
  BLEDevice::setCustomGattsHandler(gattsEvent);
  server = BLEDevice::createServer();
  const uint32_t registrationDeadline = millis() + 1000;
  while (gattInterface() == ESP_GATT_IF_NONE && int32_t(registrationDeadline - millis()) > 0) delay(1);
  if (!server || gattInterface() == ESP_GATT_IF_NONE) {
    Serial.println("Bluetooth registration failed; output remains disabled.");
    while (true) delay(1000);
  }
  server->setCallbacks(&serverCallbacks);
  server->advertiseOnDisconnect(true);
  hidDevice = new BLEHIDDevice(server);
  hidDevice->manufacturer()->setValue(String("Axo Neurotech"));
  // Espressif's Bluetooth SIG company identifier; experimental product zero.
  hidDevice->pnp(0x01, 0x02e5, 0x0000, 0x0100);
  hidDevice->hidInfo(0, 0x02);
  hidDevice->reportMap(axoReportMap, sizeof(axoReportMap));
  keyboardInput = hidDevice->inputReport(1);
  mouseInput = hidDevice->inputReport(2);
  hidDevice->outputReport(1);  // Standard keyboard LED output, no action handler.
  hidDevice->hidControl()->setCallbacks(&hidControlCallbacks);
  hidDevice->protocolMode()->setCallbacks(&protocolCallbacks);
  hidDevice->setBatteryLevel(100);  // USB-powered adapter, not the band's battery.
  BLEService *service = server->createService(serviceUUID);
  BLECharacteristic *command = service->createCharacteristic(commandUUID, BLECharacteristic::PROPERTY_WRITE);
  command->setAccessPermissions(ESP_GATT_PERM_WRITE_ENC_MITM);
  command->setCallbacks(&commandCallbacks);
  statusCharacteristic = service->createCharacteristic(statusUUID, BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY);
  statusCharacteristic->setAccessPermissions(ESP_GATT_PERM_READ_ENC_MITM);
  statusCharacteristic->addDescriptor(new BLE2902());
  sessionToken = newSession();
  publishStatus();
  service->start();
  hidDevice->startServices();
  BLEAdvertising *advertising = BLEDevice::getAdvertising();
  advertising->setAppearance(GENERIC_HID);
  advertising->addServiceUUID(BLEUUID(uint16_t(0x1812)));
  advertising->addServiceUUID(serviceUUID);
  advertising->setScanResponse(true);
  advertising->setMinPreferred(0x06);
  advertising->setMaxPreferred(0x12);
  BLEDevice::startAdvertising();
  Serial.println("Axo bridge ready, disarmed. Type PAIR then Enter for local Bluetooth enrollment.");
}

void loop() {
  serialSetup();
  servicePairingReset();
  finishProvisioning();
  const LinkState connection = snapshot();
  if (connection.connectionEpoch != observedConnectionEpoch) {
    observedConnectionEpoch = connection.connectionEpoch;
    outputFaulted = false;
    portENTER_CRITICAL(&stateMux);
    transmission = {};
    portEXIT_CRITICAL(&stateMux);
  }
  const bool ready = outputReady();
  if (ready != previousOutputReady) {
    previousOutputReady = ready;
    boundary(hidChanged);
  }
  const LinkState current = snapshot();
  if (current.generation != observedGeneration) {
    observedGeneration = current.generation;
    stopOutput(current.reason);
    sessionToken = newSession();
    lastAcceptedSequence = 0;
    // A dead link cannot complete old transfers. A live-link boundary keeps
    // an in-flight transfer until completion/timeout before sending releases.
    if (!current.connected) {
      portENTER_CRITICAL(&stateMux);
      transmission = {};
      portEXIT_CRITICAL(&stateMux);
    }
  }
  serviceTransmission();
  const uint32_t now = millis();
  if (controlsArmed && !ready) stopOutput(hidChanged);
  if (controlsArmed && now - lastAcceptedAt >= idleLimitMs) stopOutput(idleTimeout);
  if (releaseOutput()) {
    PendingCommand pending;
    if (xQueueReceive(commands, &pending, 0) == pdTRUE) accept(pending, millis());
  }
  publishStatus();
  delay(1);
}
