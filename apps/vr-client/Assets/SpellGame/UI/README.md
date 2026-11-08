# UI themes

The world-space menus and banners (`MatchMenu`, `EndGameView`, the P1/P2 tags in `DebugSkeletonsView`) draw everything
through `Runtime/Game/UiStyle.cs`, which reads the active **`UiTheme`** (`UiStyle.Theme`). A theme is one ScriptableObject:

| Part | What |
| --- | --- |
| `Palette` (`UiPalette`) | `Fill`, `FacetLight`, `FacetDark`, `Rim`, `Ink`, `Text`, `TextDim`, `Accent`, `P1`, `P2`, `Pointer`, `Ash`, `Confetti`, plus optional `Primary` (primary buttons / badges), `Hover` (hover tint) and `Highlight` (hover / selected outline); alpha 0 = derived as before |
| `Shape` (`UiShape`) | `Skew` (tan of the slant, 0 = 90° rectangles), `CornerCut`, `RimWidth`, `OutlineWidth`, `ShadowDrop`, `Facets`, `Sheet` (menus on one big card instead of a card per part) |
| `Text` (`UiTextStyle`) | text outline colour and widths, title colour, label colour on primary buttons, upper-case button labels |
| `Moments` (`UiMoments`) | countdown / FIGHT! / K.O. text, glow, shadow and outline colours (`MatchMomentsView`, `MomentPalette`) |
| `Sounds` (`UiSounds`) | `Hover`, `Press`, `TimeUp` clips; empty = MatchMenu's synthesised tones |
| Fonts / materials | `DisplayFont`, `BodyFont`, their text materials, the card material (`Crystal`) and the moment glow material (`MomentMaterial`) |

The default theme is **Smoky Opal** (`Resources/SpellGameUiTheme.asset`, `UiTheme.ResourceName`): smoke-grey translucent
crystal, plain 90° cards with two flat facets and a white rim, Chakra Petch in white with a dark-ink (#14161f) outline.
P1 red / P2 blue are only used for player names and markers.

The second theme is **Wizard** (`Resources/SpellGameUiTheme Wizard.asset`, `GameSettings.WizardTheme`): aged parchment
sheets with a bevelled gold border, a thin inner gold line and gold corner stars (`Shaders/ParchmentPanel.shader`),
Cinzel Decorative titles and buttons, IM Fell English body text in dark-brown ink with a thin cream halo, arcane purple
(#5d2c86) as the one accent (primary buttons, award badges, titles, hover glow), cream FIGHT! / K.O. with a purple
outline and glow, and chime sounds (`Sounds/Wizard*.wav`). Players pick it in **Settings → Sound & look → Theme**
(`GameSettings.Theme`, saved in PlayerPrefs and applied before the scene loads).

Switching from code: `UiStyle.Theme = UiTheme.Load("SpellGameUiTheme Wizard");` fires `UiStyle.ThemeChanged`; `MatchMenu` and
`EndGameView` rebuild, and long-lived labels can call `UiStyle.Restyle(label, display)`. New themes: Create → SpellGame →
UI Theme in `Assets/SpellGame/Resources/` (copy the fonts/materials from the default or make your own).

| File | What |
| --- | --- |
| `Shaders/CrystalPanel.shader` (`SpellGame/UI/CrystalPanel`) | Procedural card: translucent body, two flat facet planes (lighter top right, darker bottom left), rim, optional ink outline (selected) and hard drop shadow; optional slant and corner cut for other themes. One pass, no textures, no blur. Sizes come in metres through `_Rect` / `_Facet` / `_CornerCut` (set by `UiStyle.Crystal`). |
| `../Fonts/ChakraPetch-BoldItalic.ttf`, `../Fonts/ChakraPetch-Bold.ttf` | Display (titles, buttons, numbers) and body/stats; Bold Italic is shared with the match moments (`MatchMomentsView`). |
| `Shaders/ParchmentPanel.shader` (`SpellGame/UI/ParchmentPanel`) | Wizard card, same properties as CrystalPanel: near-opaque paper (lighter centre, aged mottled edges from cheap value noise in metres), bevelled gold border, inner gold line and four-point corner stars on cards taller than 10 cm, soft hover glow and soft drop shadow; `_CornerCut` is the corner radius. One pass, no textures, no blur. |
| `../Fonts/CinzelDecorative-Bold.ttf`, `../Fonts/IMFellEnglish-Regular.ttf` | Wizard display (titles, buttons, numbers, moments) and body text. |
| `Sounds/WizardHover.wav`, `WizardPress.wav`, `WizardTimeUp.wav` | Wizard menu sounds: glass tick, two-note chime, low gong (synthesised for this project). |
| `../Fonts/*SDF.asset` | Generated: dynamic TextMeshPro SDF font assets (atlas + material as sub-assets). |
| `Materials/*.mat` | Generated: text materials (outline + drop shadow), moment glow materials (`* Moment.mat`), `Crystal.mat` and `Parchment.mat`. Tweaks are kept on rebuild. |
| `../Resources/SpellGameUiTheme.asset`, `../Resources/SpellGameUiTheme Wizard.asset` | Generated themes (Smoky Opal, Wizard). Rebuilds only refresh their fonts/materials, so palette/shape tweaks are kept. |

Everything generated is made by `UiThemeBuilder` as the first step of **SpellGame → Rebuild Main Scene**. The first run also
imports TMP Essential Resources into `Assets/TextMesh Pro/` (needed by every TextMeshPro component) and then rebuilds the
scene once more by itself. A headless `QuestBuild.BuildBatch` on a project without them stops after the import with
"run the build again"; the second run works. If you built the earlier Rajdhani version, delete the old
`Fonts/Rajdhani-* SDF.asset` and `UI/Materials/Rajdhani-* Text.mat` files.

## Passthrough / alpha

The card shader uses premultiplied-alpha "over" blending for colour and alpha (`Blend One OneMinusSrcAlpha, One OneMinusSrcAlpha`),
like the shield shaders: the smoky body writes partial alpha (about 65–80 %) so the room shows through it, while the rim, outline
and text stay solid. Text is white with a thick ink outline everywhere, so it reads on the cards and against white walls.
The parchment shader blends the same way but writes about 96 % alpha, so dark-brown text on it reads in a bright room;
text off the cards (status line, player tags) keeps a cream halo.

## Settings

`Runtime/Game/GameSettings.cs` keeps the player's settings in PlayerPrefs; the Settings screen (`MatchMenu`, from the main
menu, the ready screen and the in-match pause menu) has two tabs:

- **Sound & look:** theme, master volume (`AudioListener.volume`), effects volume (spell sounds, menu tones, moment
  sounds), announcer volume.
- **Comfort:** menu distance (0.6–1.8 m) and height (±30 cm; also moves the results banner), menu & text size (80–140 %,
  scales menus, timer badge and results banner), vibration strength (menu and moment buzzes; the band's own haptics are
  sent by the server), damage flashes at the edges of the view (`HealthView`, 0 = off), K.O. slow motion and darkened
  passthrough on/off (`MatchMomentsView`).

## Sources and licences

- Chakra Petch by Cadson Demak, from [google/fonts `ofl/chakrapetch`](https://github.com/google/fonts/tree/main/ofl/chakrapetch),
  SIL Open Font License 1.1 (`../Fonts/ChakraPetch-OFL.txt`).
- Cinzel Decorative by Natanael Gama, from [google/fonts `ofl/cinzeldecorative`](https://github.com/google/fonts/tree/main/ofl/cinzeldecorative),
  SIL Open Font License 1.1 (`../Fonts/CinzelDecorative-OFL.txt`).
- IM Fell English by Igino Marini, from [google/fonts `ofl/imfellenglish`](https://github.com/google/fonts/tree/main/ofl/imfellenglish),
  SIL Open Font License 1.1 (`../Fonts/IMFellEnglish-OFL.txt`).
- The wizard sounds are synthesised for this project.
- Shader and theme code are written for this project.
