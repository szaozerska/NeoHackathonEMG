using System.Linq;
using SpellGame.Protocol;
using UnityEngine;
using UnityEngine.Rendering;

namespace SpellGame.Game
{
    /// <summary>
    /// The solo-match AI opponent drawn as a robed mage instead of a debug skeleton: a flared robe to the floor,
    /// a gold hem and belt, a mantle, sleeves, a pointed hat over a hood with a dark recessed face and two glowing eyes,
    /// flickering glowing hands, and a staff with a glowing orb in the left hand.
    /// Driven by the AI's joints from the server, like any remote player; its eyes flash red when it gets hit.
    /// </summary>
    public sealed class AiAvatarView : MonoBehaviour
    {
        [SerializeField] private GameClient gameClient;
        [SerializeField] private Material robeMaterial;
        [SerializeField] private Material trimMaterial;
        [SerializeField] private Material shadowMaterial;
        [SerializeField] private Material glowMaterial;

        [SerializeField] private float hitFlashSeconds = 0.25f;

        private static readonly Color HitColor = new(1f, 0.15f, 0.1f);

        private string _aiId;
        private bool _present;
        private float _hitAt = float.NegativeInfinity;
        private Material _eyeMaterial;
        private Color _eyeColor;

        private Transform _root;
        private Transform _robe, _hem, _staff, _staffOrb, _belt, _mantle, _hood, _face, _hat, _brim, _lEye, _rEye, _lHand, _rHand, _lCuff, _rCuff;
        private Transform[] _sleeves;

        private void Awake()
        {
            _eyeMaterial = new Material(glowMaterial);
            _eyeColor = _eyeMaterial.GetColor("_BaseColor");
            Build();
            _root.gameObject.SetActive(false);
        }

        private void OnEnable()
        {
            gameClient.StateReceived += OnState;
            gameClient.DamageReceived += OnDamage;
        }

        private void OnDisable()
        {
            gameClient.StateReceived -= OnState;
            gameClient.DamageReceived -= OnDamage;
        }

        private void OnState(StateMessage state)
        {
            _aiId = state.Match?.AiId;
            _present = _aiId != null && state.Players.Any(p => p.PlayerId == _aiId);
        }

        private void OnDamage(DamageMessage damage)
        {
            if (damage.TargetId != null && damage.TargetId == _aiId)
                _hitAt = Time.time;
        }

        private void Update()
        {
            var visible = _present && gameClient.TryGetJoints(_aiId, out var joints) && joints.Head != null &&
                          joints.Chest != null && joints.Hips != null;
            _root.gameObject.SetActive(visible);
            if (!visible)
                return;
            gameClient.TryGetJoints(_aiId, out joints);
            Place(joints);

            var hit = Mathf.Clamp01(1f - (Time.time - _hitAt) / hitFlashSeconds);
            _eyeMaterial.SetColor("_BaseColor", Color.Lerp(_eyeColor, HitColor, hit));
            var eyeSize = 0.035f * (1f + 0.6f * hit);
            _lEye.localScale = _rEye.localScale = Vector3.one * eyeSize;
        }

        private void Place(BodyJoints j)
        {
            var head = j.Head.Position;
            var chest = j.Chest.Position;
            var hips = j.Hips.Position;
            var right = j.LShoulder != null && j.RShoulder != null ? j.RShoulder.Position - j.LShoulder.Position : Vector3.right;
            right.y = 0f;
            if (right.sqrMagnitude < 1e-4f)
                right = Vector3.right;
            right.Normalize();
            var forward = Vector3.Cross(right, Vector3.up);
            var yaw = Quaternion.LookRotation(forward, Vector3.up);

            var floor = new Vector3(hips.x, 0f, hips.z);
            _robe.SetPositionAndRotation(floor, yaw);
            _robe.localScale = new Vector3(0.36f, Mathf.Max(0.5f, chest.y + 0.05f), 0.3f);
            _hem.SetPositionAndRotation(floor, yaw);
            _belt.SetPositionAndRotation(new Vector3(hips.x, hips.y + 0.06f, hips.z), yaw);
            _mantle.SetPositionAndRotation(chest + Vector3.up * 0.08f, yaw);

            _hood.SetPositionAndRotation(head - forward * 0.025f + Vector3.up * 0.01f, yaw);
            _face.SetPositionAndRotation(head + forward * 0.03f - Vector3.up * 0.015f, yaw);
            _lEye.position = head + forward * 0.115f - right * 0.038f;
            _rEye.position = head + forward * 0.115f + right * 0.038f;
            var hatRotation = yaw * Quaternion.Euler(-8f, 0f, 0f);
            _brim.SetPositionAndRotation(head + Vector3.up * 0.1f, hatRotation);
            _hat.SetPositionAndRotation(head + Vector3.up * 0.1f, hatRotation);

            PlaceSleeve(0, j.LShoulder, j.LElbow);
            PlaceSleeve(1, j.LElbow, j.LWrist);
            PlaceSleeve(2, j.RShoulder, j.RElbow);
            PlaceSleeve(3, j.RElbow, j.RWrist);
            PlaceAt(_lCuff, j.LWrist);
            PlaceAt(_rCuff, j.RWrist);
            PlaceAt(_lHand, j.LHand ?? j.LWrist);
            PlaceAt(_rHand, j.RHand ?? j.RWrist);

            var staffHand = (j.LHand ?? j.LWrist)?.Position;
            _staff.gameObject.SetActive(staffHand != null);
            _staffOrb.gameObject.SetActive(staffHand != null);
            if (staffHand != null)
            {
                var grip = staffHand.Value;
                var top = grip + Vector3.up * 0.6f;
                SpellVfx.PlaceBlade(_staff, new Vector3(grip.x, 0.02f, grip.z), top, 0.035f);
                _staffOrb.position = top + Vector3.up * 0.05f;
            }
        }

        private void PlaceSleeve(int index, JointPose from, JointPose to)
        {
            var sleeve = _sleeves[index];
            sleeve.gameObject.SetActive(from != null && to != null);
            if (from != null && to != null)
                SpellVfx.PlaceBlade(sleeve, from.Position, to.Position, index % 2 == 0 ? 0.11f : 0.13f);
        }

        private static void PlaceAt(Transform part, JointPose joint)
        {
            part.gameObject.SetActive(joint != null);
            if (joint != null)
                part.position = joint.Position;
        }

        private void Build()
        {
            _root = new GameObject("AI Mage").transform;
            _root.SetParent(transform, false);

            _robe = CreateMesh("Robe", Frustum(0.5f), robeMaterial);
            _hem = Scaled(CreateMesh("Hem", Frustum(0.96f), trimMaterial), new Vector3(0.37f, 0.07f, 0.31f));
            _belt = Scaled(SpellVfx.CreateOrb("Belt", _root, trimMaterial, 1f), new Vector3(0.36f, 0.045f, 0.3f));
            _mantle = Scaled(SpellVfx.CreateOrb("Mantle", _root, robeMaterial, 1f), new Vector3(0.5f, 0.17f, 0.32f));
            _hood = Scaled(SpellVfx.CreateOrb("Hood", _root, robeMaterial, 1f), new Vector3(0.27f, 0.29f, 0.28f));
            _face = Scaled(SpellVfx.CreateOrb("Face", _root, shadowMaterial, 1f), new Vector3(0.18f, 0.2f, 0.17f));
            _lEye = SpellVfx.CreateOrb("Left Eye", _root, _eyeMaterial, 0.03f);
            _rEye = SpellVfx.CreateOrb("Right Eye", _root, _eyeMaterial, 0.03f);
            _brim = Scaled(SpellVfx.CreateOrb("Hat Brim", _root, robeMaterial, 1f), new Vector3(0.5f, 0.025f, 0.5f));
            _hat = Scaled(CreateMesh("Hat", Frustum(0f), robeMaterial), new Vector3(0.16f, 0.32f, 0.16f));
            _staff = SpellVfx.CreateBlade("Staff", _root, trimMaterial);
            _staffOrb = SpellVfx.CreateOrb("Staff Orb", _root, glowMaterial, 0.1f);
            SpellVfx.AddFlames(_staffOrb, glowMaterial, 15f);
            _sleeves = new Transform[4];
            for (var i = 0; i < _sleeves.Length; i++)
                _sleeves[i] = SpellVfx.CreateBlade("Sleeve", _root, robeMaterial);
            _lCuff = SpellVfx.CreateOrb("Left Cuff", _root, trimMaterial, 0.1f);
            _rCuff = SpellVfx.CreateOrb("Right Cuff", _root, trimMaterial, 0.1f);
            _lHand = SpellVfx.CreateOrb("Left Hand", _root, glowMaterial, 0.075f);
            _rHand = SpellVfx.CreateOrb("Right Hand", _root, glowMaterial, 0.075f);
            SpellVfx.AddFlames(_lHand, glowMaterial, 25f);
            SpellVfx.AddFlames(_rHand, glowMaterial, 25f);
        }

        private static Transform Scaled(Transform part, Vector3 scale)
        {
            part.localScale = scale;
            return part;
        }

        private Transform CreateMesh(string name, Mesh mesh, Material material)
        {
            var go = new GameObject(name);
            go.transform.SetParent(_root, false);
            go.AddComponent<MeshFilter>().sharedMesh = mesh;
            var renderer = go.AddComponent<MeshRenderer>();
            renderer.sharedMaterial = material;
            renderer.shadowCastingMode = ShadowCastingMode.Off;
            renderer.receiveShadows = false;
            return go.transform;
        }

        /// <summary>A double-sided tapered tube, 1 m tall from y = 0, radius 1 at the bottom and <paramref name="topRadius"/> at the top (0 = cone).</summary>
        private static Mesh Frustum(float topRadius, int segments = 24)
        {
            var vertices = new Vector3[segments * 2 + 1];
            for (var i = 0; i < segments; i++)
            {
                var angle = 2f * Mathf.PI * i / segments;
                var (x, z) = (Mathf.Cos(angle), Mathf.Sin(angle));
                vertices[i] = new Vector3(x, 0f, z);
                vertices[segments + i] = new Vector3(x * topRadius, 1f, z * topRadius);
            }
            vertices[^1] = Vector3.up;

            var triangles = new System.Collections.Generic.List<int>();
            void Both(int a, int b, int c)
            {
                triangles.AddRange(new[] { a, b, c, a, c, b });
            }

            for (var i = 0; i < segments; i++)
            {
                var next = (i + 1) % segments;
                Both(i, segments + i, segments + next);
                Both(i, segments + next, next);
                if (topRadius > 0f)
                    Both(segments * 2, segments + next, segments + i);
            }

            var mesh = new Mesh { name = "Frustum", vertices = vertices, triangles = triangles.ToArray() };
            mesh.RecalculateNormals();
            mesh.RecalculateBounds();
            return mesh;
        }
    }
}
