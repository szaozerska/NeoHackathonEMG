using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.Rendering;

namespace SpellGame.Game
{
    /// <summary>
    /// Shared look for the world-space UI ("Opal", Smash Ultimate style): slanted, milky-white half-transparent crystal
    /// cards with two flat facets and a white rim, heavy italic Chakra Petch type in white with a dark-ink outline, ink
    /// text on the cards, and P1 red / P2 blue only for player names and markers. All colours live in the palette below.
    /// </summary>
    public static class UiStyle
    {
        // ---------------------------------------------------------------- palette (every UI colour is here)

        /// <summary>The one tint: the pastel shimmer in the lower facet and on selected cards. Change it to re-tint the UI.</summary>
        public static readonly Color Accent = new(0.86f, 0.8f, 1f);
        /// <summary>Milky crystal body (alpha set per style).</summary>
        public static readonly Color Opal = new(0.97f, 0.97f, 1f);
        public static readonly Color Rim = Color.white;
        /// <summary>Dark ink #2a2f45: text outlines, drop shadows, text on cards, the selected-card outline.</summary>
        public static readonly Color Ink = new(0.165f, 0.184f, 0.271f);
        public static readonly Color Text = Color.white;
        public static readonly Color TextDim = new(0.9f, 0.91f, 0.96f);
        public static readonly Color P1 = new(1f, 0.25f, 0.25f);
        public static readonly Color P2 = new(0.25f, 0.5f, 1f);
        public static readonly Color Pointer = Color.white;
        public static readonly Color Ash = new(0.35f, 0.35f, 0.4f);
        public static readonly Color[] Confetti = { Color.white, Accent, Opal };

        /// <summary>tan 12°: the slant of every card and button.</summary>
        public const float Skew = 0.2126f;

        /// <summary>P1 red, P2 blue, anyone else white (white text always has the ink outline).</summary>
        public static Color PlayerColor(string playerId) => playerId switch
        {
            "P1" => P1,
            "P2" => P2,
            _ => Text,
        };

        /// <summary>Like <see cref="PlayerColor"/> but ink for others, for names inside ink body text on a card.</summary>
        public static Color PlayerInk(string playerId) => playerId is "P1" or "P2" ? PlayerColor(playerId) : Ink;

        public static string Hex(Color color) => "#" + ColorUtility.ToHtmlStringRGB(color);

        public static Color WithAlpha(Color color, float alpha) => new(color.r, color.g, color.b, alpha);

        // ---------------------------------------------------------------- crystal cards

        /// <summary>Parameters of the <c>SpellGame/UI/CrystalPanel</c> shader. Lengths in metres.</summary>
        public struct CrystalStyle
        {
            public Color Fill;        // opal body, alpha = opacity
            public Color Rim;         // bright inner rim
            public Color Outline;     // ink outline outside the rim (alpha 0 = none)
            public Color Shimmer;     // tint of the lower facet (alpha = strength)
            public Color Shadow;      // hard drop shadow under the card (alpha 0 = none)
            public float Skew;        // tan of the slant
            public float RimWidth;
            public float OutlineWidth;
            public float Facet;       // strength of the two facet planes
            public float ShadowDrop;
        }

        /// <summary>Title cards ("SPELL DUEL", "GAME!") and text panels.</summary>
        public static CrystalStyle Panel => new()
        {
            Fill = WithAlpha(Opal, 0.72f), Rim = Rim, Outline = Color.clear, Shimmer = WithAlpha(Accent, 0.6f),
            Shadow = WithAlpha(Ink, 0.35f), Skew = Skew, RimWidth = 0.004f, OutlineWidth = 0f, Facet = 1f, ShadowDrop = 0.008f,
        };

        /// <summary>Result cards and body text.</summary>
        public static CrystalStyle Card => new()
        {
            Fill = WithAlpha(Opal, 0.64f), Rim = Rim, Outline = Color.clear, Shimmer = WithAlpha(Accent, 0.5f),
            Shadow = WithAlpha(Ink, 0.3f), Skew = Skew, RimWidth = 0.003f, OutlineWidth = 0f, Facet = 1f, ShadowDrop = 0.006f,
        };

        /// <summary>Selected / primary button: brighter opal with an ink outline.</summary>
        public static CrystalStyle Primary => new()
        {
            Fill = WithAlpha(Color.Lerp(Opal, Accent, 0.3f), 0.85f), Rim = Rim, Outline = Ink, Shimmer = WithAlpha(Accent, 0.7f),
            Shadow = WithAlpha(Ink, 0.3f), Skew = Skew, RimWidth = 0.0025f, OutlineWidth = 0.004f, Facet = 1f, ShadowDrop = 0.005f,
        };

        /// <summary>Secondary button: plain translucent white card.</summary>
        public static CrystalStyle Secondary => new()
        {
            Fill = WithAlpha(Opal, 0.55f), Rim = Rim, Outline = Color.clear, Shimmer = WithAlpha(Accent, 0.25f),
            Shadow = WithAlpha(Ink, 0.25f), Skew = Skew, RimWidth = 0.0025f, OutlineWidth = 0f, Facet = 0.6f, ShadowDrop = 0.005f,
        };

        /// <summary>Small always-on badges (match timer).</summary>
        public static CrystalStyle Hud => new()
        {
            Fill = WithAlpha(Opal, 0.75f), Rim = Rim, Outline = Color.clear, Shimmer = WithAlpha(Accent, 0.5f),
            Shadow = WithAlpha(Ink, 0.3f), Skew = Skew, RimWidth = 0.003f, OutlineWidth = 0f, Facet = 1f, ShadowDrop = 0.004f,
        };

        /// <summary>Award tags on result cards: solid white with ink text.</summary>
        public static CrystalStyle Badge => new()
        {
            Fill = WithAlpha(Color.white, 0.95f), Rim = Rim, Outline = Color.clear, Shimmer = Color.clear,
            Shadow = Color.clear, Skew = Skew, RimWidth = 0f, OutlineWidth = 0f, Facet = 0f, ShadowDrop = 0f,
        };

        /// <summary>Dwell progress bar.</summary>
        public static CrystalStyle Bar => new()
        {
            Fill = WithAlpha(Ink, 0.9f), Rim = Color.clear, Outline = Color.clear, Shimmer = Color.clear,
            Shadow = Color.clear, Skew = Skew, RimWidth = 0f, OutlineWidth = 0f, Facet = 0f, ShadowDrop = 0f,
        };

        /// <summary>Pointer on it: brighter, more shimmer, a thicker ink outline.</summary>
        public static CrystalStyle Hovered(CrystalStyle style)
        {
            style.Fill = WithAlpha(Color.Lerp(style.Fill, Accent, 0.3f), Mathf.Max(style.Fill.a, 0.85f));
            style.Shimmer = WithAlpha(Accent, Mathf.Max(style.Shimmer.a, 0.8f));
            style.Outline = Ink;
            style.OutlineWidth = Mathf.Max(style.OutlineWidth, 0.0055f);
            return style;
        }

        /// <summary>Highlight by <paramref name="amount"/> (0..1): winner card, timer in its last seconds.</summary>
        public static CrystalStyle Pulsing(CrystalStyle style, float amount)
        {
            amount = Mathf.Clamp01(amount);
            style.Fill = Color.Lerp(style.Fill, WithAlpha(Color.Lerp(Opal, Accent, 0.4f), 0.88f), amount);
            style.Outline = WithAlpha(Ink, Mathf.Max(style.Outline.a, amount));
            style.OutlineWidth = Mathf.Lerp(style.OutlineWidth, 0.006f, amount);
            return style;
        }

        /// <summary>A crystal quad and its own material; restyle or resize it at any time.</summary>
        public sealed class Crystal
        {
            private static readonly int FillId = Shader.PropertyToID("_FillColor");
            private static readonly int RimId = Shader.PropertyToID("_RimColor");
            private static readonly int OutlineId = Shader.PropertyToID("_OutlineColor");
            private static readonly int ShimmerId = Shader.PropertyToID("_ShimmerColor");
            private static readonly int ShadowId = Shader.PropertyToID("_ShadowColor");
            private static readonly int RectId = Shader.PropertyToID("_Rect");
            private static readonly int FacetId = Shader.PropertyToID("_Facet");

            public Transform Transform { get; }
            public Material Material { get; }
            public Vector2 Size { get; private set; }
            public CrystalStyle Style { get; private set; }

            internal Crystal(Transform transform, Material material, Vector2 size, CrystalStyle style)
            {
                Transform = transform;
                Material = material;
                Apply(style, size);
            }

            public void Apply(CrystalStyle style) => Apply(style, Size);

            public void Resize(Vector2 size) => Apply(Style, size);

            /// <summary><paramref name="size"/> is the card at mid height; the slant adds |skew| × height to the quad.</summary>
            public void Apply(CrystalStyle style, Vector2 size)
            {
                Style = style;
                Size = size;
                var w = Mathf.Max(size.x, 1e-4f);
                var h = Mathf.Max(size.y, 1e-4f);
                var margin = style.OutlineWidth + style.ShadowDrop + 0.003f;
                Transform.localScale = new Vector3(w + Mathf.Abs(style.Skew) * h + 2f * margin, h + 2f * margin, 1f);
                if (Material == null)
                    return;
                Material.SetColor(FillId, style.Fill);
                Material.SetColor(RimId, style.Rim);
                Material.SetColor(OutlineId, style.Outline);
                Material.SetColor(ShimmerId, style.Shimmer);
                Material.SetColor(ShadowId, style.Shadow);
                Material.SetVector(RectId, new Vector4(w, h, style.Skew, margin));
                Material.SetVector(FacetId, new Vector4(style.RimWidth, style.OutlineWidth, style.Facet, style.ShadowDrop));
            }
        }

        /// <summary>
        /// A crystal card of <paramref name="size"/> centred at <paramref name="localPosition"/>. Its material is new;
        /// pass <paramref name="owned"/> to collect it so the owner can <see cref="DestroyAll"/> when it rebuilds.
        /// </summary>
        public static Crystal CreateCrystal(string name, Transform parent, Vector2 size, CrystalStyle style, Vector3 localPosition,
            int sortingOrder = SortPanel, List<Material> owned = null)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            go.transform.localPosition = localPosition;
            go.AddComponent<MeshFilter>().sharedMesh = QuadMesh;
            var renderer = go.AddComponent<MeshRenderer>();
            renderer.shadowCastingMode = ShadowCastingMode.Off;
            renderer.receiveShadows = false;
            renderer.sortingOrder = sortingOrder;
            var source = CrystalSource;
            var material = source != null ? new Material(source) : null;
            renderer.sharedMaterial = material;
            if (material != null)
                owned?.Add(material);
            return new Crystal(go.transform, material, size, style);
        }

        // ---------------------------------------------------------------- text

        /// <summary>
        /// How a label is drawn. <see cref="Outlined"/>: thick ink outline (white or player-coloured text, readable on
        /// the cards and in a bright room). <see cref="Title"/>: outline plus a hard ink drop shadow. <see cref="Ink"/>:
        /// plain dark-ink text for stats and button labels on the white cards.
        /// </summary>
        public enum Look { Outlined, Title, Ink }

        public const int SortPanel = 10;
        public const int SortSurface = 11;
        public const int SortBar = 12;
        public const int SortText = 13;

        /// <summary>
        /// A TextMeshPro label whose line height is about <paramref name="size"/> m. Display = Chakra Petch Bold Italic
        /// (titles, buttons, numbers), otherwise Chakra Petch Bold (stats, body).
        /// </summary>
        public static TextMeshPro CreateText(string name, Transform parent, string text, Vector3 localPosition, float size, Color color,
            bool display = false, Look look = Look.Outlined, TextAlignmentOptions alignment = TextAlignmentOptions.Center,
            float width = 1.2f, float spacing = 0f)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            go.transform.localPosition = localPosition;
            var label = go.AddComponent<TextMeshPro>();
            var theme = Theme;
            var font = theme != null ? (display ? theme.DisplayFont : theme.BodyFont) : null;
            if (font != null)
            {
                label.font = font;
                label.fontSharedMaterial = TextMaterial(display, look);
            }
            label.fontSize = size * 10f;
            label.rectTransform.sizeDelta = new Vector2(width, size * 1.5f);
            label.alignment = alignment;
            label.textWrappingMode = TextWrappingModes.NoWrap;
            label.overflowMode = TextOverflowModes.Overflow;
            label.richText = true;
            label.characterSpacing = spacing;
            label.color = color;
            label.text = text;
            label.sortingOrder = SortText;
            label.renderer.shadowCastingMode = ShadowCastingMode.Off;
            label.renderer.receiveShadows = false;
            return label;
        }

        /// <summary>Height in metres <paramref name="label"/> needs for its current text (lines × line height).</summary>
        public static float Height(TextMeshPro label) =>
            string.IsNullOrEmpty(label.text) ? 0f : label.GetPreferredValues(label.text).y;

        /// <summary>Width in metres of <paramref name="label"/>'s current text.</summary>
        public static float Width(TextMeshPro label) =>
            string.IsNullOrEmpty(label.text) ? 0f : label.GetPreferredValues(label.text).x;

        /// <summary>Destroys materials collected by <see cref="CreateCrystal"/> and clears the list.</summary>
        public static void DestroyAll(List<Material> materials)
        {
            foreach (var material in materials)
                if (material != null)
                    Object.Destroy(material);
            materials.Clear();
        }

        // ---------------------------------------------------------------- resources

        private static readonly int OutlineWidthId = Shader.PropertyToID("_OutlineWidth");
        private static readonly int UnderlayColorId = Shader.PropertyToID("_UnderlayColor");
        private static readonly int FaceDilateId = Shader.PropertyToID("_FaceDilate");

        private static UiTheme _theme;
        private static bool _warned;
        private static Mesh _quadMesh;
        private static readonly Dictionary<(bool Display, Look Look), Material> TextMaterials = new();

        public static UiTheme Theme
        {
            get
            {
                if (_theme != null)
                    return _theme;
                _theme = Resources.Load<UiTheme>(UiTheme.ResourceName);
                if (_theme == null && !_warned)
                {
                    _warned = true;
                    Debug.LogError($"[SpellGame] UI theme '{UiTheme.ResourceName}' not found in Resources; run SpellGame → Rebuild Main Scene.");
                }
                return _theme;
            }
        }

        private static Material CrystalSource
        {
            get
            {
                var theme = Theme;
                return theme != null ? theme.Crystal : null;
            }
        }

        /// <summary>Shared per font and look: a copy of the theme's font material (ink outline + ink drop shadow).</summary>
        private static Material TextMaterial(bool display, Look look)
        {
            var key = (display, look);
            if (TextMaterials.TryGetValue(key, out var cached) && cached != null)
                return cached;

            var theme = Theme;
            var source = display ? theme.DisplayMaterial : theme.BodyMaterial;
            if (source == null)
                source = (display ? theme.DisplayFont : theme.BodyFont).material;
            var material = new Material(source) { name = $"{source.name} {look}" };
            material.SetFloat(OutlineWidthId, look == Look.Ink ? 0f : look == Look.Title ? 0.26f : 0.22f);
            material.SetFloat(FaceDilateId, look == Look.Ink ? 0.05f : 0.1f);
            material.SetColor(UnderlayColorId, look == Look.Title ? Ink : Color.clear);
            TextMaterials[key] = material;
            return material;
        }

        private static Mesh QuadMesh
        {
            get
            {
                if (_quadMesh != null)
                    return _quadMesh;
                var primitive = GameObject.CreatePrimitive(PrimitiveType.Quad);
                _quadMesh = primitive.GetComponent<MeshFilter>().sharedMesh;
                Object.Destroy(primitive);
                return _quadMesh;
            }
        }
    }
}
