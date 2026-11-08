using System;
using UnityEngine;

namespace SpellGame.Game
{
    /// <summary>
    /// Player settings from the Settings screen (<see cref="MatchMenu"/>), saved in PlayerPrefs. Theme and master volume
    /// are applied here (<see cref="UiStyle.Theme"/>, <see cref="AudioListener.volume"/>); everything else is read by the
    /// views it affects: effects volume (<see cref="SpellAudio"/>, menu tones, moment sounds), announcer volume
    /// (<see cref="MatchMomentsView"/>), menu distance / height / size (<see cref="MatchMenu"/>, <see cref="EndGameView"/>),
    /// haptics (menu and moment buzzes), damage flashes (<see cref="HealthView"/>) and the K.O. slow motion.
    /// </summary>
    public static class GameSettings
    {
        /// <summary>Themes to pick from: UiTheme resource names, the first is the default.</summary>
        public static readonly string[] Themes = { UiTheme.ResourceName, WizardTheme };
        public const string WizardTheme = UiTheme.ResourceName + " Wizard";

        public const float DefaultMenuDistance = 1.1f;
        public const float MinMenuDistance = 0.6f, MaxMenuDistance = 1.8f;
        public const float MinMenuHeight = -0.3f, MaxMenuHeight = 0.3f;
        public const float MinUiScale = 0.8f, MaxUiScale = 1.4f;

        /// <summary>After any setting changes (also on <see cref="ResetToDefaults"/>).</summary>
        public static event Action Changed;

        private const string Prefix = "SpellGame.Settings.";

        public static string Theme
        {
            get => PlayerPrefs.GetString(Prefix + "Theme", Themes[0]);
            set
            {
                if (Array.IndexOf(Themes, value) < 0)
                    value = Themes[0];
                PlayerPrefs.SetString(Prefix + "Theme", value);
                ApplyTheme();
                Save();
            }
        }

        public static float MasterVolume { get => Get("MasterVolume", 1f); set { Set("MasterVolume", Mathf.Clamp01(value)); } }
        public static float EffectsVolume { get => Get("EffectsVolume", 1f); set => Set("EffectsVolume", Mathf.Clamp01(value)); }
        public static float AnnouncerVolume { get => Get("AnnouncerVolume", 1f); set => Set("AnnouncerVolume", Mathf.Clamp01(value)); }

        /// <summary>Metres from your eyes to the menu panels.</summary>
        public static float MenuDistance
        {
            get => Get("MenuDistance", DefaultMenuDistance);
            set => Set("MenuDistance", Mathf.Clamp(value, MinMenuDistance, MaxMenuDistance));
        }

        /// <summary>Metres the menus sit above (+) or below (-) their default height.</summary>
        public static float MenuHeight
        {
            get => Get("MenuHeight", 0f);
            set => Set("MenuHeight", Mathf.Clamp(value, MinMenuHeight, MaxMenuHeight));
        }

        /// <summary>Scale of the menus, banners and their text (1 = default).</summary>
        public static float UiScale
        {
            get => Get("UiScale", 1f);
            set => Set("UiScale", Mathf.Clamp(value, MinUiScale, MaxUiScale));
        }

        /// <summary>Multiplier on controller vibration (0 = off).</summary>
        public static float Haptics { get => Get("Haptics", 1f); set => Set("Haptics", Mathf.Clamp01(value)); }

        /// <summary>Multiplier on the damage flashes at the edges of your view (0 = off).</summary>
        public static float DamageFlash { get => Get("DamageFlash", 1f); set => Set("DamageFlash", Mathf.Clamp01(value)); }

        /// <summary>The slow motion and darkened passthrough when someone is knocked out.</summary>
        public static bool KoSlowMotion
        {
            get => PlayerPrefs.GetInt(Prefix + "KoSlowMotion", 1) != 0;
            set
            {
                PlayerPrefs.SetInt(Prefix + "KoSlowMotion", value ? 1 : 0);
                Save();
            }
        }

        /// <summary>Everything except the theme back to its default.</summary>
        public static void ResetToDefaults()
        {
            foreach (var key in new[] { "MasterVolume", "EffectsVolume", "AnnouncerVolume", "MenuDistance", "MenuHeight", "UiScale", "Haptics", "DamageFlash", "KoSlowMotion" })
                PlayerPrefs.DeleteKey(Prefix + key);
            Save();
        }

        /// <summary>Theme and master volume from the saved settings, before the first frame.</summary>
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
        private static void ApplyOnStartup()
        {
            AudioListener.volume = MasterVolume;
            if (Theme != Themes[0])
                ApplyTheme();
        }

        private static void ApplyTheme()
        {
            var theme = UiTheme.Load(Theme);
            if (theme == null && Theme != Themes[0])
                theme = UiTheme.Load(Themes[0]);
            if (theme != null && theme != UiStyle.Theme)
                UiStyle.Theme = theme;
        }

        private static float Get(string key, float fallback) => PlayerPrefs.GetFloat(Prefix + key, fallback);

        private static void Set(string key, float value)
        {
            PlayerPrefs.SetFloat(Prefix + key, value);
            Save();
        }

        private static void Save()
        {
            AudioListener.volume = MasterVolume;
            PlayerPrefs.Save();
            Changed?.Invoke();
        }
    }
}
