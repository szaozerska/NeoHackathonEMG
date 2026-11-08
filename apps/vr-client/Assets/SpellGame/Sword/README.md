# Sword VFX

Energy-blade look for `SwordView` (`Runtime/Game/SwordView.cs`): an opaque white-hot core inside an additive glow,
tinted per player (P1 red, P2 blue), a swept swing trail, and streaking hit sparks with a flash.

| File | What |
|---|---|
| `Shaders/SwordCommon.hlsl` | Shared vertex stage (single-pass multiview/instancing stereo macros), facing ratio, flicker, passthrough-safe glow output |
| `Shaders/BladeCore.shader` | `SpellGame/Sword/BladeCore`: opaque core, white in the middle, player colour at the silhouette |
| `Shaders/BladeGlow.shader` | `SpellGame/Sword/BladeGlow`: additive halo, fades to nothing at its silhouette (no bloom needed) |
| `Shaders/Trail.shader` | `SpellGame/Sword/Trail`: swept ribbon built by `SwordView`, bright tip edge, fades with age |
| `Shaders/Spark.shader` | `SpellGame/Sword/Spark`: procedural soft-dot particle (no texture), streaks on stretched billboards |
| `Materials/*.mat` | Created by `SpellGame/Rebuild Main Scene` (`MainSceneBuilder.CreateSwordView`); tweaks to them are kept on rebuild |

The meshes (round-ended blade capsules, trail ribbon) and particle systems are generated in code; there are no textures.

## Passthrough alpha

The passthrough layer is composited under the eye buffer using the buffer's alpha, so anything that leaves alpha at 0
disappears. The core is opaque and writes alpha 1. All additive shaders use `Blend One One, One OneMinusSrcAlpha`
(add colour; alpha accumulates like premultiplied "over") and output alpha = their brightness (`GlowOutput`), so glow
stays visible over passthrough, fades smoothly at its edges, and never lowers the alpha of what's behind it (no holes).
`_AlphaScale` on each material tunes how strongly glow covers passthrough.

## Sources and licences

- Shader structure follows **Cyanilux, URP Shader Code Templates**
  (https://github.com/Cyanilux/URP_ShaderCodeTemplates), **CC0 1.0**. Nothing else is vendored; all code here is original.
- Evaluated but not used: **CyberAgent NOVA Shader** (https://github.com/CyberAgentGameEntertainment/NovaShader, MIT),
  a full URP particle uber-shader. It works on mobile, but it's a large multi-keyword package for what the sword needs,
  and its blend modes use one blend for colour and alpha, which we need to separate for passthrough.
  Weapon-trail scripts found on GitHub were Asset Store copies or under unclear/ShareAlike licences, so the swept trail
  is written from scratch.
