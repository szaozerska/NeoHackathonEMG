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
    /// <item>taking damage: a soft see-through glow at the rim of the view, stronger for big hits and low HP, on the side
    /// the hit came from (all round for hits from behind) and coloured by what hit you: fireball orange, sword cyan. Shield
    /// blocks get no screen flash; the shield's own flash shows them.</item>
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

        [Header("Chip damage")]
        [Tooltip("Seconds the lost HP stays white before it drains away.")]
        [SerializeField] private float chipHoldSeconds = 0.5f;
        [Tooltip("Bar fractions per second the white chip drains at.")]
        [SerializeField] private float chipDrainRate = 0.6f;
        [Tooltip("At or below this HP fraction the bar pulses.")]
        [SerializeField] private float lowHpFraction = 0.25f;

        [Header("Damage flash")]
        [Tooltip("Additive SpellGame/Fireball/Particle material; each edge gets a tinted copy. None = no damage flash.")]
        [SerializeField] private Material flashMaterial;
        [SerializeField] private float flashDuration = 0.3f;
        [SerializeField] private float flashDistance = 0.5f;
        [Tooltip("Left/right glow: from this angle off centre (transparent) out to this one (full); Quest 3 sees ~55°.")]
        [SerializeField] private Vector2 sideFlashDegrees = new(30f, 62f);
        [Tooltip("Top/bottom glow, same idea; Quest 3 sees ~48° up and down.")]
        [SerializeField] private Vector2 topFlashDegrees = new(26f, 58f);
        [SerializeField, Range(0f, 1f)] private float flashBrightness = 0.8f;
        [SerializeField] private Color fireballFlash = new(1f, 0.42f, 0.05f);
        [SerializeField] private Color swordFlash = new(0.25f, 0.85f, 1f);

        private sealed class Bar
        {
            public Transform Root;
            public Transform Fill;
            public Transform Chip;
            public Material FillMaterial;
            public Vector2 Size;
            public float Shown = -1f;
            public float LastFraction = -1f;
            public float ChipHoldUntil;
        }

        private static Mesh _quadMesh;

        private readonly Dictionary<string, PlayerSnapshot> _players = new();
        private readonly Dictionary<string, Bar> _headBars = new();
        private Bar _wristBar;
        private Material _backMaterial;
        private Material _chipMaterial;
        private Transform[] _flashEdges;
        private Material[] _edgeMaterials;
        private Color _flashColor;
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
            _chipMaterial = Tinted(new Color(1f, 0.95f, 0.85f));
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
            var lowHp = 1f - Mathf.Clamp01(damage.HpAfter / MaxHpOf(damage.TargetId));
            var color = damage.Kind == SpellKind.Sword ? swordFlash : damage.Kind == SpellKind.Fireball ? fireballFlash : Color.red;
            Flash(Mathf.Clamp01(0.4f + damage.Amount / 20f + 0.5f * lowHp), color, AttackerPosition(damage.SourceId, damage.Pos));
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
            _flashColor = color;
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
            var fade = active ? flashBrightness * _flashStrength * (1f - t) * (1f - t) : 0f;
            for (var i = 0; i < _flashEdges.Length; i++)
            {
                _flashEdges[i].gameObject.SetActive(active && _flashWeights[i] > 0.01f);
                if (active)
                    _edgeMaterials[i].SetColor("_Color", new Color(_flashColor.r, _flashColor.g, _flashColor.b, fade * _flashWeights[i]));
            }
        }

        private float MaxHpOf(string playerId) =>
            playerId != null && _players.TryGetValue(playerId, out var player) && player.MaxHp > 0f ? player.MaxHp : maxHp;

        private void PlaceBar(Bar bar, Vector3 position, Vector3 viewer, PlayerSnapshot player)
        {
            var away = position - viewer;
            bar.Root.SetPositionAndRotation(position, away.sqrMagnitude > 1e-6f ? Quaternion.LookRotation(away) : Quaternion.identity);

            var fraction = Mathf.Clamp01(player.Hp / MaxHpOf(player.PlayerId));
            SetSegment(bar.Fill, bar.Size, fraction, -0.002f);

            // Chip damage, fighting-game style: the HP just lost stays white for a moment, then drains down to the fill.
            if (fraction < bar.LastFraction)
                bar.ChipHoldUntil = Time.time + chipHoldSeconds;
            bar.LastFraction = fraction;
            if (bar.Shown < fraction)
                bar.Shown = fraction;
            else if (Time.time >= bar.ChipHoldUntil)
                bar.Shown = Mathf.MoveTowards(bar.Shown, fraction, chipDrainRate * Time.deltaTime);
            SetSegment(bar.Chip, bar.Size, bar.Shown, -0.001f);

            var color = HpColor(fraction);
            var scale = 1f;
            if (fraction > 0f && fraction <= lowHpFraction)
            {
                var pulse = 0.5f + 0.5f * Mathf.Sin(Time.time * 8f);
                color = Color.Lerp(color, new Color(1f, 0.75f, 0.75f), 0.6f * pulse);
                scale = 1f + 0.06f * pulse;
            }
            bar.FillMaterial.SetColor("_BaseColor", color);
            bar.Root.localScale = Vector3.one * scale;
        }

        private static void SetSegment(Transform segment, Vector2 size, float fraction, float depth)
        {
            var width = size.x * fraction;
            segment.gameObject.SetActive(fraction > 0f);
            segment.localPosition = new Vector3((width - size.x) * 0.5f, 0f, depth);
            segment.localScale = new Vector3(width, size.y, 1f);
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
            var chip = CreateQuad("Chip", root, _chipMaterial);
            var fillMaterial = Tinted(Color.green);
            var fill = CreateQuad("Fill", root, fillMaterial);
            root.gameObject.SetActive(false);
            return new Bar { Root = root, Fill = fill, Chip = chip, FillMaterial = fillMaterial, Size = size };
        }

        /// <summary>
        /// Top, bottom, left, right glows at the rim of the view, parented to the eye: strips that fade from transparent
        /// (towards the centre) to full (past the edge of view), so the middle of the view stays clear.
        /// </summary>
        private Transform[] CreateFlashEdges()
        {
            var parent = centerEye != null ? centerEye : transform;
            var mesh = GradientStripMesh();
            var (sideCentre, sideWidth) = Band(sideFlashDegrees);
            var (topCentre, topHeight) = Band(topFlashDegrees);
            var layout = new[]
            {
                (new Vector3(0f, topCentre, flashDistance), 90f, topHeight, flashDistance * 5f),
                (new Vector3(0f, -topCentre, flashDistance), -90f, topHeight, flashDistance * 5f),
                (new Vector3(-sideCentre, 0f, flashDistance), 180f, sideWidth, flashDistance * 4f),
                (new Vector3(sideCentre, 0f, flashDistance), 0f, sideWidth, flashDistance * 4f),
            };
            var edges = new Transform[layout.Length];
            _edgeMaterials = new Material[layout.Length];
            for (var i = 0; i < layout.Length; i++)
            {
                var (position, roll, depth, length) = layout[i];
                var go = new GameObject("Damage Flash");
                go.transform.SetParent(parent, false);
                go.AddComponent<MeshFilter>().sharedMesh = mesh;
                var renderer = go.AddComponent<MeshRenderer>();
                renderer.sharedMaterial = _edgeMaterials[i] = flashMaterial != null ? new Material(flashMaterial) : null;
                renderer.shadowCastingMode = ShadowCastingMode.Off;
                renderer.receiveShadows = false;
                edges[i] = go.transform;
                edges[i].localPosition = position;
                edges[i].localRotation = Quaternion.Euler(0f, 0f, roll);
                edges[i].localScale = new Vector3(depth, length, 1f);
                go.SetActive(false);
            }
            return flashMaterial != null ? edges : System.Array.Empty<Transform>();
        }

        /// <summary>Centre and size, at <see cref="flashDistance"/>, of the band between two angles off the view centre.</summary>
        private (float Centre, float Size) Band(Vector2 degrees)
        {
            var inner = flashDistance * Mathf.Tan(degrees.x * Mathf.Deg2Rad);
            var outer = flashDistance * Mathf.Tan(degrees.y * Mathf.Deg2Rad);
            return ((inner + outer) * 0.5f, outer - inner);
        }

        /// <summary>A unit quad whose vertex alpha eases from 0 at x = -0.5 (inner side) to 1 at x = +0.5 (outer side).</summary>
        private static Mesh GradientStripMesh()
        {
            float[] xs = { -0.5f, -0.2f, 0.15f, 0.5f };
            float[] alphas = { 0f, 0.15f, 0.5f, 1f };
            var vertices = new Vector3[xs.Length * 2];
            var colors = new Color[vertices.Length];
            var triangles = new int[(xs.Length - 1) * 6];
            for (var i = 0; i < xs.Length; i++)
            {
                vertices[i * 2] = new Vector3(xs[i], -0.5f, 0f);
                vertices[i * 2 + 1] = new Vector3(xs[i], 0.5f, 0f);
                colors[i * 2] = colors[i * 2 + 1] = new Color(1f, 1f, 1f, alphas[i]);
                if (i == 0)
                    continue;
                var t = (i - 1) * 6;
                var a = (i - 1) * 2;
                triangles[t] = a;
                triangles[t + 1] = a + 1;
                triangles[t + 2] = a + 2;
                triangles[t + 3] = a + 1;
                triangles[t + 4] = a + 3;
                triangles[t + 5] = a + 2;
            }
            return new Mesh { name = "Damage Flash Strip", vertices = vertices, colors = colors, triangles = triangles };
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
