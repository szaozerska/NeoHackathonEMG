#include "../AxoPhoneSerial.h"
#include <assert.h>
#include <string.h>
using namespace AxoPhone;

SerialLine::Result feed(SerialLine &parser, const char *value) {
  SerialLine::Result result = SerialLine::Result::waiting;
  for (; *value; ++value) result = parser.push(*value);
  return result;
}

int main() {
  static_assert(SerialLine::maximumLength == 28, "USB commands have one fixed wire length");
  static_assert(serialStatusLength == 34, "Status has no terminal control bytes except newline");
  SerialLine parser;
  assert(feed(parser, "HEL") == SerialLine::Result::waiting);
  assert(feed(parser, "LO\r\n") == SerialLine::Result::ready);
  assert(parser.size() == 5 && strcmp(parser.data(), "HELLO") == 0);

  const char *valid = "USB 0105341278563412ff000000";
  Command command;
  assert(serialCommand(valid, strlen(valid), command));
  assert(command.opcode == wheel && command.sequence == 0x1234 && command.session == 0x12345678);
  assert(command.first == 0xff && command.second == 0);
  assert(feed(parser, valid) == SerialLine::Result::waiting);
  assert(parser.push('\n') == SerialLine::Result::ready);
  assert(serialCommand(parser.data(), parser.size(), command));
  assert(serialCommand("USB 0105341278563412FF000000", 28, command));
  assert(!serialCommand(nullptr, 28, command));
  assert(!serialCommand(valid, 27, command));
  assert(!serialCommand(valid, 29, command));
  assert(!serialCommand("usb 0105341278563412ff000000", 28, command));
  assert(!serialCommand("USB 0105341278563412fg000000", 28, command));
  assert(!serialCommand("USB 0205341278563412ff000000", 28, command));
  assert(!serialCommand("USB 01f034127856341200000000", 28, command));  // NUDGE is physical-console only.
  assert(!serialCommand("USB 0105000078563412ff000000", 28, command));
  assert(!serialCommand("USB 0105341200000000ff000000", 28, command));
  assert(!serialCommand("USB 010534127856341200000000", 28, command));
  assert(!serialCommand("USB 010534127856341280000000", 28, command));
  assert(!serialCommand("USB 0105341278563412ff000100", 28, command));
  assert(!serialCommand("USB 010434127856341204000000", 28, command));  // No letter keys.
  assert(serialCommand("USB 010434127856341268000000", 28, command));  // F13.
  assert(serialCommand("USB 010634127856341210f00000", 28, command));
  assert(command.opcode == pointerMove && command.first == 16 && command.second == 0xf0);
  assert(!serialCommand("USB 010634127856341200000000", 28, command));
  assert(!serialCommand("USB 010634127856341280000000", 28, command));
  assert(serialCommand("USB 010734127856341200000000", 28, command));
  assert(command.opcode == pointerClick && command.first == 0 && command.second == 0);
  assert(!serialCommand("USB 010734127856341201000000", 28, command));
  assert(!serialCommand("USB 010734127856341200010000", 28, command));

  // Oversized or nonprintable lines cannot turn a valid-looking suffix into a
  // command. The next complete line still works after the rejection boundary.
  assert(feed(parser, "USB 0105341278563412ff000000PAIR\n") == SerialLine::Result::rejected);
  assert(feed(parser, "PAIR\n") == SerialLine::Result::ready);
  assert(strcmp(parser.data(), "PAIR") == 0);
  assert(parser.push('P') == SerialLine::Result::waiting);
  assert(parser.push(0) == SerialLine::Result::waiting);
  assert(feed(parser, "AIR\n") == SerialLine::Result::rejected);
  assert(feed(parser, "HELLO\n") == SerialLine::Result::ready);
  assert(strcmp(parser.data(), "HELLO") == 0);

  uint8_t packet[packetSize];
  status(packet, true, 0x1234, 0x12345678, armed, true);
  char line[serialStatusLength];
  serialStatus(line, packet);
  const char *expected = "AXOUSB 3 010134127856341202010000\n";
  assert(strlen(expected) == sizeof(line));
  assert(memcmp(line, expected, sizeof(line)) == 0);
}
