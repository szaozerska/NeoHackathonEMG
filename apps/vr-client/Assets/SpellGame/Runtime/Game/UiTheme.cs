using System;
using TMPro;
using UnityEngine;

namespace SpellGame.Game
{
    /// <summary>Every colour of a UI theme. P1 / P2 are only for player names and markers.</summary>
    [Serializable]
    public struct UiPalette
    {
        [Tooltip("Card body (alpha = opacity).")] public Color Fill;
        [Tooltip("Lighter facet plane, top right.")] public Color FacetLight;
        [Tooltip("Darker facet plane, bottom left.")] public Color FacetDark;
        [Tooltip("Card rim.")] public Color Rim;
        [Tooltip("Text outline, drop shadows, the selected-card outline.")] public Color Ink;
        public Color Text;
        public Color TextDim;
        [Tooltip("The one tint: hover and selected highlights.")] public Color Accent;
        public Color P1;
        public Color P2;
        public Color Pointer;
        public Color Ash;
        public Color[] Confetti;

        /// <summary>"L · Smoky Opal": smoke-grey translucent crystal, white rim, white text with a dark-ink outline.</summary>
        public static UiPalette SmokyOpal => new()
        {
            Fill = Rgba(70, 74, 92, 0.72f),
            FacetLight = Rgba(95, 98, 120, 0.70f),
            FacetDark = Rgba(40, 43, 58, 0.66f),
            Rim = Color.white,
            Ink = Rgba(20, 22, 31, 1f),
            Text = Color.white,
            TextDim = Rgba(218, 222, 235, 1f),
            Accent = Rgba(200, 210, 255, 1f),
            P1 = new Color(1f, 0.25f, 0.25f),
            P2 = new Color(0.25f, 0.5f, 1f),
            Pointer = Color.white,
            Ash = new Color(0.35f, 0.35f, 0.4f),
            Confetti = new[] { Color.white, Rgba(200, 210, 255, 1f), Rgba(150, 156, 185, 1f) },
        };

        /// <summary>"Midnight": plain see-through black with a faint white hairline and white text; no crystal facets.</summary>
        public static UiPalette Midnight => new()
        {
            Fill = Rgba(0, 0, 0, 0.6f),
            FacetLight = Rgba(0, 0, 0, 0.6f),
            FacetDark = Rgba(0, 0, 0, 0.6f),
            Rim = Rgba(255, 255, 255, 0.22f),
            Ink = Rgba(0, 0, 0, 1f),
            Text = Color.white,
            TextDim = Rgba(200, 200, 200, 1f),
            Accent = Color.white,
            P1 = new Color(1f, 0.25f, 0.25f),
            P2 = new Color(0.25f, 0.5f, 1f),
            Pointer = Color.white,
            Ash = new Color(0.35f, 0.35f, 0.35f),
            Confetti = new[] { Color.white, Rgba(200, 200, 200, 1f), Rgba(120, 120, 120, 1f) },
        };

        /// <summary>Warm amber glass.</summary>
        public static UiPalette EmberGlass
        {
            get
            {
                var p = SmokyOpal;
                p.Fill = Rgba(92, 52, 38, 0.72f);
                p.FacetLight = Rgba(125, 72, 50, 0.70f);
                p.FacetDark = Rgba(55, 28, 20, 0.66f);
                p.Rim = Rgba(255, 214, 170, 1f);
                p.Ink = Rgba(30, 14, 8, 1f);
                p.TextDim = Rgba(245, 222, 205, 1f);
                p.Accent = Rgba(255, 170, 90, 1f);
                p.Confetti = new[] { Color.white, Rgba(255, 170, 90, 1f), Rgba(255, 214, 170, 1f) };
                return p;
            }
        }

        /// <summary>Deep violet glass.</summary>
        public static UiPalette ArcaneViolet
        {
            get
            {
                var p = SmokyOpal;
                p.Fill = Rgba(62, 44, 98, 0.72f);
                p.FacetLight = Rgba(88, 66, 132, 0.70f);
                p.FacetDark = Rgba(34, 22, 60, 0.66f);
                p.Rim = Rgba(225, 205, 255, 1f);
                p.Ink = Rgba(18, 10, 32, 1f);
                p.TextDim = Rgba(225, 215, 245, 1f);
                p.Accent = Rgba(200, 160, 255, 1f);
                p.Confetti = new[] { Color.white, Rgba(200, 160, 255, 1f), Rgba(225, 205, 255, 1f) };
                return p;
            }
        }

        /// <summary>Icy teal glass.</summary>
        public static UiPalette Frost
        {
            get
            {
                var p = SmokyOpal;
                p.Fill = Rgba(40, 80, 100, 0.72f);
                p.FacetLight = Rgba(60, 110, 135, 0.70f);
                p.FacetDark = Rgba(20, 45, 60, 0.66f);
                p.Rim = Rgba(210, 245, 255, 1f);
                p.Ink = Rgba(8, 24, 32, 1f);
                p.TextDim = Rgba(210, 235, 245, 1f);
                p.Accent = Rgba(140, 225, 255, 1f);
                p.Confetti = new[] { Color.white, Rgba(140, 225, 255, 1f), Rgba(210, 245, 255, 1f) };
                return p;
            }
        }

        /// <summary>Menu colour choices in Settings. Only the menu look changes; P1 / P2 stay red / blue.</summary>
        public static readonly (string Name, UiPalette Palette)[] Presets =
        {
            ("Smoky Opal", SmokyOpal), ("Ember", EmberGlass), ("Arcane", ArcaneViolet), ("Frost", Frost),
        };

        private static Color Rgba(int r, int g, int b, float a) => new(r / 255f, g / 255f, b / 255f, a);
    }

    /// <summary>Card shape for the <c>SpellGame/UI/CrystalPanel</c> shader. Lengths in metres.</summary>
    [Serializable]
    public struct UiShape
    {
        [Tooltip("tan of the slant; 0 = upright 90° rectangles.")] public float Skew;
        [Tooltip("45° corner cut; 0 = square corners.")] public float CornerCut;
        public float RimWidth;
        [Tooltip("Ink outline on selected / hovered cards.")] public float OutlineWidth;
        [Tooltip("Hard drop shadow below cards; 0 = none.")] public float ShadowDrop;
        [Tooltip("Strength of the two flat facet planes (0..1).")] [Range(0f, 1f)] public float Facets;
        [Tooltip("Plain look: buttons in the card fill instead of accent glass, a thin text outline, no title shadow.")]
        public bool Minimal;

        /// <summary>Plain 90° rectangles with two facets and a rim.</summary>
        public static UiShape Rectangles => new()
        {
            Skew = 0f, CornerCut = 0f, RimWidth = 0.003f, OutlineWidth = 0.004f, ShadowDrop = 0.005f, Facets = 1f,
        };

        /// <summary>Flat 90° rectangles with a hairline rim: no facets, no drop shadow.</summary>
        public static UiShape Plain => new()
        {
            Skew = 0f, CornerCut = 0f, RimWidth = 0.0015f, OutlineWidth = 0.002f, ShadowDrop = 0f, Facets = 0f, Minimal = true,
        };
    }

    /// <summary>Menu sounds. Empty slots fall back to MatchMenu's synthesised tones.</summary>
    [Serializable]
    public struct UiSounds
    {
        [Tooltip("Pointer moves onto a button.")] public AudioClip Hover;
        [Tooltip("Button pressed.")] public AudioClip Press;
        [Tooltip("Match timer ran out.")] public AudioClip TimeUp;
    }

    /// <summary>
    /// One swappable UI theme: palette, card shape, sounds, fonts and materials. <see cref="UiStyle"/> reads the active
    /// one (<see cref="UiStyle.Theme"/>). The default (<see cref="ResourceName"/>, Smoky Opal) is generated by SpellGame →
    /// Rebuild Main Scene (<c>UiThemeBuilder</c>) into <c>Assets/SpellGame/Resources</c>; other themes sit next to it.
    /// </summary>
    [CreateAssetMenu(menuName = "SpellGame/UI Theme", fileName = "SpellGameUiTheme")]
    public sealed class UiTheme : ScriptableObject
    {
        public const string ResourceName = "SpellGameUiTheme";

        /// <summary>The plain black theme (Cinzel titles, Inter body text), the default menu style.</summary>
        public const string MidnightResourceName = "SpellGameUiThemeMidnight";

        [SerializeField] private string displayName = "Smoky Opal";
        [SerializeField] private UiPalette palette = UiPalette.SmokyOpal;
        [SerializeField] private UiShape shape = UiShape.Rectangles;
        [SerializeField] private UiSounds sounds;

        [Tooltip("Titles, buttons, big numbers (Chakra Petch Bold Italic SDF).")]
        [SerializeField] private TMP_FontAsset displayFont;
        [Tooltip("Body text and stats (Chakra Petch Bold SDF).")]
        [SerializeField] private TMP_FontAsset bodyFont;
        [Tooltip("Display font material with outline + underlay enabled (UiStyle recolours copies of it).")]
        [SerializeField] private Material displayMaterial;
        [Tooltip("Body font material with outline + underlay enabled (UiStyle recolours copies of it).")]
        [SerializeField] private Material bodyMaterial;
        [Tooltip("Material on SpellGame/UI/CrystalPanel (or a compatible shader) that card materials are copied from.")]
        [SerializeField] private Material crystal;

        public string DisplayName => displayName;
        public UiPalette Palette => palette;
        public UiShape Shape => shape;
        public UiSounds Sounds => sounds;
        public TMP_FontAsset DisplayFont => displayFont;
        public TMP_FontAsset BodyFont => bodyFont;
        public Material DisplayMaterial => displayMaterial;
        public Material BodyMaterial => bodyMaterial;
        public Material Crystal => crystal;

        /// <summary>A runtime copy of this theme (fonts, shape, sounds) with another palette.</summary>
        public UiTheme WithPalette(string name, UiPalette newPalette)
        {
            var copy = Instantiate(this);
            copy.displayName = name;
            copy.palette = newPalette;
            return copy;
        }

        /// <summary>A theme from Resources by asset name, e.g. <see cref="ResourceName"/>; null if missing.</summary>
        public static UiTheme Load(string resourceName) => Resources.Load<UiTheme>(resourceName);
    }
}
