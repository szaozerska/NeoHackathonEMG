using System.IO;
using SpellGame.Game;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace SpellGame.Editor
{
    /// <summary>
    /// Regenerates the boilerplate scene: OVRCameraRig + Movement SDK body tracking + GameClient.
    /// Headless: <c>Unity -batchmode -quit -projectPath . -executeMethod SpellGame.Editor.MainSceneBuilder.Build</c>
    /// </summary>
    public static class MainSceneBuilder
    {
        private const string ScenePath = "Assets/SpellGame/Scenes/Main.unity";
        private const string PrefabFolder = "Assets/SpellGame/Prefabs";
        private const string MaterialFolder = "Assets/SpellGame/Materials";
        private const string CameraRigPrefabPath = "Packages/com.meta.xr.sdk.core/Prefabs/OVRCameraRig.prefab";
        private const string LitShaderName = "Universal Render Pipeline/Lit";

        [MenuItem("SpellGame/Rebuild Main Scene")]
        public static void Build()
        {
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

            CreateLight();
            CreateFloor();
            var rig = CreateCameraRig();
            var trackingSpace = rig.transform.Find("TrackingSpace");
            var bodySkeleton = CreateBodyTracking(trackingSpace);
            var statusLabel = CreateStatusLabel(trackingSpace.Find("CenterEyeAnchor"));
            var remotePlayers = CreateRemotePlayersView();
            CreateGameClient(bodySkeleton, remotePlayers, statusLabel);

            EditorSceneManager.SaveScene(scene, ScenePath);
            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ScenePath, true) };
            Debug.Log($"[SpellGame] Built {ScenePath}.");
        }

        private static void CreateLight()
        {
            var light = new GameObject("Directional Light").AddComponent<Light>();
            light.type = LightType.Directional;
            light.shadows = LightShadows.Soft;
            light.transform.rotation = Quaternion.Euler(50f, -30f, 0f);
        }

        private static void CreateFloor()
        {
            var floor = GameObject.CreatePrimitive(PrimitiveType.Plane);
            floor.name = "Floor";
            floor.transform.localScale = new Vector3(2f, 1f, 2f);
            floor.GetComponent<MeshRenderer>().sharedMaterial = LitMaterial("Floor", new Color(0.35f, 0.35f, 0.4f));
        }

        private static OVRCameraRig CreateCameraRig()
        {
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(CameraRigPrefabPath);
            var rig = (GameObject)PrefabUtility.InstantiatePrefab(prefab);

            var manager = new SerializedObject(rig.GetComponent<OVRManager>());
            manager.FindProperty("_trackingOriginType").intValue = (int)OVRManager.TrackingOrigin.FloorLevel;
            manager.FindProperty("requestBodyTrackingPermissionOnStartup").boolValue = true;
            manager.ApplyModifiedPropertiesWithoutUndo();

            return rig.GetComponent<OVRCameraRig>();
        }

        /// <summary>Local player body (architecture.md §2.1): rendered locally, sampled for the pose stream.</summary>
        private static OVRSkeleton CreateBodyTracking(Transform trackingSpace)
        {
            var body = new GameObject("Body Tracking");
            body.transform.SetParent(trackingSpace, false);
            body.AddComponent<OVRBody>().ProvidedSkeletonType = OVRPlugin.BodyJointSet.UpperBody;

            var skeleton = body.AddComponent<OVRSkeleton>();
            var serializedSkeleton = new SerializedObject(skeleton);
            serializedSkeleton.FindProperty("_skeletonType").intValue = (int)OVRSkeleton.SkeletonType.Body;
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

        private static RemotePlayersView CreateRemotePlayersView()
        {
            var view = new GameObject("Remote Players").AddComponent<RemotePlayersView>();
            var serializedView = new SerializedObject(view);
            serializedView.FindProperty("jointMarkerPrefab").objectReferenceValue = JointMarkerPrefab();
            serializedView.ApplyModifiedPropertiesWithoutUndo();
            return view;
        }

        private static void CreateGameClient(OVRSkeleton bodySkeleton, RemotePlayersView remotePlayers, TextMesh statusLabel)
        {
            var client = new GameObject("Game Client").AddComponent<GameClient>();
            var serializedClient = new SerializedObject(client);
            serializedClient.FindProperty("bodySkeleton").objectReferenceValue = bodySkeleton;
            serializedClient.FindProperty("remotePlayers").objectReferenceValue = remotePlayers;
            serializedClient.FindProperty("statusLabel").objectReferenceValue = statusLabel;
            serializedClient.ApplyModifiedPropertiesWithoutUndo();
        }

        private static GameObject JointMarkerPrefab()
        {
            var path = $"{PrefabFolder}/JointMarker.prefab";
            var existing = AssetDatabase.LoadAssetAtPath<GameObject>(path);
            if (existing != null)
                return existing;

            Directory.CreateDirectory(PrefabFolder);
            var marker = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            Object.DestroyImmediate(marker.GetComponent<Collider>());
            marker.transform.localScale = Vector3.one * 0.08f;
            marker.GetComponent<MeshRenderer>().sharedMaterial = LitMaterial("RemoteJoint", new Color(0.9f, 0.4f, 0.2f));
            var prefab = PrefabUtility.SaveAsPrefabAsset(marker, path);
            Object.DestroyImmediate(marker);
            return prefab;
        }

        private static Material LitMaterial(string name, Color color)
        {
            var path = $"{MaterialFolder}/{name}.mat";
            var existing = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (existing != null)
                return existing;

            Directory.CreateDirectory(MaterialFolder);
            var material = new Material(Shader.Find(LitShaderName)) { color = color };
            AssetDatabase.CreateAsset(material, path);
            return material;
        }
    }
}
