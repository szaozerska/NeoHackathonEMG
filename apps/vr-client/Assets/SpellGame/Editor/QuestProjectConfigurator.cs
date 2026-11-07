using System;
using System.IO;
using System.Linq;
using System.Xml;
using Meta.XR;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.XR.Management;
using UnityEditor.XR.Management.Metadata;
using UnityEditor.XR.OpenXR.Features;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using UnityEngine.XR.Management;
using UnityEngine.XR.OpenXR;
using UnityEngine.XR.OpenXR.Features;
using UnityEngine.XR.OpenXR.Features.Interactions;
using UnityEngine.XR.OpenXR.Features.MetaQuestSupport;

namespace SpellGame.Editor
{
    /// <summary>
    /// One-shot, idempotent Quest 3 project setup. Run from the menu, or headless:
    /// <c>Unity -batchmode -quit -projectPath . -executeMethod SpellGame.Editor.QuestProjectConfigurator.Configure</c>
    /// </summary>
    public static class QuestProjectConfigurator
    {
        private const string ApplicationId = "com.neohackathon.spellgame";
        private const string SettingsFolder = "Assets/SpellGame/Settings";
        private const string XRSettingsFolder = "Assets/XR";
        private const string AndroidManifestPath = "Assets/Plugins/Android/AndroidManifest.xml";
        private const string AndroidNamespace = "http://schemas.android.com/apk/res/android";

        private static readonly BuildTargetGroup[] XRTargets = { BuildTargetGroup.Android, BuildTargetGroup.Standalone };

        private static readonly string[] NetworkPermissions =
        {
            "android.permission.INTERNET",
            "android.permission.ACCESS_WIFI_STATE",
            "android.permission.CHANGE_WIFI_MULTICAST_STATE",
        };

        [MenuItem("SpellGame/Configure Project for Quest 3")]
        public static void Configure()
        {
            if (!BuildPipeline.IsBuildTargetSupported(BuildTargetGroup.Android, BuildTarget.Android))
                throw new InvalidOperationException("Android Build Support is not installed for this Editor. Add it in Unity Hub (Installs > Add modules), then rerun.");

            ConfigurePlayer();
            ConfigureRenderPipeline();
            foreach (var target in XRTargets)
                ConfigureOpenXR(target);
            ConfigureMetaProjectConfig();
            ConfigureAndroidManifest();
            AssetDatabase.SaveAssets();
            Debug.Log("[SpellGame] Quest 3 project configuration applied.");
        }

        private static void ConfigurePlayer()
        {
            PlayerSettings.companyName = "NeoHackathon";
            PlayerSettings.productName = "SpellGame";
            PlayerSettings.colorSpace = ColorSpace.Linear;
            PlayerSettings.SetApplicationIdentifier(NamedBuildTarget.Android, ApplicationId);
            PlayerSettings.SetScriptingBackend(NamedBuildTarget.Android, ScriptingImplementation.IL2CPP);
            PlayerSettings.Android.targetArchitectures = AndroidArchitecture.ARM64;
            PlayerSettings.Android.minSdkVersion = AndroidSdkVersions.AndroidApiLevel32;
            PlayerSettings.SetUseDefaultGraphicsAPIs(BuildTarget.Android, false);
            PlayerSettings.SetGraphicsAPIs(BuildTarget.Android, new[] { GraphicsDeviceType.Vulkan });
        }

        private static void ConfigureRenderPipeline()
        {
            var pipelinePath = $"{SettingsFolder}/QuestURP.asset";
            var pipeline = AssetDatabase.LoadAssetAtPath<UniversalRenderPipelineAsset>(pipelinePath) ?? CreateRenderPipeline(pipelinePath);
            GraphicsSettings.defaultRenderPipeline = pipeline;
            QualitySettings.ForEach(() => QualitySettings.renderPipeline = pipeline);
        }

        private static UniversalRenderPipelineAsset CreateRenderPipeline(string pipelinePath)
        {
            Directory.CreateDirectory(SettingsFolder);
            var renderer = ScriptableObject.CreateInstance<UniversalRendererData>();
            AssetDatabase.CreateAsset(renderer, $"{SettingsFolder}/QuestURP_Renderer.asset");

            var pipeline = UniversalRenderPipelineAsset.Create(renderer);
            pipeline.msaaSampleCount = 4;
            pipeline.supportsHDR = false;
            pipeline.shadowDistance = 3f;
            AssetDatabase.CreateAsset(pipeline, pipelinePath);
            return pipeline;
        }

        private static void ConfigureOpenXR(BuildTargetGroup target)
        {
            var manager = XRManagerFor(target);
            XRPackageMetadataStore.AssignLoader(manager, typeof(OpenXRLoader).FullName, target);

            FeatureHelpers.RefreshFeatures(target);
            var openXR = OpenXRSettings.GetSettingsForBuildTargetGroup(target);
            EnableFeature<MetaXRFeature>(openXR);
            EnableFeature<OculusTouchControllerProfile>(openXR);
            EnableFeature<MetaQuestTouchPlusControllerProfile>(openXR);
            if (target == BuildTargetGroup.Android)
                EnableFeature<MetaQuestFeature>(openXR);
            EditorUtility.SetDirty(openXR);
        }

        private static XRManagerSettings XRManagerFor(BuildTargetGroup target)
        {
            var perTarget = XRSettingsPerBuildTarget();
            if (!perTarget.HasSettingsForBuildTarget(target))
                perTarget.CreateDefaultSettingsForBuildTarget(target);
            if (!perTarget.HasManagerSettingsForBuildTarget(target))
                perTarget.CreateDefaultManagerSettingsForBuildTarget(target);
            EditorUtility.SetDirty(perTarget);
            return perTarget.ManagerSettingsForBuildTarget(target);
        }

        private static XRGeneralSettingsPerBuildTarget XRSettingsPerBuildTarget()
        {
            EditorBuildSettings.TryGetConfigObject(XRGeneralSettings.settingsKey, out XRGeneralSettingsPerBuildTarget existing);
            if (existing != null)
                return existing;

            Directory.CreateDirectory(XRSettingsFolder);
            var created = ScriptableObject.CreateInstance<XRGeneralSettingsPerBuildTarget>();
            AssetDatabase.CreateAsset(created, $"{XRSettingsFolder}/XRGeneralSettingsPerBuildTarget.asset");
            EditorBuildSettings.AddConfigObject(XRGeneralSettings.settingsKey, created, true);
            return created;
        }

        private static void EnableFeature<TFeature>(OpenXRSettings settings) where TFeature : OpenXRFeature
        {
            settings.GetFeature<TFeature>().enabled = true;
        }

        private static void ConfigureMetaProjectConfig()
        {
            var config = OVRProjectConfig.CachedProjectConfig;
            config.targetDeviceTypes = new() { OVRProjectConfig.DeviceType.Quest3, OVRProjectConfig.DeviceType.Quest3S };
            config.bodyTrackingSupport = OVRProjectConfig.FeatureSupport.Required;
            config.handTrackingSupport = OVRProjectConfig.HandTrackingSupport.ControllersAndHands;
            OVRProjectConfig.CommitProjectConfig(config);

            var runtime = OVRRuntimeSettings.GetRuntimeSettings();
            runtime.BodyTrackingJointSet = OVRPlugin.BodyJointSet.FullBody;
            runtime.BodyTrackingFidelity = OVRPlugin.BodyTrackingFidelity2.High;
            OVRRuntimeSettings.CommitRuntimeSettings(runtime);
        }

        /// <summary>Generates Meta's store-compatible manifest, then adds the LAN permissions discovery needs (§4.1).</summary>
        private static void ConfigureAndroidManifest()
        {
            OVRManifestPreprocessor.GenerateOrUpdateAndroidManifest(silentMode: true);

            var manifest = new XmlDocument();
            manifest.Load(AndroidManifestPath);
            var root = manifest.DocumentElement;
            var declared = root.SelectNodes("uses-permission").Cast<XmlElement>()
                .Select(element => element.GetAttribute("name", AndroidNamespace))
                .ToHashSet();

            foreach (var permission in NetworkPermissions.Where(permission => !declared.Contains(permission)))
            {
                var element = manifest.CreateElement("uses-permission");
                element.SetAttribute("name", AndroidNamespace, permission);
                root.PrependChild(element);
            }

            manifest.Save(AndroidManifestPath);
            AssetDatabase.ImportAsset(AndroidManifestPath);
        }
    }
}
