# UI theme ("Opal")

Smash Ultimate-style look for the world-space menus and banners (`MatchMenu`, `EndGameView`, the P1/P2 tags in
`DebugSkeletonsView`): slanted (12°) milky-white, half-transparent crystal cards with two flat facets and a white rim,
heavy italic type in white with a dark-ink outline, ink text on the cards.
All colours, card styles and text helpers are in `Runtime/Game/UiStyle.cs` (palette block at the top); `UiStyle.Accent`
is the one tint (the pastel shimmer). P1 red / P2 blue (`UiStyle.P1`, `UiStyle.P2`) are only used for player names and markers.

| File | What |
| --- | --- |
| `Shaders/CrystalPanel.shader` (`SpellGame/UI/CrystalPanel`) | Procedural slanted card: milky body, two flat facet planes (lighter top right, pastel bottom left), white rim, optional ink outline (selected) and hard drop shadow. One pass, no textures, no blur. Sizes come in metres through `_Rect` / `_Facet` (set by `UiStyle.Crystal`). |
| `../Fonts/ChakraPetch-BoldItalic.ttf`, `../Fonts/ChakraPetch-Bold.ttf` | Display (titles, buttons, numbers) and body/stats; Bold Italic is shared with the match moments (`MatchMomentsView`). |
| `../Fonts/ChakraPetch-* SDF.asset` | Generated: dynamic TextMeshPro SDF font assets (atlas + material as sub-assets). |
| `Materials/*.mat` | Generated: text materials with ink outline + ink drop shadow, and `Crystal.mat`. Tweaks are kept on rebuild. |
| `../Resources/SpellGameUiTheme.asset` | Generated `UiTheme`: the fonts and materials above, loaded by `UiStyle` at runtime. |

Everything generated is made by `UiThemeBuilder` as the first step of **SpellGame → Rebuild Main Scene**. The first run also
imports TMP Essential Resources into `Assets/TextMesh Pro/` (needed by every TextMeshPro component) and then rebuilds the
scene once more by itself. A headless `QuestBuild.BuildBatch` on a project without them stops after the import with
"run the build again"; the second run works. If you built the earlier Rajdhani version, delete the old
`Fonts/Rajdhani-* SDF.asset` and `UI/Materials/Rajdhani-* Text.mat` files.

## Passthrough / alpha

The card shader uses premultiplied-alpha "over" blending for colour and alpha (`Blend One OneMinusSrcAlpha, One OneMinusSrcAlpha`),
like the shield shaders: the milky body writes partial alpha (55–85 %) so the room shows through it, while the rim, outline
and text stay solid. White text always has the thick ink outline; text on the cards is ink, since white on white doesn't read.

## Sources and licences

- Chakra Petch by Cadson Demak, from [google/fonts `ofl/chakrapetch`](https://github.com/google/fonts/tree/main/ofl/chakrapetch),
  SIL Open Font License 1.1 (`../Fonts/ChakraPetch-OFL.txt`).
- Shader and theme code are written for this project.
