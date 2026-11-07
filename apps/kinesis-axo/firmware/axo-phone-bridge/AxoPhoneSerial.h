#pragma once
#include "AxoPhoneProtocol.h"
#include <string.h>

namespace AxoPhone {
// No arbitrary serial commands or binary terminal escapes enter the control
// path. A line is either bounded printable ASCII or discarded through newline.
class SerialLine {
 public:
  static constexpr size_t maximumLength = 4 + packetSize * 2;
  enum class Result { waiting, ready, rejected };

  Result push(int byte) {
    if (byte == '\r') return Result::waiting;
    if (byte == '\n') {
      const bool rejected = discard;
      length = used;
      bytes[used] = 0;
      used = 0;
      discard = false;
      return rejected ? Result::rejected : Result::ready;
    }
    if (discard) return Result::waiting;
    if (byte < 0x20 || byte > 0x7e || used == maximumLength) {
      used = 0;
      discard = true;
      return Result::waiting;
    }
    bytes[used++] = static_cast<char>(byte);
    return Result::waiting;
  }

  const char *data() const { return bytes; }
  size_t size() const { return length; }

 private:
  char bytes[maximumLength + 1] = {};
  size_t used = 0;
  size_t length = 0;
  bool discard = false;
};

inline int hexDigit(char value) {
  if (value >= '0' && value <= '9') return value - '0';
  if (value >= 'a' && value <= 'f') return value - 'a' + 10;
  if (value >= 'A' && value <= 'F') return value - 'A' + 10;
  return -1;
}

inline bool serialCommand(const char *line, size_t length, Command &command) {
  if (!line || length != SerialLine::maximumLength || memcmp(line, "USB ", 4) != 0) return false;
  uint8_t packet[packetSize];
  for (size_t i = 0; i < packetSize; ++i) {
    const int high = hexDigit(line[4 + i * 2]);
    const int low = hexDigit(line[5 + i * 2]);
    if (high < 0 || low < 0) return false;
    packet[i] = static_cast<uint8_t>((high << 4) | low);
  }
  return decode(packet, sizeof(packet), command);
}

constexpr size_t serialStatusLength = 9 + packetSize * 2 + 1;
inline void serialStatus(char (&line)[serialStatusLength], const uint8_t (&packet)[packetSize]) {
  constexpr char digits[] = "0123456789abcdef";
  memcpy(line, "AXOUSB 3 ", 9);
  for (size_t i = 0; i < packetSize; ++i) {
    line[9 + i * 2] = digits[packet[i] >> 4];
    line[10 + i * 2] = digits[packet[i] & 0x0f];
  }
  line[serialStatusLength - 1] = '\n';
}
}  // namespace AxoPhone
