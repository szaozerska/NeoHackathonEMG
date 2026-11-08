# Shield VFX

Energy force-field look for `ShieldView` (`Runtime/Game/ShieldView.cs`). Everything is procedural: two hand-written
URP shaders, a dome mesh generated at runtime and two Shuriken particle emitters. No textures, no packages.

| File | What |
| --- | --- |
| `Shaders/ForceFieldShield.shader` (`SpellGame/Shield/ForceField`) | The field: fresnel rim, edge ring, hex grid with per-cell flicker, radial energy pulse, scrolling noise, up to 4 hit ripples (`_HitPoints`), radial spawn reveal (`_Spawn`), gold boost tint (`_Boost`). |
| `Shaders/ShieldSpark.shader` (`SpellGame/Shield/Spark`) | Particles: soft glowing dot (`_Ring = 0`, stretched into streaks for sparks) or soft ring (`_Ring = 1`, shock rings). Uses particle vertex colour. |
| `ShieldForceField.mat`, `ShieldSpark.mat`, `ShieldRing.mat` | Created by `MainSceneBuilder.CreateShieldView` on `SpellGame/Rebuild Main Scene`. Delete them to reset to shader defaults. |

## Passthrough / alpha

Both shaders use premultiplied-alpha "over" blending for colour and alpha (`Blend One OneMinusSrcAlpha, One OneMinusSrcAlpha`):
the eye buffer's alpha ends up as real coverage, so the passthrough underlay is shown where the effect is thin and dimmed
where it is dense. Glow brighter than its coverage still adds light. Alpha is also raised from brightness (`_GlowAlpha`),
so bright lines/sparks darken the room behind them a little and stay readable in bright rooms; plain additive
(`Blend One One` with alpha 0) would make the effect vanish under passthrough.

## Sources and licences

No existing package fit as-is, so the shaders are new, with two small pieces adapted from MIT-licensed repos:

- **K0chiko/EnergyShieldShader** — https://github.com/K0chiko/EnergyShieldShader — MIT, Copyright (c) 2026 K0chiko
  (Aleksandr Panichevskii). Adapted: the procedural hex-grid functions (`hexDist`/`getHexGrid` → `HexDist`/`HexCell`,
  fixed to tile negative coordinates and anti-aliased with `fwidth`). Not used as-is: it samples `_CameraOpaqueTexture`
  (disabled in `QuestURP`, costly on Quest), needs LFS textures and writes a constant alpha (0 by default), which breaks
  under passthrough.
- **AdultLink/HoloShield** — https://github.com/AdultLink/HoloShield — MIT, Copyright (c) 2018 Guillermo Angel.
  Adapted: the fresnel rim formulation (bias + scale · (1 − N·V)^power). Not used as-is: Built-in RP surface shader
  with tessellation (shader model 4.6), not URP and too heavy for Quest.

Both licences require keeping the copyright notice with substantial portions; the snippets above are small and
rewritten, but the notices are kept here regardless.

```
MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the
Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## Cost

One dome (~770 vertices, one transparent draw) per raised shield, ALU-only fragment shader (no texture samples), and two
pooled emitters (max 300 + 16 particles) that only emit on events.

## Tuning

Hit-tested geometry is unchanged: the dome's rim is the server's disc (`shieldRadius`/`shieldOffset` on `ShieldView`
must match `Tuning.shield_radius`/`shield_offset`; `parryMinBoost` mirrors `Tuning.shield_parry_min_boost` and only
drives the gold "parry ready" ring). The dome bulges `domeDepth` × diameter (default 7 cm) in front of that disc.
Look knobs are on the `ShieldForceField` material (colours, `_FillAlpha`, `_GlowAlpha`, `_BackFace` = how strongly you
see your own shield from behind, hex size/width, ripple speed/duration).
