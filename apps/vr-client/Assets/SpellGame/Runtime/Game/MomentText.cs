using TMPro;
using UnityEngine;

namespace SpellGame.Game
{
    /// <summary>
    /// Colours of the big match moments (<see cref="MatchMomentsView"/>), kept together so they can follow the theme's
    /// accent: white text with a coloured glow, plus a dark drop shadow on the K.O.
    /// </summary>
    public static class MomentPalette
    {
        public static readonly Color Text = Color.white;
        public static readonly Color CountdownGlow = new(0.35f, 0.65f, 1f, 0.85f);
        public static readonly Color FightText = new(1f, 0.87f, 0.5f);
        public static readonly Color FightGlow = new(1f, 0.45f, 0.1f, 0.9f);
        public static readonly Color KoGlow = new(0.95f, 0.15f, 0.15f, 0.8f);
        public static readonly Color KoShadow = new(0.4f, 0.05f, 0.06f, 1f);
        public static readonly Color NoShadow = Color.clear;
    }

    /// <summary>
    /// World-space TextMeshPro text for the match moments, the one place they create text (so it can move onto the shared
    /// theme helpers). Sizes: a TextMeshPro line is about <c>fontSize × 0.12</c> m tall, capitals about <c>fontSize × 0.07</c> m.
    /// </summary>
    public static class MomentText
    {
        private static bool? _available;

        /// <summary>
        /// False until TMP Essential Resources are imported: TextMeshPro throws on creation without <c>Resources/TMP Settings</c>.
        /// SpellGame/Rebuild Main Scene imports them.
        /// </summary>
        public static bool Available => _available ??= Resources.Load<TMP_Settings>("TMP Settings") != null;

        /// <summary>
        /// A copy of <paramref name="template"/> with the given glow and drop shadow. The template should be a saved material
        /// with GLOW_ON and UNDERLAY_ON enabled, otherwise a player build strips those shader variants.
        /// </summary>
        public static Material GlowMaterial(Material template, Color glow, Color shadow)
        {
            var material = new Material(template);
            material.EnableKeyword("GLOW_ON");
            material.SetColor("_GlowColor", glow);
            material.SetFloat("_GlowOffset", 0f);
            material.SetFloat("_GlowInner", 0.08f);
            material.SetFloat("_GlowOuter", 0.6f);
            material.SetFloat("_GlowPower", 0.55f);
            material.EnableKeyword("UNDERLAY_ON");
            material.SetColor("_UnderlayColor", shadow);
            material.SetFloat("_UnderlayOffsetX", 0.35f);
            material.SetFloat("_UnderlayOffsetY", -0.35f);
            material.SetFloat("_UnderlayDilate", 0.2f);
            material.SetFloat("_UnderlaySoftness", 0.05f);
            return material;
        }

        public static TextMeshPro Create(string name, Transform parent, TMP_FontAsset font, Material material, string text,
            float fontSize, Color color, bool italic)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            var label = go.AddComponent<TextMeshPro>();
            if (font != null)
                label.font = font;
            if (material != null)
                label.fontSharedMaterial = material;
            label.text = text;
            label.fontSize = fontSize;
            label.fontStyle = italic ? FontStyles.Italic : FontStyles.Normal;
            label.color = color;
            label.alignment = TextAlignmentOptions.Center;
            label.overflowMode = TextOverflowModes.Overflow;
            label.extraPadding = true;
            label.rectTransform.sizeDelta = new Vector2(20f, 5f);
            var renderer = go.GetComponent<MeshRenderer>();
            renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            renderer.receiveShadows = false;
            return label;
        }
    }
}
