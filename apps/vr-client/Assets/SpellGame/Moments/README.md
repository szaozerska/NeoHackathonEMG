# Match moments assets

Announcer lines for `MatchMomentsView` (`Announcer/*.ogg`: three, two, one, fight, ko, time, sudden_death).

- Generated with [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (weights Apache-2.0) via
  [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) (MIT), voice `am_fenrir`, then pitched down,
  EQ'd, compressed, given a short echo, trimmed and normalized with ffmpeg. The output audio carries no
  extra licence restriction and may be committed and shipped.
- Drum, impact, bass and whoosh effects are synthesised at runtime in `MatchMomentsView`.

Font: `../Fonts/ChakraPetch-BoldItalic.ttf` (Cadson Demak, SIL Open Font License 1.1, see `../Fonts/ChakraPetch-OFL.txt`).
SpellGame/Rebuild Main Scene imports TMP Essential Resources and creates `ChakraPetch-BoldItalic SDF.asset` and
`MomentText.mat` here on first run.
