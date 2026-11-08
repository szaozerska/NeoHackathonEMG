# UI theme

Crystal look for the world-space menus and banners (`MatchMenu`, `EndGameView`, the P1/P2 tags in `DebugSkeletonsView`).
All colours, panel styles and text helpers are in `Runtime/Game/UiStyle.cs`; change `UiStyle.Accent` to re-tint everything.
P1 red / P2 blue (`UiStyle.P1`, `UiStyle.P2`) are only used for player names and markers.

| File | What |
| --- | --- |
| `Shaders/CrystalPanel.shader` (`SpellGame/UI/CrystalPanel`) | Procedural translucent panel: crystal tint, bright rim, cut corners, inner facet, slow highlight streak, outer glow, optional top accent strip. One pass, no textures. Sizes come in metres through `_Rect` / `_Facet` (set by `UiStyle.Crystal`). |
| `../Fonts/Rajdhani-Bold.ttf`, `../Fonts/Rajdhani-SemiBold.ttf` | Display (titles, buttons, numbers) and body text; shared with the match moments (`MatchMomentsView`). |
| `../Fonts/Rajdhani-* SDF.asset` | Generated: dynamic TextMeshPro SDF font assets (atlas + material as sub-assets). |
| `Materials/*.mat` | Generated: text materials with outline + underlay, and `Crystal.mat`. Tweaks are kept on rebuild. |
| `../Resources/SpellGameUiTheme.asset` | Generated `UiTheme`: the fonts and materials above, loaded by `UiStyle` at runtime. |

Everything generated is made by `UiThemeBuilder` as the first step of **SpellGame → Rebuild Main Scene**. The first run also
imports TMP Essential Resources into `Assets/TextMesh Pro/` (needed by every TextMeshPro component) and then rebuilds the
scene once more by itself. A headless `QuestBuild.BuildBatch` on a project without them stops after the import with
"run the build again"; the second run works.

## Passthrough / alpha

The panel shader uses premultiplied-alpha "over" blending for colour and alpha (`Blend One OneMinusSrcAlpha, One OneMinusSrcAlpha`),
like the shield shaders: the crystal body writes partial alpha so the room shows through it, tinted and dimmed, while the
rim and glow write more alpha and stay bright in a lit room. Text has a dark outline and a soft underlay for the same reason.

## Sources and licences

- Rajdhani by Indian Type Foundry, from [google/fonts `ofl/rajdhani`](https://github.com/google/fonts/tree/main/ofl/rajdhani),
  SIL Open Font License 1.1 (`../Fonts/Rajdhani-OFL.txt`).
- Shader and theme code are written for this project.
