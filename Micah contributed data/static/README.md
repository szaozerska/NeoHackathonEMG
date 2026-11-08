# Static testing

These recordings are intentionally **not Git-ignored**.

Open `/static` on the partner bench. The current collection Mac uses
http://127.0.0.1:8785/static.

1. Start a session; keep the same wearing-session ID until moving/reapplying
   the band.
2. Select Shield low/medium/high or Sword low/medium/high.
3. Keep the arm comfortably still. Hold Space and maintain the selected open
   shield hand or closed sword grip for about ten seconds or longer.
4. Release Space to return to non-intended. Rest between holds.
5. Stop and save. Record another session or repeat conditions as useful.

Space down/up labels the interval immediately. No minimum duration or fixed
clipping is applied. Low/medium/high describe participant-reported relative
effort, not calibrated force. Static describes the instructed condition, not
automatic proof that the arm was motionless. No camera or model supplies labels.

Each session saves below this directory, with `test_condition: static` in its
metadata and truth intervals. Raw EMG, source timestamps, selected effort and
available band context remain available for later review. Only completed
sessions should be committed; do not stage a recording while it is growing.
