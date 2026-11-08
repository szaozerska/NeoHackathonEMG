using System.IO;
using SpellGame.Game;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace SpellGame.Editor
{
    /// <summary>
    /// Regenerates the scene: passthrough OVRCameraRig + Movement SDK body tracking + debug skeletons + GameClient + shared-space aligner + spell views.
    /// Headless: <c>Unity -batchmode -quit -projectPath . -executeMethod SpellGame.Editor.MainSceneBuilder.Build</c>
    /// </summary>
    public static class MainSceneBuilder
    {
        private const string ScenePath = "Assets/SpellGame/Scenes/Main.unity";
        private const string MaterialFolder = "Assets/SpellGame/Materials";
        private const string ShieldFolder = "Assets/SpellGame/Shield";
        private const string CameraRigPrefabPath = "Packages/com.meta.xr.sdk.core/Prefabs/OVRCameraRig.prefab";
        private const string UnlitShaderName = "Universal Render Pipeline/Unlit";

        [MenuItem("SpellGame/Rebuild Main Scene")]
        public static void Build()
        {
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

            var rig = CreateCameraRig();
            var trackingSpace = rig.transform.Find("TrackingSpace");
            var bodySkeleton = CreateBodyTracking(trackingSpace);
            var statusLabel = CreateStatusLabel(trackingSpace.Find("CenterEyeAnchor"));
            var debugSkeletons = CreateDebugSkeletonsView();
            var client = CreateGameClient(bodySkeleton, debugSkeletons, statusLabel);
            CreateControllerBand(client);
            CreatePairingButton(client);
            CreateSharedSpaceAligner(client, rig);
            CreateFireballView(client);
            CreateSwordView(client);
            CreateShieldView(client);

            EditorSceneManager.SaveScene(scene, ScenePath);
            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ScenePath, true) };
            Debug.Log($"[SpellGame] Built {ScenePath}.");
        }

        private static OVRCameraRig CreateCameraRig()
        {
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(CameraRigPrefabPath);
            var rig = (GameObject)PrefabUtility.InstantiatePrefab(prefab);

            var manager = new SerializedObject(rig.GetComponent<OVRManager>());
            manager.FindProperty("_trackingOriginType").intValue = (int)OVRManager.TrackingOrigin.FloorLevel;
            manager.FindProperty("requestBodyTrackingPermissionOnStartup").boolValue = true;
            manager.FindProperty("isInsightPassthroughEnabled").boolValue = true;
            manager.ApplyModifiedPropertiesWithoutUndo();

            rig.AddComponent<OVRPassthroughLayer>();
            ClearToTransparent(rig.transform.Find("TrackingSpace/CenterEyeAnchor").GetComponent<Camera>());
            return rig.GetComponent<OVRCameraRig>();
        }

        /// <summary>The passthrough layer is an underlay, so the camera must leave alpha at zero wherever nothing is drawn.</summary>
        private static void ClearToTransparent(Camera camera)
        {
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = Color.clear;
        }

        /// <summary>Local player body (architecture.md §2.1), sampled for the pose stream and the debug skeleton.</summary>
        private static OVRSkeleton CreateBodyTracking(Transform trackingSpace)
        {
            var body = new GameObject("Body Tracking");
            body.transform.SetParent(trackingSpace, false);
            body.AddComponent<OVRBody>().ProvidedSkeletonType = OVRPlugin.BodyJointSet.FullBody;

            var skeleton = body.AddComponent<OVRSkeleton>();
            var serializedSkeleton = new SerializedObject(skeleton);
            serializedSkeleton.FindProperty("_skeletonType").intValue = (int)OVRSkeleton.SkeletonType.FullBody;
            serializedSkeleton.ApplyModifiedPropertiesWithoutUndo();
            return skeleton;
        }

        private static TextMesh CreateStatusLabel(Transform centerEye)
        {
            var label = new GameObject("Status Label").AddComponent<TextMesh>();
            label.transform.SetParent(centerEye, false);
            label.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            label.GetComponent<MeshRenderer>().sharedMaterial = label.font.material;
            label.transform.localPosition = new Vector3(0f, -0.25f, 1f);
            label.anchor = TextAnchor.MiddleCenter;
            label.alignment = TextAlignment.Center;
            label.characterSize = 0.01f;
            label.fontSize = 48;
            label.text = "SpellGame";
            return label;
        }

        private static DebugSkeletonsView CreateDebugSkeletonsView()
        {
            var view = new GameObject("Debug Skeletons").AddComponent<DebugSkeletonsView>();
            var serializedView = new SerializedObject(view);
            serializedView.FindProperty("boneMaterial").objectReferenceValue = UnlitMaterial("DebugSkeleton", new Color(0.2f, 1f, 0.4f));
            serializedView.FindProperty("bodyMaterial").objectReferenceValue = UnlitMaterial("RemoteBody", new Color(1f, 0.35f, 0.75f));
            serializedView.ApplyModifiedPropertiesWithoutUndo();
            return view;
        }

        private static GameClient CreateGameClient(OVRSkeleton bodySkeleton, DebugSkeletonsView debugSkeletons, TextMesh statusLabel)
        {
            var client = new GameObject("Game Client").AddComponent<GameClient>();
            var serializedClient = new SerializedObject(client);
            serializedClient.FindProperty("bodySkeleton").objectReferenceValue = bodySkeleton;
            serializedClient.FindProperty("debugSkeletons").objectReferenceValue = debugSkeletons;
            serializedClient.FindProperty("statusLabel").objectReferenceValue = statusLabel;
            serializedClient.ApplyModifiedPropertiesWithoutUndo();
            return client;
        }

        private static void CreateControllerBand(GameClient client)
        {
            var band = client.gameObject.AddComponent<ControllerBand>();
            var serializedBand = new SerializedObject(band);
            serializedBand.FindProperty("gameClient").objectReferenceValue = client;
            serializedBand.ApplyModifiedPropertiesWithoutUndo();
        }

        private static void CreatePairingButton(GameClient client)
        {
            var button = client.gameObject.AddComponent<PairingButton>();
            var serializedButton = new SerializedObject(button);
            serializedButton.FindProperty("gameClient").objectReferenceValue = client;
            serializedButton.ApplyModifiedPropertiesWithoutUndo();
        }

        private static void CreateSharedSpaceAligner(GameClient client, OVRCameraRig rig)
        {
            var aligner = client.gameObject.AddComponent<SharedSpaceAligner>();
            var serializedAligner = new SerializedObject(aligner);
            serializedAligner.FindProperty("gameClient").objectReferenceValue = client;
            serializedAligner.FindProperty("cameraRig").objectReferenceValue = rig;
            serializedAligner.ApplyModifiedPropertiesWithoutUndo();
        }

        private static void CreateFireballView(GameClient client)
        {
            var view = new GameObject("Fireball View").AddComponent<FireballView>();
            var serializedView = new SerializedObject(view);
            serializedView.FindProperty("gameClient").objectReferenceValue = client;
            serializedView.FindProperty("fireMaterial").objectReferenceValue = UnlitMaterial("Fire", new Color(1f, 0.38f, 0.05f));
            serializedView.FindProperty("sparkMaterial").objectReferenceValue = UnlitMaterial("Spark", new Color(1f, 0.85f, 0.3f));
            serializedView.FindProperty("smokeMaterial").objectReferenceValue = UnlitMaterial("Smoke", new Color(0.45f, 0.45f, 0.45f));
            serializedView.ApplyModifiedPropertiesWithoutUndo();
        }

        private static void CreateSwordView(GameClient client)
        {
            var view = new GameObject("Sword View").AddComponent<SwordView>();
            var serializedView = new SerializedObject(view);
            serializedView.FindProperty("gameClient").objectReferenceValue = client;
            serializedView.FindProperty("bladeMaterial").objectReferenceValue = UnlitMaterial("Blade", new Color(0.55f, 0.9f, 1f));
            serializedView.FindProperty("trailMaterial").objectReferenceValue = UnlitMaterial("BladeTrail", new Color(0.2f, 0.6f, 1f));
            serializedView.FindProperty("sparkMaterial").objectReferenceValue = UnlitMaterial("Spark", new Color(1f, 0.85f, 0.3f));
            serializedView.ApplyModifiedPropertiesWithoutUndo();
        }

        private static void CreateShieldView(GameClient client)
        {
            var view = new GameObject("Shield View").AddComponent<ShieldView>();
            var serializedView = new SerializedObject(view);
            serializedView.FindProperty("gameClient").objectReferenceValue = client;
            serializedView.FindProperty("shieldMaterial").objectReferenceValue = ShieldMaterial("ShieldForceField", "SpellGame/Shield/ForceField", null);
            serializedView.FindProperty("sparkMaterial").objectReferenceValue = ShieldMaterial("ShieldSpark", "SpellGame/Shield/Spark", m => m.SetFloat("_Ring", 0f));
            serializedView.FindProperty("ringMaterial").objectReferenceValue = ShieldMaterial("ShieldRing", "SpellGame/Shield/Spark", m => m.SetFloat("_Ring", 1f));
            serializedView.ApplyModifiedPropertiesWithoutUndo();
        }

        /// <summary>A material on one of the Assets/SpellGame/Shield shaders, created next to them on first build.</summary>
        private static Material ShieldMaterial(string name, string shaderName, System.Action<Material> configure)
        {
            var shader = Shader.Find(shaderName);
            if (shader == null)
                throw new System.InvalidOperationException($"[SpellGame] Shader '{shaderName}' not found; is Assets/SpellGame/Shield/Shaders imported?");

            var path = $"{ShieldFolder}/{name}.mat";
            var material = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (material == null)
            {
                Directory.CreateDirectory(ShieldFolder);
                material = new Material(shader);
                configure?.Invoke(material);
                AssetDatabase.CreateAsset(material, path);
            }
            else if (material.shader != shader)
            {
                material.shader = shader;
                configure?.Invoke(material);
                EditorUtility.SetDirty(material);
            }
            return material;
        }

        private static Material UnlitMaterial(string name, Color color)
        {
            var path = $"{MaterialFolder}/{name}.mat";
            var existing = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (existing != null)
                return existing;

            Directory.CreateDirectory(MaterialFolder);
            var material = new Material(Shader.Find(UnlitShaderName)) { color = color };
            AssetDatabase.CreateAsset(material, path);
            return material;
        }
    }
}
