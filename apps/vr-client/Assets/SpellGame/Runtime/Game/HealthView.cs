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
    /// <item>taking damage: bars flash at the edges of the view, stronger for big hits and low HP, on the side the hit came
    /// from (top and bottom too for hits from behind) and coloured by what hit you: fireball orange, sword cyan; a softer
    /// blue flash when your shield blocks something.</item>
    /// </list>
    /// </summary>
    public sealed class HealthView : MonoBehaviour
    {
        [SerializeField] private GameClient gameClient;
        [SerializeField] private Transform centerEye;
        [Tooltip("Unlit material the bar materials are copied from (only its colour is changed).")]
        [SerializeField] private Material baseMaterial;

        [Tooltip("Fallback starting HP for servers that don't send max_hp.")]
        [SerializeField] private float maxHp = 150f;

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
        [SerializeField] private Color fireballFlash = new(1f, 0.42f, 0.05f);
        [SerializeField] private Color swordFlash = new(0.25f, 0.85f, 1f);
        [SerializeField] private Color blockFlash = new(0.3f, 0.45f, 1f);
        [SerializeField, Range(0f, 1f)] private float blockFlashStrength = 0.35f;

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
        private readonly float[] _flashWeights = { 1f, 1f, 1f, 1f };

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
            gameClient.ImpactReceived += OnImpact;
        }

        private void OnDisable()
        {
            gameClient.StateReceived -= OnState;
            gameClient.DamageReceived -= OnDamage;
            gameClient.ImpactReceived -= OnImpact;
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
            var lowHp = 1f - Mathf.Clamp01(damage.HpAfter / MaxHpOf(damage.TargetId));
            var color = damage.Kind == SpellKind.Sword ? swordFlash : damage.Kind == SpellKind.Fireball ? fireballFlash : Color.red;
            Flash(Mathf.Clamp01(0.4f + damage.Amount / 20f + 0.5f * lowHp), color, AttackerPosition(damage.SourceId, damage.Pos));
        }

        private void OnImpact(ImpactMessage impact)
        {
            if (impact.TargetId != gameClient.PlayerId || impact.Reason is not ("blocked" or "parried"))
                return;
            Flash(blockFlashStrength, blockFlash, AttackerPosition(impact.OwnerId, impact.Pos));
        }

        /// <summary>Where the hit came from: the attacker's head, else the hit point.</summary>
        private Vector3? AttackerPosition(string attackerId, float[] hitPos)
        {
            if (attackerId != null && gameClient.TryGetJoints(attackerId, out var joints) && joints.Head != null)
                return joints.Head.Position;
            return hitPos is { Length: 3 } ? new Vector3(hitPos[0], hitPos[1], hitPos[2]) : null;
        }

        /// <summary>Edges: 0 top, 1 bottom, 2 left, 3 right. The side facing the attacker flashes hardest.</summary>
        private void Flash(float strength, Color color, Vector3? from)
        {
            _flashStrength = strength;
            _flashStart = Time.time;
            _flashMaterial.SetColor("_BaseColor", color);
            for (var i = 0; i < _flashWeights.Length; i++)
                _flashWeights[i] = 1f;
            if (from == null || centerEye == null)
                return;

            var local = centerEye.InverseTransformPoint(from.Value);
            local.y = 0f;
            if (local.sqrMagnitude < 1e-4f)
                return;
            local.Normalize();
            var side = Mathf.Clamp01(Mathf.Abs(local.x) * 1.5f);
            var behind = Mathf.Clamp01(-local.z);
            var near = 0.6f + 0.4f * side;
            var far = Mathf.Max(0.6f * (1f - side), behind);
            _flashWeights[2] = local.x < 0f ? near : far;
            _flashWeights[3] = local.x < 0f ? far : near;
            _flashWeights[0] = _flashWeights[1] = 0.3f + 0.7f * behind;
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
                PlaceBar(_wristBar, wrist.Position + Vector3.up * wristBarLift, viewer, _players[ownId]);
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
                    PlaceBar(bar, joints.Head.Position + Vector3.up * headBarHeight, viewer, player);
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
            var edgeThickness = active ? flashMaxThickness * _flashStrength * (1f - t) : 0f;
            for (var i = 0; i < _flashEdges.Length; i++)
            {
                var edge = _flashEdges[i];
                edge.gameObject.SetActive(active && _flashWeights[i] > 0.01f);
                if (!active)
                    continue;
                var thickness = edgeThickness * _flashWeights[i];
                var horizontal = i < 2;
                edge.localScale = horizontal ? new Vector3(1.2f, thickness, 1f) : new Vector3(thickness, 1.2f, 1f);
            }
        }

        private float MaxHpOf(string playerId) =>
            playerId != null && _players.TryGetValue(playerId, out var player) && player.MaxHp > 0f ? player.MaxHp : maxHp;

        private void PlaceBar(Bar bar, Vector3 position, Vector3 viewer, PlayerSnapshot player)
        {
            var away = position - viewer;
            bar.Root.SetPositionAndRotation(position, away.sqrMagnitude > 1e-6f ? Quaternion.LookRotation(away) : Quaternion.identity);

            var fraction = Mathf.Clamp01(player.Hp / MaxHpOf(player.PlayerId));
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
