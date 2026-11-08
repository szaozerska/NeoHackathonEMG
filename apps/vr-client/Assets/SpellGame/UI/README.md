# UI themes

The world-space menus and banners (`MatchMenu`, `EndGameView`, the P1/P2 tags in `DebugSkeletonsView`) draw everything
through `Runtime/Game/UiStyle.cs`, which reads the active **`UiTheme`** (`UiStyle.Theme`). A theme is one ScriptableObject:

| Part | What |
| --- | --- |
| `Palette` (`UiPalette`) | `Fill`, `FacetLight`, `FacetDark`, `Rim`, `Ink`, `Text`, `TextDim`, `Accent`, `P1`, `P2`, `Pointer`, `Ash`, `Confetti` |
| `Shape` (`UiShape`) | `Skew` (tan of the slant, 0 = 90° rectangles), `CornerCut`, `RimWidth`, `OutlineWidth`, `ShadowDrop`, `Facets` |
| `Sounds` (`UiSounds`) | `Hover`, `Press`, `TimeUp` clips; empty = MatchMenu's synthesised tones |
| Fonts / materials | `DisplayFont`, `BodyFont`, their text materials, and the card material (`Crystal`) |

The default theme is **Smoky Opal** (`Resources/SpellGameUiTheme.asset`, `UiTheme.ResourceName`): smoke-grey translucent
crystal, plain 90° cards with two flat facets and a white rim, Chakra Petch in white with a dark-ink (#14161f) outline.
P1 red / P2 blue are only used for player names and markers.

Switching: `UiStyle.Theme = UiTheme.Load("SpellGameUiTheme Wizard");` fires `UiStyle.ThemeChanged`; `MatchMenu` and
`EndGameView` rebuild, and long-lived labels can call `UiStyle.Restyle(label, display)`. New themes: Create → SpellGame →
UI Theme in `Assets/SpellGame/Resources/` (copy the fonts/materials from the default or make your own).

| File | What |
| --- | --- |
| `Shaders/CrystalPanel.shader` (`SpellGame/UI/CrystalPanel`) | Procedural card: translucent body, two flat facet planes (lighter top right, darker bottom left), rim, optional ink outline (selected) and hard drop shadow; optional slant and corner cut for other themes. One pass, no textures, no blur. Sizes come in metres through `_Rect` / `_Facet` / `_CornerCut` (set by `UiStyle.Crystal`). |
| `../Fonts/ChakraPetch-BoldItalic.ttf`, `../Fonts/ChakraPetch-Bold.ttf` | Display (titles, buttons, numbers) and body/stats; Bold Italic is shared with the match moments (`MatchMomentsView`). |
| `../Fonts/ChakraPetch-* SDF.asset` | Generated: dynamic TextMeshPro SDF font assets (atlas + material as sub-assets). |
| `Materials/*.mat` | Generated: text materials with ink outline + ink drop shadow, and `Crystal.mat`. Tweaks are kept on rebuild. |
| `../Resources/SpellGameUiTheme.asset` | Generated default `UiTheme` (Smoky Opal). Rebuilds only refresh its fonts/materials, so palette/shape tweaks are kept. |

Everything generated is made by `UiThemeBuilder` as the first step of **SpellGame → Rebuild Main Scene**. The first run also
imports TMP Essential Resources into `Assets/TextMesh Pro/` (needed by every TextMeshPro component) and then rebuilds the
scene once more by itself. A headless `QuestBuild.BuildBatch` on a project without them stops after the import with
"run the build again"; the second run works. If you built the earlier Rajdhani version, delete the old
`Fonts/Rajdhani-* SDF.asset` and `UI/Materials/Rajdhani-* Text.mat` files.

## Passthrough / alpha

The card shader uses premultiplied-alpha "over" blending for colour and alpha (`Blend One OneMinusSrcAlpha, One OneMinusSrcAlpha`),
like the shield shaders: the smoky body writes partial alpha (about 65–80 %) so the room shows through it, while the rim, outline
and text stay solid. Text is white with a thick ink outline everywhere, so it reads on the cards and against white walls.

## Sources and licences

- Chakra Petch by Cadson Demak, from [google/fonts `ofl/chakrapetch`](https://github.com/google/fonts/tree/main/ofl/chakrapetch),
  SIL Open Font License 1.1 (`../Fonts/ChakraPetch-OFL.txt`).
- Shader and theme code are written for this project.
