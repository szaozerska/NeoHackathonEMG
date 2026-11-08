using System.IO;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;

namespace SpellGame.Editor
{
    /// <summary>
    /// APK builds for the Quest. Headless, configure + rebuild scene + build in one go:
    /// <c>Unity -batchmode -quit -projectPath . -buildTarget Android -executeMethod SpellGame.Editor.QuestBuild.BuildBatch</c>
    /// </summary>
    public static class QuestBuild
    {
        private const string ScenePath = "Assets/SpellGame/Scenes/Main.unity";
        private const string ApkPath = "Builds/SpellGame.apk";

        [MenuItem("SpellGame/Build APK")]
        public static void BuildApk() => Build(BuildOptions.None);

        [MenuItem("SpellGame/Build And Run On Headset")]
        public static void BuildAndRun() => Build(BuildOptions.AutoRunPlayer);

        public static void BuildBatch()
        {
            QuestProjectConfigurator.Configure();
            MainSceneBuilder.Build();
            Build(BuildOptions.None);
        }

        private static void Build(BuildOptions options)
        {
            if (EditorUserBuildSettings.activeBuildTarget != BuildTarget.Android)
                EditorUserBuildSettings.SwitchActiveBuildTarget(BuildTargetGroup.Android, BuildTarget.Android);

            Directory.CreateDirectory(Path.GetDirectoryName(ApkPath));
            var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
            {
                scenes = new[] { ScenePath },
                locationPathName = ApkPath,
                target = BuildTarget.Android,
                targetGroup = BuildTargetGroup.Android,
                options = options,
            });
            var summary = report.summary;
            Debug.Log($"[SpellGame] Build {summary.result}: {Path.GetFullPath(ApkPath)} ({summary.totalSize / (1024 * 1024)} MB, {summary.totalErrors} errors)");
            if (Application.isBatchMode && summary.result != BuildResult.Succeeded)
                EditorApplication.Exit(1);
        }
    }
}
