#pragma once
#include <stddef.h>
#include <stdint.h>

namespace AxoPhone {
constexpr size_t packetSize = 12;
constexpr uint8_t version = 1;
constexpr const char *serviceUUID = "A10A0001-5D53-4A18-8F6A-1C173E442001";
constexpr const char *commandUUID = "A10A0002-5D53-4A18-8F6A-1C173E442001";
constexpr const char *statusUUID = "A10A0003-5D53-4A18-8F6A-1C173E442001";
enum Opcode : uint8_t { arm = 1, disarm = 2, heartbeat = 3, key = 4, wheel = 5, pointerMove = 6, pointerClick = 7 };
enum Reason : uint8_t {
  startup = 0, connectionChanged = 1, armed = 2, explicitDisarm = 3,
  authenticationFailed = 4, hidChanged = 5, idleTimeout = 6, queueOverflow = 7,
  invalidCommand = 8, hidSendFailed = 9, staleQueuedCommand = 10
};
struct Command {
  Opcode opcode;
  uint16_t sequence;
  uint32_t session;
  uint8_t first;
  uint8_t second;
};
inline bool navigationKey(uint8_t usage) {
  switch (usage) {
    case 0x28: case 0x29: case 0x2b: case 0x2c:
    case 0x4a: case 0x4b: case 0x4d: case 0x4e:
    case 0x4f: case 0x50: case 0x51: case 0x52:
    case 0x68: case 0x69: return true;  // F13/F14: explicit user-configured shortcut triggers.
    default: return false;
  }
}
inline bool decode(const uint8_t *bytes, size_t length, Command &result) {
  if (!bytes || length != packetSize || bytes[0] != version || bytes[10] || bytes[11]) return false;
  const uint16_t sequence = uint16_t(bytes[2]) | (uint16_t(bytes[3]) << 8);
  const uint32_t session = uint32_t(bytes[4]) | (uint32_t(bytes[5]) << 8)
    | (uint32_t(bytes[6]) << 16) | (uint32_t(bytes[7]) << 24);
  if (!sequence || !session || bytes[1] < arm || bytes[1] > pointerClick) return false;
  const Opcode opcode = static_cast<Opcode>(bytes[1]);
  if (opcode == key && !navigationKey(bytes[8])) return false;
  if ((opcode == wheel || opcode == pointerMove)
      && (bytes[8] == 0x80 || bytes[9] == 0x80 || (!bytes[8] && !bytes[9]))) return false;
  if ((opcode <= heartbeat || opcode == pointerClick) && (bytes[8] || bytes[9])) return false;
  result = {opcode, sequence, session, bytes[8], bytes[9]};
  return true;
}
inline void status(uint8_t *bytes, bool isArmed, uint16_t lastAcceptedSequence,
                   uint32_t session, Reason reason, bool outputReady) {
  bytes[0] = version;
  bytes[1] = isArmed ? 1 : 0;
  bytes[2] = uint8_t(lastAcceptedSequence);
  bytes[3] = uint8_t(lastAcceptedSequence >> 8);
  for (unsigned i = 0; i < 4; ++i) bytes[4 + i] = uint8_t(session >> (8 * i));
  bytes[8] = reason;
  bytes[9] = outputReady ? 1 : 0;
  bytes[10] = bytes[11] = 0;
}
inline void pointerMoveReport(uint8_t (&report)[5], const Command &command) {
  report[0] = 0;
  report[1] = command.first;
  report[2] = command.second;
  report[3] = report[4] = 0;
}
inline void pointerClickReport(uint8_t (&report)[5]) {
  report[0] = 1;  // Primary/left button only; the serialized neutral report releases it.
  report[1] = report[2] = report[3] = report[4] = 0;
}
}  // namespace AxoPhone
