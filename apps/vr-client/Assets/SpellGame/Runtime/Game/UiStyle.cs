using System;
using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.Rendering;
using Object = UnityEngine.Object;

namespace SpellGame.Game
{
    /// <summary>
    /// Shared look of every in-room screen, read from the active <see cref="UiTheme"/> (<see cref="Theme"/>): crystal
    /// cards (two flat facets, a rim, optional slant / corner cut), crisp TextMeshPro text in white with a dark-ink
    /// outline, and P1 red / P2 blue only for player names and markers. Set <see cref="Theme"/> to switch themes;
    /// <see cref="ThemeChanged"/> fires so menus and banners rebuild.
    /// </summary>
    public static class UiStyle
    {
        // ---------------------------------------------------------------- active theme

        /// <summary>Fired after <see cref="Theme"/> changes.</summary>
        public static event Action ThemeChanged;

        /// <summary>The active theme; defaults to <see cref="UiTheme.ResourceName"/> from Resources.</summary>
        public static UiTheme Theme
        {
            get
            {
                if (_theme != null)
                    return _theme;
                _theme = UiTheme.Load(UiTheme.ResourceName);
                if (_theme == null && !_warned)
                {
                    _warned = true;
                    Debug.LogError($"[SpellGame] UI theme '{UiTheme.ResourceName}' not found in Resources; run SpellGame → Rebuild Main Scene.");
                }
                return _theme;
            }
            set
            {
                if (value == _theme)
                    return;
                _theme = value;
                // Labels still using the old materials keep them until restyled (Restyle) or rebuilt.
                TextMaterials.Clear();
                ThemeChanged?.Invoke();
            }
        }

        private static readonly UiPalette FallbackPalette = UiPalette.SmokyOpal;

        public static UiPalette Palette => Theme != null ? Theme.Palette : FallbackPalette;
        public static UiShape Shape => Theme != null ? Theme.Shape : UiShape.Rectangles;
        public static UiSounds Sounds => Theme != null ? Theme.Sounds : default;

        // ---------------------------------------------------------------- palette (from the theme)

        public static Color Accent => Palette.Accent;
        public static Color Fill => Palette.Fill;
        public static Color Rim => Palette.Rim;
        public static Color Ink => Palette.Ink;
        public static Color Text => Palette.Text;
        public static Color TextDim => Palette.TextDim;
        public static Color P1 => Palette.P1;
        public static Color P2 => Palette.P2;
        public static Color Pointer => Palette.Pointer;
        public static Color Ash => Palette.Ash;
        public static Color[] Confetti => Palette.Confetti is { Length: > 0 } c ? c : FallbackPalette.Confetti;

        /// <summary>P1 red, P2 blue, anyone else in the text colour.</summary>
        public static Color PlayerColor(string playerId) => playerId switch
        {
            "P1" => P1,
            "P2" => P2,
            _ => Text,
        };

        public static string Hex(Color color) => "#" + ColorUtility.ToHtmlStringRGB(color);

        public static Color WithAlpha(Color color, float alpha) => new(color.r, color.g, color.b, alpha);

        // ---------------------------------------------------------------- crystal cards

        /// <summary>Parameters of the <c>SpellGame/UI/CrystalPanel</c> shader. Lengths in metres.</summary>
        public struct CrystalStyle
        {
            public Color Fill;        // body, alpha = opacity
            public Color FacetLight;  // top-right facet plane
            public Color FacetDark;   // bottom-left facet plane
            public Color Rim;
            public Color Outline;     // ink outline outside the rim (alpha 0 = none)
            public Color Shadow;      // hard drop shadow (alpha 0 = none)
            public float Skew;        // tan of the slant
            public float CornerCut;
            public float RimWidth;
            public float OutlineWidth;
            public float Facets;      // facet strength
            public float ShadowDrop;
        }

        private static CrystalStyle Base(float rimScale = 1f, float facets = 1f, float shadow = 0.35f)
        {
            var palette = Palette;
            var shape = Shape;
            return new CrystalStyle
            {
                Fill = palette.Fill,
                FacetLight = palette.FacetLight,
                FacetDark = palette.FacetDark,
                Rim = palette.Rim,
                Outline = Color.clear,
                Shadow = WithAlpha(palette.Ink, shadow),
                Skew = shape.Skew,
                CornerCut = shape.CornerCut,
                RimWidth = shape.RimWidth * rimScale,
                OutlineWidth = 0f,
                Facets = shape.Facets * facets,
                ShadowDrop = shape.ShadowDrop,
            };
        }

        /// <summary>Title banners ("SPELL DUEL", "GAME!") and text panels.</summary>
        public static CrystalStyle Panel
        {
            get
            {
                var style = Base(1.3f);
                style.ShadowDrop *= 1.5f;
                return style;
            }
        }

        /// <summary>Result cards and body text.</summary>
        public static CrystalStyle Card => Base();

        /// <summary>Primary button: accent-tinted see-through glass with a bright rim.</summary>
        public static CrystalStyle Primary
        {
            get
            {
                if (Shape.Minimal)
                    return Plain(0.75f, 2f);
                var style = Glass(Accent, 0.38f);
                style.Rim = WithAlpha(Color.Lerp(Rim, Color.white, 0.4f), 0.95f);
                return style;
            }
        }

        /// <summary>Secondary button: nearly clear glass with a thin rim.</summary>
        public static CrystalStyle Secondary => Shape.Minimal ? Plain(0.5f, 1f) : Glass(Fill, 0.16f);

        /// <summary>Minimal themes: a button in the card fill at <paramref name="opacity"/> with the theme's hairline rim.</summary>
        private static CrystalStyle Plain(float opacity, float rimAlphaScale)
        {
            var style = Glass(Fill, opacity);
            style.Rim = WithAlpha(Rim, Mathf.Clamp01(Rim.a * rimAlphaScale));
            style.RimWidth = Shape.RimWidth;
            return style;
        }

        /// <summary>Flat see-through glass for buttons: no facets, outline or drop shadow.</summary>
        private static CrystalStyle Glass(Color tint, float opacity)
        {
            var style = Base(0.6f, 0f, 0f);
            style.Fill = WithAlpha(tint, opacity);
            style.FacetLight = style.FacetDark = WithAlpha(tint, 0f);
            style.Rim = WithAlpha(style.Rim, 0.7f);
            style.Outline = WithAlpha(style.Outline, 0f);
            style.Shadow = WithAlpha(style.Shadow, 0f);
            style.OutlineWidth = 0f;
            style.ShadowDrop = 0f;
            style.Facets = 0f;
            return style;
        }

        /// <summary>Small always-on badges (match timer).</summary>
        public static CrystalStyle Hud => Base(1f, 1f, 0.3f);

        /// <summary>Award tags on result cards: dark crystal, thin rim.</summary>
        public static CrystalStyle Badge
        {
            get
            {
                var style = Base(0.5f, 0f, 0f);
                style.Fill = WithAlpha(style.FacetDark, 0.9f);
                style.ShadowDrop = 0f;
                return style;
            }
        }

        /// <summary>Dwell progress bar: a solid rim-coloured line.</summary>
        public static CrystalStyle Bar
        {
            get
            {
                var style = Base(0f, 0f, 0f);
                style.Fill = WithAlpha(Rim, 0.95f);
                style.CornerCut = 0f;
                style.ShadowDrop = 0f;
                return style;
            }
        }

        /// <summary>Pointer on it: tinted toward the accent, thicker rim, ink outline.</summary>
        public static CrystalStyle Hovered(CrystalStyle style)
        {
            if (Shape.Minimal)
            {
                style.Fill = WithAlpha(Color.Lerp(style.Fill, Accent, 0.18f), Mathf.Max(style.Fill.a, 0.85f));
                style.Rim = WithAlpha(Rim, 0.9f);
                return style;
            }
            style.Fill = WithAlpha(Color.Lerp(style.Fill, Accent, 0.35f), Mathf.Min(0.6f, style.Fill.a + 0.2f));
            style.Rim = WithAlpha(Color.Lerp(style.Rim, Color.white, 0.6f), 1f);
            style.RimWidth *= 1.6f;
            return style;
        }

        /// <summary>Highlight by <paramref name="amount"/> (0..1): winner card, timer in its last seconds.</summary>
        public static CrystalStyle Pulsing(CrystalStyle style, float amount)
        {
            amount = Mathf.Clamp01(amount);
            style.Fill = Color.Lerp(style.Fill, WithAlpha(Color.Lerp(style.Fill, Accent, 0.35f), Mathf.Max(style.Fill.a, 0.8f)), amount);
            style.RimWidth *= 1f + amount;
            style.Outline = WithAlpha(Ink, Mathf.Max(style.Outline.a, amount));
            style.OutlineWidth = Mathf.Lerp(style.OutlineWidth, Shape.OutlineWidth * 1.5f, amount);
            return style;
        }

        /// <summary>A crystal quad and its own material; restyle or resize it at any time.</summary>
        public sealed class Crystal
        {
            private static readonly int FillId = Shader.PropertyToID("_FillColor");
            private static readonly int FacetLightId = Shader.PropertyToID("_FacetLightColor");
            private static readonly int FacetDarkId = Shader.PropertyToID("_FacetDarkColor");
            private static readonly int RimId = Shader.PropertyToID("_RimColor");
            private static readonly int OutlineId = Shader.PropertyToID("_OutlineColor");
            private static readonly int ShadowId = Shader.PropertyToID("_ShadowColor");
            private static readonly int RectId = Shader.PropertyToID("_Rect");
            private static readonly int FacetId = Shader.PropertyToID("_Facet");
            private static readonly int CornerCutId = Shader.PropertyToID("_CornerCut");

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

            /// <summary><paramref name="size"/> is the card at mid height; a slant adds |skew| × height to the quad.</summary>
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
                Material.SetColor(FacetLightId, style.FacetLight);
                Material.SetColor(FacetDarkId, style.FacetDark);
                Material.SetColor(RimId, style.Rim);
                Material.SetColor(OutlineId, style.Outline);
                Material.SetColor(ShadowId, style.Shadow);
                Material.SetVector(RectId, new Vector4(w, h, style.Skew, margin));
                Material.SetVector(FacetId, new Vector4(style.RimWidth, style.OutlineWidth, style.Facets, style.ShadowDrop));
                Material.SetFloat(CornerCutId, style.CornerCut);
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
        /// How a label is drawn. <see cref="Outlined"/>: thick ink outline, readable on the cards and in a bright room.
        /// <see cref="Title"/>: outline plus a hard ink drop shadow.
        /// </summary>
        public enum Look { Outlined, Title }

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
            Restyle(label, display, look);
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

        /// <summary>Gives a long-lived label the active theme's font and material (e.g. on <see cref="ThemeChanged"/>).</summary>
        public static void Restyle(TextMeshPro label, bool display, Look look = Look.Outlined)
        {
            var theme = Theme;
            var font = theme != null ? (display ? theme.DisplayFont : theme.BodyFont) : null;
            if (font == null)
                return;
            label.font = font;
            label.fontSharedMaterial = TextMaterial(display, look);
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

        private static readonly int OutlineColorId = Shader.PropertyToID("_OutlineColor");
        private static readonly int OutlineWidthId = Shader.PropertyToID("_OutlineWidth");
        private static readonly int UnderlayColorId = Shader.PropertyToID("_UnderlayColor");
        private static readonly int FaceDilateId = Shader.PropertyToID("_FaceDilate");

        private static UiTheme _theme;
        private static bool _warned;
        private static Mesh _quadMesh;
        private static readonly Dictionary<(bool Display, Look Look), Material> TextMaterials = new();

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
            material.SetColor(OutlineColorId, Ink);
            if (Shape.Minimal)
            {
                // A light outline keeps white text readable in a bright room without the heavy arcade look.
                material.SetFloat(OutlineWidthId, 0.08f);
                material.SetFloat(FaceDilateId, 0.05f);
                material.SetColor(UnderlayColorId, Color.clear);
            }
            else
            {
                material.SetFloat(OutlineWidthId, look == Look.Title ? 0.26f : display ? 0.22f : 0.2f);
                material.SetFloat(FaceDilateId, 0.1f);
                material.SetColor(UnderlayColorId, look == Look.Title ? Ink : Color.clear);
            }
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
