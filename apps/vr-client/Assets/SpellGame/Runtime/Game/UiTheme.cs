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
        [Tooltip("Primary buttons and award badges; alpha 0 = a darker shade of Fill.")] public Color Primary;
        [Tooltip("Hovered / highlighted cards are tinted toward this; alpha 0 = Accent.")] public Color Hover;
        [Tooltip("Outline / glow of hovered and selected cards; alpha 0 = Ink.")] public Color Highlight;

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

        /// <summary>"N · Wizard": aged parchment, gold border, dark-brown ink text, arcane purple as the one accent.</summary>
        public static UiPalette Wizard => new()
        {
            Fill = Rgba(243, 226, 184, 0.96f),
            FacetLight = Rgba(252, 243, 216, 0.97f),
            FacetDark = Rgba(196, 150, 84, 0.97f),
            Rim = Rgba(216, 180, 90, 1f),
            Ink = Rgba(58, 36, 18, 1f),
            Text = Rgba(58, 36, 18, 1f),
            TextDim = Rgba(107, 74, 42, 1f),
            Accent = Rgba(93, 44, 134, 1f),
            P1 = Rgba(192, 22, 29, 1f),
            P2 = Rgba(31, 79, 201, 1f),
            Pointer = Rgba(232, 198, 106, 1f),
            Ash = new Color(0.35f, 0.32f, 0.3f),
            Confetti = new[] { Rgba(216, 180, 90, 1f), Rgba(140, 80, 190, 1f), Rgba(252, 243, 216, 1f) },
            Primary = Rgba(93, 44, 134, 0.97f),
            Hover = Rgba(255, 248, 225, 1f),
            Highlight = Rgba(150, 90, 210, 0.85f),
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
        [Tooltip("Strength of the two flat facet planes (0..1); on parchment, of the aged edges and grain.")] [Range(0f, 1f)] public float Facets;
        [Tooltip("Menus sit on one big card (title and text straight on it) instead of a card per part.")] public bool Sheet;

        /// <summary>Plain 90° rectangles with two facets and a rim.</summary>
        public static UiShape Rectangles => new()
        {
            Skew = 0f, CornerCut = 0f, RimWidth = 0.003f, OutlineWidth = 0.004f, ShadowDrop = 0.005f, Facets = 1f,
        };

        /// <summary>Parchment sheets for <c>SpellGame/UI/ParchmentPanel</c>: CornerCut is the corner radius there, OutlineWidth a soft glow.</summary>
        public static UiShape Parchment => new()
        {
            Skew = 0f, CornerCut = 0.004f, RimWidth = 0.0035f, OutlineWidth = 0.008f, ShadowDrop = 0.006f, Facets = 1f, Sheet = true,
        };
    }

    /// <summary>How text is drawn: outline colour and widths (TextMeshPro SDF units), title and primary-button label colours.</summary>
    [Serializable]
    public struct UiTextStyle
    {
        [Tooltip("Outline around all text (and the title drop shadow).")] public Color Outline;
        [Tooltip("Titles (SPELL DUEL, VICTORY!).")] public Color Title;
        [Tooltip("Labels on primary buttons and award badges.")] public Color OnPrimary;
        public float BodyOutline;
        public float DisplayOutline;
        public float TitleOutline;
        [Tooltip("Hard drop shadow under titles, in the outline colour.")] public bool TitleShadow;
        [Tooltip("Button labels in capitals.")] public bool UpperCaseLabels;
        [Tooltip("Makes the glyphs bolder (SDF face dilate).")] public float Dilate;

        /// <summary>White text with a thick dark-ink outline, readable on smoky cards and in a bright room.</summary>
        public static UiTextStyle SmokyOpal => new()
        {
            Outline = new Color(20 / 255f, 22 / 255f, 31 / 255f, 1f), Title = Color.white, OnPrimary = Color.white,
            BodyOutline = 0.2f, DisplayOutline = 0.22f, TitleOutline = 0.26f, TitleShadow = true, UpperCaseLabels = true, Dilate = 0.1f,
        };

        /// <summary>Dark-brown ink with a thin cream halo (so it still reads off the parchment), purple titles, cream on purple.</summary>
        public static UiTextStyle Wizard => new()
        {
            Outline = new Color(252 / 255f, 243 / 255f, 216 / 255f, 1f), Title = new Color(93 / 255f, 44 / 255f, 134 / 255f, 1f),
            OnPrimary = new Color(252 / 255f, 243 / 255f, 216 / 255f, 1f),
            BodyOutline = 0.12f, DisplayOutline = 0.14f, TitleOutline = 0.16f, TitleShadow = false, UpperCaseLabels = false, Dilate = 0.05f,
        };
    }

    /// <summary>Colours of the big match moments (countdown, FIGHT!, K.O.; <see cref="MatchMomentsView"/>).</summary>
    [Serializable]
    public struct UiMoments
    {
        [Tooltip("Countdown numbers, K.O., SUDDEN DEATH.")] public Color Text;
        public Color CountdownGlow;
        public Color FightText;
        public Color FightGlow;
        public Color KoGlow;
        public Color KoShadow;
        [Tooltip("Outline around the moment text; alpha 0 or width 0 = none.")] public Color Outline;
        public float OutlineWidth;
        [Tooltip("Slant the moment text (FIGHT!, K.O.).")] public bool Italic;

        /// <summary>White text with a blue / orange / red glow.</summary>
        public static UiMoments SmokyOpal => new()
        {
            Text = Color.white, CountdownGlow = new Color(0.35f, 0.65f, 1f, 0.85f), FightText = new Color(1f, 0.87f, 0.5f),
            FightGlow = new Color(1f, 0.45f, 0.1f, 0.9f), KoGlow = new Color(0.95f, 0.15f, 0.15f, 0.8f),
            KoShadow = new Color(0.4f, 0.05f, 0.06f, 1f), Outline = Color.clear, OutlineWidth = 0f, Italic = true,
        };

        /// <summary>Cream text with a purple outline and a purple glow.</summary>
        public static UiMoments Wizard => new()
        {
            Text = new Color(0.99f, 0.94f, 0.78f), CountdownGlow = new Color(0.55f, 0.3f, 0.85f, 0.85f),
            FightText = new Color(0.97f, 0.89f, 0.66f), FightGlow = new Color(0.5f, 0.22f, 0.8f, 0.9f),
            KoGlow = new Color(0.62f, 0.16f, 0.72f, 0.85f), KoShadow = new Color(0.16f, 0.06f, 0.24f, 1f),
            Outline = new Color(0.29f, 0.12f, 0.43f, 1f), OutlineWidth = 0.2f, Italic = false,
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

        [SerializeField] private string displayName = "Smoky Opal";
        [SerializeField] private UiPalette palette = UiPalette.SmokyOpal;
        [SerializeField] private UiShape shape = UiShape.Rectangles;
        [SerializeField] private UiSounds sounds;
        [SerializeField] private UiTextStyle text = UiTextStyle.SmokyOpal;
        [SerializeField] private UiMoments moments = UiMoments.SmokyOpal;

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
        [Tooltip("Display font material with GLOW_ON + UNDERLAY_ON (+ OUTLINE_ON) for the match moments.")]
        [SerializeField] private Material momentMaterial;

        public string DisplayName => displayName;
        public UiPalette Palette => palette;
        public UiShape Shape => shape;
        public UiSounds Sounds => sounds;
        public UiTextStyle Text => text;
        public UiMoments Moments => moments;
        public TMP_FontAsset DisplayFont => displayFont;
        public TMP_FontAsset BodyFont => bodyFont;
        public Material DisplayMaterial => displayMaterial;
        public Material BodyMaterial => bodyMaterial;
        public Material Crystal => crystal;
        public Material MomentMaterial => momentMaterial;

        /// <summary>Sets the look (not fonts or materials); <c>UiThemeBuilder</c> calls it once when it creates a theme asset.</summary>
        public void SetLook(string name, UiPalette newPalette, UiShape newShape, UiTextStyle newText, UiMoments newMoments, UiSounds newSounds)
        {
            displayName = name;
            palette = newPalette;
            shape = newShape;
            text = newText;
            moments = newMoments;
            sounds = newSounds;
        }

        /// <summary>A theme from Resources by asset name, e.g. <see cref="ResourceName"/>; null if missing.</summary>
        public static UiTheme Load(string resourceName) => Resources.Load<UiTheme>(resourceName);
    }
}
