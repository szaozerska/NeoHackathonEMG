using System.IO;
using SpellGame.Game;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace SpellGame.Editor
{
    /// <summary>
    /// Regenerates the scene: passthrough OVRCameraRig + Movement SDK body tracking + debug skeletons + GameClient + shared-space aligner + spell views + match menus + AI avatar.
    /// Headless: <c>Unity -batchmode -quit -projectPath . -executeMethod SpellGame.Editor.MainSceneBuilder.Build</c>
    /// </summary>
    public static class MainSceneBuilder
    {
        private const string ScenePath = "Assets/SpellGame/Scenes/Main.unity";
        private const string MaterialFolder = "Assets/SpellGame/Materials";
        private const string SwordFolder = "Assets/SpellGame/Sword";
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
            CreateHealthView(client, trackingSpace.Find("CenterEyeAnchor"));
            CreateMatchMenu(client, rig);
            CreateAiAvatarView(client);

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
            // Players move around a shared room, so hide the Guardian boundary while passthrough is on.
            manager.FindProperty("shouldBoundaryVisibilityBeSuppressed").boolValue = true;
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

        private const string FireballFolder = "Assets/SpellGame/Fireball";

        /// <summary>Fireball view plus its materials, (re)generated from the shaders and textures in <see cref="FireballFolder"/>.</summary>
        private static void CreateFireballView(GameClient client)
        {
            var view = new GameObject("Fireball View").AddComponent<FireballView>();
            var serializedView = new SerializedObject(view);
            serializedView.FindProperty("gameClient").objectReferenceValue = client;
            serializedView.FindProperty("materials.core").objectReferenceValue = FireballMaterial("FireballCore", "FireballCore");
            serializedView.FindProperty("materials.glow").objectReferenceValue = FireballParticleMaterial("FireballGlow", "glow_soft", additive: true, coverage: 0.5f, intensity: 1f);
            serializedView.FindProperty("materials.flame").objectReferenceValue = FireballParticleMaterial("FireballFlame", "fire_01", additive: true, coverage: 0.7f, intensity: 1.3f);
            serializedView.FindProperty("materials.tongue").objectReferenceValue = FireballParticleMaterial("FireballTongue", "flame_05", additive: true, coverage: 0.7f, intensity: 1.3f);
            serializedView.FindProperty("materials.smoke").objectReferenceValue = FireballParticleMaterial("FireballSmoke", "smoke_04", additive: false, coverage: 1f, intensity: 1f);
            serializedView.FindProperty("materials.shockwave").objectReferenceValue = FireballParticleMaterial("FireballShockwave", "light_03", additive: true, coverage: 0.5f, intensity: 1f);
            serializedView.ApplyModifiedPropertiesWithoutUndo();
            AssetDatabase.SaveAssets();
        }

        /// <summary>
        /// Particle material on SpellGame/Fireball/Particle. Additive fire adds colour but still writes <paramref name="coverage"/>
        /// into alpha ("over"), so passthrough doesn't show through it; smoke is plain premultiplied alpha.
        /// </summary>
        private static Material FireballParticleMaterial(string name, string texture, bool additive, float coverage, float intensity)
        {
            var material = FireballMaterial(name, "FireballParticle");
            material.SetTexture("_MainTex", FireballTexture(texture));
            material.SetFloat("_AlphaWrite", coverage);
            material.SetFloat("_Intensity", intensity);
            material.SetFloat("_SrcBlend", (float)UnityEngine.Rendering.BlendMode.One);
            material.SetFloat("_DstBlend", (float)(additive ? UnityEngine.Rendering.BlendMode.One : UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha));
            material.SetFloat("_SrcBlendAlpha", (float)UnityEngine.Rendering.BlendMode.One);
            material.SetFloat("_DstBlendAlpha", (float)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);
            EditorUtility.SetDirty(material);
            return material;
        }

        /// <summary>Load or create <c>Fireball/Materials/{name}.mat</c> on <c>Fireball/Shaders/{shaderFile}.shader</c>.</summary>
        private static Material FireballMaterial(string name, string shaderFile)
        {
            var shaderPath = $"{FireballFolder}/Shaders/{shaderFile}.shader";
            var shader = AssetDatabase.LoadAssetAtPath<Shader>(shaderPath);
            if (shader == null)
                throw new FileNotFoundException($"[SpellGame] Missing fireball shader {shaderPath}.");

            var path = $"{FireballFolder}/Materials/{name}.mat";
            var material = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (material == null)
            {
                if (!AssetDatabase.IsValidFolder($"{FireballFolder}/Materials"))
                    AssetDatabase.CreateFolder(FireballFolder, "Materials");
                material = new Material(shader) { name = name };
                AssetDatabase.CreateAsset(material, path);
            }
            else if (material.shader != shader)
            {
                material.shader = shader;
                EditorUtility.SetDirty(material);
            }
            return material;
        }

        /// <summary>Particle masks are white RGB + alpha shape: clamp, mipmapped, 256 px is plenty on Quest.</summary>
        private static Texture2D FireballTexture(string name)
        {
            var path = $"{FireballFolder}/Textures/{name}.png";
            if (AssetImporter.GetAtPath(path) is TextureImporter importer
                && (importer.wrapMode != TextureWrapMode.Clamp
                    || !importer.mipmapEnabled
                    || importer.maxTextureSize > 256
                    || importer.alphaSource != TextureImporterAlphaSource.FromInput))
            {
                importer.textureType = TextureImporterType.Default;
                importer.alphaSource = TextureImporterAlphaSource.FromInput;
                importer.alphaIsTransparency = true;
                importer.wrapMode = TextureWrapMode.Clamp;
                importer.mipmapEnabled = true;
                importer.maxTextureSize = 256;
                importer.SaveAndReimport();
            }

            var texture = AssetDatabase.LoadAssetAtPath<Texture2D>(path);
            if (texture == null)
                throw new FileNotFoundException($"[SpellGame] Missing fireball texture {path}.");
            return texture;
        }

        private static void CreateSwordView(GameClient client)
        {
            var view = new GameObject("Sword View").AddComponent<SwordView>();
            var serializedView = new SerializedObject(view);
            serializedView.FindProperty("gameClient").objectReferenceValue = client;
            serializedView.FindProperty("bladeMaterial").objectReferenceValue = SwordMaterial("SwordBladeCore", "SpellGame/Sword/BladeCore");
            serializedView.FindProperty("glowMaterial").objectReferenceValue = SwordMaterial("SwordBladeGlow", "SpellGame/Sword/BladeGlow");
            serializedView.FindProperty("trailMaterial").objectReferenceValue = SwordMaterial("SwordTrail", "SpellGame/Sword/Trail");
            serializedView.FindProperty("sparkMaterial").objectReferenceValue = SwordMaterial("SwordSpark", "SpellGame/Sword/Spark");
            serializedView.ApplyModifiedPropertiesWithoutUndo();
        }

        /// <summary>A material on one of the sword shaders in <see cref="SwordFolder"/>, keeping any tweaks made to an existing one.</summary>
        private static Material SwordMaterial(string name, string shaderName)
        {
            var shader = Shader.Find(shaderName);
            if (shader == null)
                throw new System.InvalidOperationException($"[SpellGame] Shader '{shaderName}' not found; is {SwordFolder}/Shaders imported?");

            var folder = $"{SwordFolder}/Materials";
            var path = $"{folder}/{name}.mat";
            var material = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (material != null)
            {
                material.shader = shader;
                return material;
            }

            if (!AssetDatabase.IsValidFolder(folder))
                AssetDatabase.CreateFolder(SwordFolder, "Materials");
            material = new Material(shader);
            AssetDatabase.CreateAsset(material, path);
            return material;
        }

        private static void CreateHealthView(GameClient client, Transform centerEye)
        {
            var view = new GameObject("Health View").AddComponent<HealthView>();
            var serializedView = new SerializedObject(view);
            serializedView.FindProperty("gameClient").objectReferenceValue = client;
            serializedView.FindProperty("centerEye").objectReferenceValue = centerEye;
            serializedView.FindProperty("baseMaterial").objectReferenceValue = UnlitMaterial("DebugSkeleton", new Color(0.2f, 1f, 0.4f));
            serializedView.ApplyModifiedPropertiesWithoutUndo();
        }

        private static void CreateMatchMenu(GameClient client, OVRCameraRig rig)
        {
            var menu = new GameObject("Match Menu").AddComponent<MatchMenu>();
            var serializedMenu = new SerializedObject(menu);
            serializedMenu.FindProperty("gameClient").objectReferenceValue = client;
            serializedMenu.FindProperty("cameraRig").objectReferenceValue = rig;
            serializedMenu.FindProperty("baseMaterial").objectReferenceValue = UnlitMaterial("DebugSkeleton", new Color(0.2f, 1f, 0.4f));
            serializedMenu.ApplyModifiedPropertiesWithoutUndo();
        }

        private static void CreateAiAvatarView(GameClient client)
        {
            var view = new GameObject("AI Avatar").AddComponent<AiAvatarView>();
            var serializedView = new SerializedObject(view);
            serializedView.FindProperty("gameClient").objectReferenceValue = client;
            serializedView.FindProperty("robeMaterial").objectReferenceValue = UnlitMaterial("MageRobe", new Color(0.22f, 0.1f, 0.42f));
            serializedView.FindProperty("trimMaterial").objectReferenceValue = UnlitMaterial("MageTrim", new Color(0.95f, 0.72f, 0.25f));
            serializedView.FindProperty("shadowMaterial").objectReferenceValue = UnlitMaterial("MageShadow", new Color(0.04f, 0.02f, 0.08f));
            serializedView.FindProperty("glowMaterial").objectReferenceValue = UnlitMaterial("MageGlow", new Color(0.35f, 1f, 0.95f));
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
