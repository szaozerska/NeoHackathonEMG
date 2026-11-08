using System.Collections.Generic;
using SpellGame.Protocol;
using UnityEngine;
using UnityEngine.Rendering;

namespace SpellGame.Game
{
    /// <summary>
    /// HP in the room rather than pinned to the view (head-locked HUDs are uncomfortable in MR):
    /// <list type="bullet">
    /// <item>own HP: a bar above the wrist of the hand without the band, read by glancing at it like a watch;</item>
    /// <item>other players' HP: a bar floating above their head, above the player-ID marker;</item>
    /// <item>taking damage: red bars flash at the edges of the view, stronger for big hits and low HP.</item>
    /// </list>
    /// </summary>
    public sealed class HealthView : MonoBehaviour
    {
        [SerializeField] private GameClient gameClient;
        [SerializeField] private Transform centerEye;
        [Tooltip("Unlit material the bar materials are copied from (only its colour is changed).")]
        [SerializeField] private Material baseMaterial;

        [Tooltip("Server starting HP.")]
        [SerializeField] private float maxHp = 100f;

        [Header("Wrist bar (own HP)")]
        [SerializeField] private Vector2 wristBarSize = new(0.12f, 0.016f);
        [SerializeField] private float wristBarLift = 0.05f;

        [Header("Head bars (other players)")]
        [SerializeField] private Vector2 headBarSize = new(0.4f, 0.04f);
        [Tooltip("Above the head joint; the player-ID marker sits at 0.3 m.")]
        [SerializeField] private float headBarHeight = 0.45f;

        [Header("Damage flash")]
        [SerializeField] private float flashDuration = 0.35f;
        [SerializeField] private float flashDistance = 0.5f;
        [SerializeField] private float flashMaxThickness = 0.08f;

        private sealed class Bar
        {
            public Transform Root;
            public Transform Fill;
            public Material FillMaterial;
            public Vector2 Size;
        }

        private static Mesh _quadMesh;

        private readonly Dictionary<string, PlayerSnapshot> _players = new();
        private readonly Dictionary<string, Bar> _headBars = new();
        private Bar _wristBar;
        private Material _backMaterial;
        private Material _flashMaterial;
        private Transform[] _flashEdges;
        private float _flashStart = float.NegativeInfinity;
        private float _flashStrength;

        private static Mesh QuadMesh
        {
            get
            {
                if (_quadMesh != null)
                    return _quadMesh;
                var primitive = GameObject.CreatePrimitive(PrimitiveType.Quad);
                _quadMesh = primitive.GetComponent<MeshFilter>().sharedMesh;
                Destroy(primitive);
                return _quadMesh;
            }
        }

        private void Awake()
        {
            _backMaterial = Tinted(new Color(0.08f, 0.08f, 0.08f));
            _flashMaterial = Tinted(new Color(1f, 0.05f, 0.05f));
            _wristBar = CreateBar("Wrist HP", wristBarSize);
            _flashEdges = CreateFlashEdges();
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
            _players.Clear();
            foreach (var player in state.Players)
                _players[player.PlayerId] = player;
        }

        private void OnDamage(DamageMessage damage)
        {
            if (damage.TargetId != gameClient.PlayerId)
                return;
            var lowHp = 1f - Mathf.Clamp01(damage.HpAfter / maxHp);
            _flashStrength = Mathf.Clamp01(0.4f + damage.Amount / 20f + 0.5f * lowHp);
            _flashStart = Time.time;
        }

        private void Update()
        {
            var viewer = centerEye != null ? centerEye.position : Vector3.zero;
            UpdateWristBar(viewer);
            UpdateHeadBars(viewer);
            UpdateFlash();
        }

        private void UpdateWristBar(Vector3 viewer)
        {
            JointPose wrist = null;
            var ownId = gameClient.PlayerId;
            if (ownId != null && _players.TryGetValue(ownId, out var own) && gameClient.TryGetJoints(ownId, out var joints))
                wrist = own.BandHand == HandSide.Left ? joints.RWrist : joints.LWrist;

            _wristBar.Root.gameObject.SetActive(wrist != null);
            if (wrist != null)
                PlaceBar(_wristBar, wrist.Position + Vector3.up * wristBarLift, viewer, _players[ownId].Hp);
        }

        private void UpdateHeadBars(Vector3 viewer)
        {
            foreach (var (playerId, player) in _players)
            {
                if (playerId == gameClient.PlayerId)
                    continue;
                var bar = HeadBarFor(playerId);
                var visible = gameClient.TryGetJoints(playerId, out var joints) && joints.Head != null;
                bar.Root.gameObject.SetActive(visible);
                if (visible)
                    PlaceBar(bar, joints.Head.Position + Vector3.up * headBarHeight, viewer, player.Hp);
            }

            foreach (var (playerId, bar) in _headBars)
            {
                if (!_players.ContainsKey(playerId))
                    bar.Root.gameObject.SetActive(false);
            }
        }

        private void UpdateFlash()
        {
            var t = (Time.time - _flashStart) / flashDuration;
            var active = t is >= 0f and < 1f;
            var thickness = active ? flashMaxThickness * _flashStrength * (1f - t) : 0f;
            for (var i = 0; i < _flashEdges.Length; i++)
            {
                var edge = _flashEdges[i];
                edge.gameObject.SetActive(active);
                if (!active)
                    continue;
                var horizontal = i < 2;
                edge.localScale = horizontal ? new Vector3(1.2f, thickness, 1f) : new Vector3(thickness, 1.2f, 1f);
            }
        }

        private void PlaceBar(Bar bar, Vector3 position, Vector3 viewer, float hp)
        {
            var away = position - viewer;
            bar.Root.SetPositionAndRotation(position, away.sqrMagnitude > 1e-6f ? Quaternion.LookRotation(away) : Quaternion.identity);

            var fraction = Mathf.Clamp01(hp / maxHp);
            var width = bar.Size.x * fraction;
            bar.Fill.gameObject.SetActive(fraction > 0f);
            bar.Fill.localPosition = new Vector3((width - bar.Size.x) * 0.5f, 0f, -0.002f);
            bar.Fill.localScale = new Vector3(width, bar.Size.y, 1f);
            bar.FillMaterial.SetColor("_BaseColor", HpColor(fraction));
        }

        private static Color HpColor(float fraction) =>
            fraction > 0.5f
                ? Color.Lerp(Color.yellow, Color.green, (fraction - 0.5f) * 2f)
                : Color.Lerp(Color.red, Color.yellow, fraction * 2f);

        private Bar HeadBarFor(string playerId)
        {
            if (!_headBars.TryGetValue(playerId, out var bar))
                _headBars[playerId] = bar = CreateBar($"HP {playerId}", headBarSize);
            return bar;
        }

        private Bar CreateBar(string name, Vector2 size)
        {
            var root = new GameObject(name).transform;
            root.SetParent(transform, false);
            var back = CreateQuad("Back", root, _backMaterial);
            back.localScale = new Vector3(size.x + 0.006f, size.y + 0.006f, 1f);
            var fillMaterial = Tinted(Color.green);
            var fill = CreateQuad("Fill", root, fillMaterial);
            root.gameObject.SetActive(false);
            return new Bar { Root = root, Fill = fill, FillMaterial = fillMaterial, Size = size };
        }

        /// <summary>Top, bottom, left, right edges of the view, parented to the eye.</summary>
        private Transform[] CreateFlashEdges()
        {
            var parent = centerEye != null ? centerEye : transform;
            var offsets = new[]
            {
                new Vector3(0f, 0.27f, 0f), new Vector3(0f, -0.27f, 0f),
                new Vector3(-0.33f, 0f, 0f), new Vector3(0.33f, 0f, 0f),
            };
            var edges = new Transform[offsets.Length];
            for (var i = 0; i < offsets.Length; i++)
            {
                edges[i] = CreateQuad("Damage Flash", parent, _flashMaterial);
                edges[i].localPosition = (offsets[i] + Vector3.forward) * flashDistance;
                edges[i].localRotation = Quaternion.identity;
                edges[i].gameObject.SetActive(false);
            }
            return edges;
        }

        private static Transform CreateQuad(string name, Transform parent, Material material)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            go.AddComponent<MeshFilter>().sharedMesh = QuadMesh;
            var renderer = go.AddComponent<MeshRenderer>();
            renderer.sharedMaterial = material;
            renderer.shadowCastingMode = ShadowCastingMode.Off;
            renderer.receiveShadows = false;
            return go.transform;
        }

        private Material Tinted(Color color)
        {
            var material = new Material(baseMaterial);
            material.SetColor("_BaseColor", color);
            return material;
        }
    }
}
