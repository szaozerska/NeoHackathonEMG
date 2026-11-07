#include "../AxoPhoneProtocol.h"
#include <assert.h>
#include <string.h>
using namespace AxoPhone;
int main() {
  uint8_t packet[packetSize] = {1, key, 0x34, 0x12, 0x78, 0x56, 0x34, 0x12, 0x2b, 0x0a, 0, 0};
  Command command;
  assert(decode(packet, sizeof(packet), command));
  assert(command.sequence == 0x1234 && command.session == 0x12345678 && command.first == 0x2b && command.second == 0x0a);
  assert(!decode(nullptr, sizeof(packet), command));
  assert(!decode(packet, sizeof(packet) - 1, command));
  packet[0] = 2; assert(!decode(packet, sizeof(packet), command)); packet[0] = 1;
  packet[1] = 8; assert(!decode(packet, sizeof(packet), command)); packet[1] = key;
  packet[1] = 0xf0; assert(!decode(packet, sizeof(packet), command)); packet[1] = key;  // Local NUDGE is not a wire opcode.
  const uint8_t shortcutUsages[] = {0x68, 0x69};
  for (uint8_t usage : shortcutUsages) {
    packet[8] = usage; assert(decode(packet, sizeof(packet), command));
  }
  packet[8] = 0x2b;
  packet[10] = 1; assert(!decode(packet, sizeof(packet), command)); packet[10] = 0;
  packet[8] = 4; assert(!decode(packet, sizeof(packet), command));
  packet[1] = wheel; packet[8] = 0x81; packet[9] = 0x7f; assert(decode(packet, sizeof(packet), command));
  packet[8] = 0x80; assert(!decode(packet, sizeof(packet), command));
  packet[8] = 0; packet[9] = 0; assert(!decode(packet, sizeof(packet), command));
  packet[1] = pointerMove; packet[8] = 0x81; packet[9] = 0x7f;
  assert(decode(packet, sizeof(packet), command));
  assert(command.opcode == pointerMove && command.first == 0x81 && command.second == 0x7f);
  uint8_t moveReport[5] = {0xff, 0xff, 0xff, 0xff, 0xff};
  pointerMoveReport(moveReport, command);
  const uint8_t expectedMove[5] = {0, 0x81, 0x7f, 0, 0};
  assert(memcmp(moveReport, expectedMove, sizeof(moveReport)) == 0); // No buttons or wheel.
  packet[8] = 0x80; assert(!decode(packet, sizeof(packet), command));
  packet[8] = 1; packet[9] = 0x80; assert(!decode(packet, sizeof(packet), command));
  packet[8] = 0; packet[9] = 0; assert(!decode(packet, sizeof(packet), command));
  packet[8] = 0; packet[9] = 1; assert(decode(packet, sizeof(packet), command));
  packet[9] = 0;
  packet[1] = pointerClick;
  assert(decode(packet, sizeof(packet), command));
  assert(command.opcode == pointerClick && command.first == 0 && command.second == 0);
  uint8_t clickReport[5] = {0xff, 0xff, 0xff, 0xff, 0xff};
  pointerClickReport(clickReport);
  const uint8_t expectedClick[5] = {1, 0, 0, 0, 0};
  assert(memcmp(clickReport, expectedClick, sizeof(clickReport)) == 0); // Left button only, no pointer/scroll movement.
  packet[8] = 1; assert(!decode(packet, sizeof(packet), command)); packet[8] = 0;
  packet[9] = 1; assert(!decode(packet, sizeof(packet), command)); packet[9] = 0;
  packet[1] = arm; assert(decode(packet, sizeof(packet), command));
  packet[9] = 1; assert(!decode(packet, sizeof(packet), command)); packet[9] = 0;
  packet[2] = packet[3] = 0; assert(!decode(packet, sizeof(packet), command));
  packet[2] = 1;
  packet[4] = packet[5] = packet[6] = packet[7] = 0; assert(!decode(packet, sizeof(packet), command));
  const uint8_t expected[packetSize] = {1, 1, 0x34, 0x12, 0x78, 0x56, 0x34, 0x12, armed, 1, 0, 0};
  status(packet, true, 0x1234, 0x12345678, armed, true);
  assert(memcmp(packet, expected, sizeof(packet)) == 0);
}
