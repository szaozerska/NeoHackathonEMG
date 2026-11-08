# AI opponent wizard

`Wizard.fbx` and `Wizard_Texture.png` are Quaternius's "Animated Wizard" from the RPG Character Pack (Nov 2020,
https://quaternius.com/packs/rpgcharacters.html; also on https://poly.pizza/m/kttbFvCl2C), by Quaternius. Released as
CC0 on the pack page (Poly Pizza lists CC-BY); credit: Quaternius. Converted from the glTF with Blender 3.0
(actions renamed to their short names, e.g. `Idle`, `Spell1`), about 5.4k triangles and one 1024² texture.

`MainSceneBuilder` sets the import settings, generates `Wizard.controller` and the unlit `WizardBody` material;
`AiWizardView` drives it.
