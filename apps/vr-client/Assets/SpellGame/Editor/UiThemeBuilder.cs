using System;
using System.IO;
using SpellGame.Game;
using TMPro;
using UnityEditor;
using UnityEngine;
using UnityEngine.TextCore.LowLevel;

namespace SpellGame.Editor
{
    /// <summary>
    /// Generates the <see cref="UiTheme"/> behind <see cref="UiStyle"/>: imports TMP Essential Resources if the project
    /// doesn't have them yet, makes dynamic SDF font assets from the Chakra Petch TTFs in <see cref="FontFolder"/>, the text
    /// materials (outline + underlay) and the crystal panel material, and saves the theme into Resources. Also makes the
    /// plain black Midnight theme (<see cref="UiTheme.MidnightResourceName"/>) from the Cinzel and Inter TTFs.
    /// Called first thing by <see cref="MainSceneBuilder.Build"/>. Existing assets are reused, so tweaks to them survive.
    /// </summary>
    public static class UiThemeBuilder
    {
        private const string FontFolder = "Assets/SpellGame/Fonts";
        private const string MaterialFolder = "Assets/SpellGame/UI/Materials";
        private const string ResourcesFolder = "Assets/SpellGame/Resources";
        private const string CrystalShaderName = "SpellGame/UI/CrystalPanel";
        private const string TmpMobileSdfShader = "TextMeshPro/Mobile/Distance Field";

        /// <summary>Pre-baked into the atlas; anything else is added at runtime from the font file (dynamic atlas).</summary>
        private const string Characters =
            " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~·•…–—’×";

        /// <summary>False when TMP Essential Resources are still importing; the scene rebuild then reruns once they're in.</summary>
        public static bool EnsureTheme()
        {
            if (!EnsureTmpEssentials())
                return false;

            var display = FontAsset("ChakraPetch-BoldItalic");
            var body = FontAsset("ChakraPetch-Bold");

            var path = $"{ResourcesFolder}/{UiTheme.ResourceName}.asset";
            var theme = AssetDatabase.LoadAssetAtPath<UiTheme>(path);
            if (theme == null)
            {
                Directory.CreateDirectory(ResourcesFolder);
                theme = ScriptableObject.CreateInstance<UiTheme>();
                AssetDatabase.CreateAsset(theme, path);
            }

            var serializedTheme = new SerializedObject(theme);
            serializedTheme.FindProperty("displayFont").objectReferenceValue = display;
            serializedTheme.FindProperty("bodyFont").objectReferenceValue = body;
            serializedTheme.FindProperty("displayMaterial").objectReferenceValue = TextMaterial(display, theme.Palette.Ink);
            serializedTheme.FindProperty("bodyMaterial").objectReferenceValue = TextMaterial(body, theme.Palette.Ink);
            serializedTheme.FindProperty("crystal").objectReferenceValue = CrystalMaterial();
            serializedTheme.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(theme);
            EnsureMidnightTheme();
            AssetDatabase.SaveAssets();
            return true;
        }

        /// <summary>Palette and shape are set only when the asset is first made, so tweaks to them survive.</summary>
        private static void EnsureMidnightTheme()
        {
            var display = FontAsset("Cinzel-Bold");
            var body = FontAsset("Inter-Medium");

            var path = $"{ResourcesFolder}/{UiTheme.MidnightResourceName}.asset";
            var theme = AssetDatabase.LoadAssetAtPath<UiTheme>(path);
            var created = theme == null;
            if (created)
            {
                theme = ScriptableObject.CreateInstance<UiTheme>();
                AssetDatabase.CreateAsset(theme, path);
            }

            var serializedTheme = new SerializedObject(theme);
            if (created)
            {
                serializedTheme.FindProperty("displayName").stringValue = "Midnight";
                serializedTheme.FindProperty("palette").boxedValue = UiPalette.Midnight;
                serializedTheme.FindProperty("shape").boxedValue = UiShape.Plain;
            }
            serializedTheme.FindProperty("displayFont").objectReferenceValue = display;
            serializedTheme.FindProperty("bodyFont").objectReferenceValue = body;
            serializedTheme.FindProperty("displayMaterial").objectReferenceValue = TextMaterial(display, UiPalette.Midnight.Ink);
            serializedTheme.FindProperty("bodyMaterial").objectReferenceValue = TextMaterial(body, UiPalette.Midnight.Ink);
            serializedTheme.FindProperty("crystal").objectReferenceValue = CrystalMaterial();
            serializedTheme.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(theme);
        }

        // ---------------------------------------------------------------- TMP Essential Resources

        private static bool TmpReady() =>
            AssetDatabase.FindAssets("t:TMP_Settings").Length > 0 && Shader.Find(TmpMobileSdfShader) != null;

        private static int _retries;

        /// <summary>
        /// TextMeshPro needs its Essential Resources (TMP Settings + SDF shaders) in the project; without them creating a
        /// text component throws. Imports them silently from the com.unity.ugui package the first time. If they aren't
        /// usable straight away, the scene rebuild is retried on the next editor ticks (or a batch build fails with a hint).
        /// </summary>
        private static bool EnsureTmpEssentials()
        {
            if (TmpReady())
            {
                _retries = 0;
                return true;
            }

            if (_retries == 0)
            {
                Debug.Log("[SpellGame] Importing TMP Essential Resources (one time, into Assets/TextMesh Pro).");
                TMP_PackageResourceImporter.ImportResources(true, false, false);
                AssetDatabase.Refresh();
                if (TmpReady())
                    return true;
            }

            if (Application.isBatchMode)
                throw new InvalidOperationException("[SpellGame] TMP Essential Resources were just imported; run the build again.");
            if (_retries++ < 5)
            {
                Debug.Log("[SpellGame] Waiting for the TMP Essential Resources import, then rebuilding the scene.");
                EditorApplication.delayCall += MainSceneBuilder.Build;
            }
            else
            {
                _retries = 0;
                Debug.LogError("[SpellGame] TMP Essential Resources are missing. Use Window → TextMeshPro → Import TMP Essential Resources, then rebuild the scene.");
            }
            return false;
        }

        // ---------------------------------------------------------------- fonts and materials

        /// <summary>
        /// <c>{name} SDF.asset</c> next to <c>{name}.ttf</c>: dynamic SDF atlas (72 pt sampling, 1024², multi-atlas) with
        /// <see cref="Characters"/> pre-baked. The atlas texture and material are saved as sub-assets so they survive reloads.
        /// </summary>
        private static TMP_FontAsset FontAsset(string name)
        {
            var path = $"{FontFolder}/{name} SDF.asset";
            var existing = AssetDatabase.LoadAssetAtPath<TMP_FontAsset>(path);
            if (existing != null && existing.atlasTexture != null && existing.material != null)
                return existing;

            var fontPath = $"{FontFolder}/{name}.ttf";
            var font = AssetDatabase.LoadAssetAtPath<Font>(fontPath);
            if (font == null)
                throw new FileNotFoundException($"[SpellGame] Missing font {fontPath}.");

            var asset = TMP_FontAsset.CreateFontAsset(font, 72, 8, GlyphRenderMode.SDFAA, 1024, 1024, AtlasPopulationMode.Dynamic, true);
            if (asset == null)
                throw new InvalidOperationException($"[SpellGame] Could not create a font asset from {fontPath}.");
            if (existing != null)
                AssetDatabase.DeleteAsset(path);

            asset.name = $"{name} SDF";
            AssetDatabase.CreateAsset(asset, path);
            asset.atlasTexture.name = $"{name} SDF Atlas";
            asset.material.name = $"{name} SDF Material";
            AssetDatabase.AddObjectToAsset(asset.atlasTexture, asset);
            AssetDatabase.AddObjectToAsset(asset.material, asset);
            if (!asset.TryAddCharacters(Characters, out var missing))
                Debug.LogWarning($"[SpellGame] {name} has no glyphs for: {missing}");
            EditorUtility.SetDirty(asset);
            AssetDatabase.SaveAssets();
            return asset;
        }

        /// <summary>
        /// The font's material with OUTLINE_ON + UNDERLAY_ON (a dark outline and a soft shadow, so text reads against a
        /// bright room). As a saved asset it also keeps those shader variants in the build; UiStyle recolours copies.
        /// </summary>
        private static Material TextMaterial(TMP_FontAsset font, Color ink)
        {
            var path = $"{MaterialFolder}/{font.name} Text.mat";
            var material = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (material == null)
            {
                Directory.CreateDirectory(MaterialFolder);
                material = new Material(font.material) { name = $"{font.name} Text" };
                ApplyTextDefaults(material, ink);
                AssetDatabase.CreateAsset(material, path);
            }
            else if (material.shader != font.material.shader || material.mainTexture != font.atlasTexture)
            {
                material.shader = font.material.shader;
                material.CopyPropertiesFromMaterial(font.material);
                ApplyTextDefaults(material, ink);
            }
            material.EnableKeyword("OUTLINE_ON");
            material.EnableKeyword("UNDERLAY_ON");
            EditorUtility.SetDirty(material);
            return material;
        }

        private static void ApplyTextDefaults(Material material, Color ink)
        {
            material.SetFloat("_FaceDilate", 0.1f);
            material.SetColor("_OutlineColor", ink);
            material.SetFloat("_OutlineWidth", 0.22f);
            material.SetColor("_UnderlayColor", ink);
            material.SetFloat("_UnderlayOffsetX", 0.7f);
            material.SetFloat("_UnderlayOffsetY", -0.7f);
            material.SetFloat("_UnderlayDilate", 0.25f);
            material.SetFloat("_UnderlaySoftness", 0f);
        }

        private static Material CrystalMaterial()
        {
            var shader = Shader.Find(CrystalShaderName);
            if (shader == null)
                throw new InvalidOperationException($"[SpellGame] Shader '{CrystalShaderName}' not found; is Assets/SpellGame/UI/Shaders imported?");

            var path = $"{MaterialFolder}/Crystal.mat";
            var material = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (material == null)
            {
                Directory.CreateDirectory(MaterialFolder);
                material = new Material(shader) { name = "Crystal" };
                AssetDatabase.CreateAsset(material, path);
            }
            else if (material.shader != shader)
            {
                material.shader = shader;
                EditorUtility.SetDirty(material);
            }
            return material;
        }
    }
}
