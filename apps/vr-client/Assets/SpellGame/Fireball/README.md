# Fireball VFX

Held orb, projectile, explosion and cooldown ember for `FireballView`. The effects are built in code by
`Runtime/Game/FireballVfx.cs`; materials are generated into `Materials/` by `SpellGame/Rebuild Main Scene`
(`MainSceneBuilder.CreateFireballView`). Re-run it after changing anything here.

## Layers

- **Core**: sphere on `Shaders/FireballCore.shader`, an opaque unlit URP shader with two octaves of value noise
  flowing upward, ramped white-hot centre → orange → deep red rim. Its size is the gameplay size (`projectileDiameter`
  etc. in `FireballView`); everything else is cosmetic and larger, so it's easy to see at 1–5 m.
- **Particles** (Shuriken, billboards, `Shaders/FireballParticle.shader`): a flickering glow halo, rising flame tongues
  and embers on the held orb; a flame-puff trail (emitted per metre), a smoke trail, embers and a glowing
  `TrailRenderer` ribbon on the projectile; flash + shockwave ring + fire + sparks + smoke on a hit (smaller on a shield
  block), smoke + embers on a fizzle/expiry, a flash + spark burst on the snap and on the throw.

## Passthrough alpha

Passthrough is composited using the eye buffer's alpha, so every layer writes real coverage into alpha:

- the core is opaque (alpha 1);
- glow/flame materials blend colour additively but alpha "over": `Blend One One, One OneMinusSrcAlpha`, writing
  `mask × _AlphaWrite` (0.5–0.7), so fire both brightens and partly covers the real room instead of vanishing;
- smoke is ordinary premultiplied alpha (`Blend One OneMinusSrcAlpha, One OneMinusSrcAlpha`), so it can darken passthrough.

No depth/opaque texture, no HDR, no lights: it stays cheap on Quest 3.

## Sources and licences

| File | Source | Licence |
| --- | --- | --- |
| `Textures/fire_01.png`, `flame_05.png`, `smoke_04.png`, `light_03.png` | [Kenney Particle Pack 1.1](https://kenney.nl/assets/particle-pack) by Kenney Vleugels, taken from the [Calinou/kenney-particle-pack](https://github.com/Calinou/kenney-particle-pack) mirror. Converted to white RGB + the original alpha and downscaled to 256×256. | CC0 1.0 (`Textures/Kenney-ParticlePack-LICENSE.txt`) |
| `Textures/glow_soft.png` | Generated for this project (radial falloff). | CC0 1.0 |
| `Shaders/*.shader` | Written for this project. | Same as this repository |
