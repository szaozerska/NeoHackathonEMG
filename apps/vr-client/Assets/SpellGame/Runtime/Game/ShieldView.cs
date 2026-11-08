using System.Collections.Generic;
using SpellGame.Protocol;
using UnityEngine;
using UnityEngine.Rendering;

namespace SpellGame.Game
{
    /// <summary>
    /// Renders shields from server events and state (game_plan.md stage 1c):
    /// <list type="bullet">
    /// <item>while <c>item == "shield"</c>, an energy force field sits in front of the band hand, facing away from the
    /// chest through the hand: a shallow dome whose rim is the disc the server hit-tests;</item>
    /// <item>the field swells and warms towards gold with <c>shield_boost</c> (push impulse), with a ring pulse when the
    /// boost reaches parry strength;</item>
    /// <item><c>impact blocked</c> on a shield ripples the field from the hit point and throws sparks;
    /// <c>impact parried</c> adds a gold flash, bigger burst and shock rings.</item>
    /// </list>
    /// The local player's shield follows local hand tracking. The look lives in the <c>SpellGame/Shield/*</c> shaders
    /// (Assets/SpellGame/Shield).
    /// </summary>
    public sealed class ShieldView : MonoBehaviour
    {
        private const int MaxHits = 4;
        private static readonly int BoostId = Shader.PropertyToID("_Boost");
        private static readonly int SpawnId = Shader.PropertyToID("_Spawn");
        private static readonly int HitPointsId = Shader.PropertyToID("_HitPoints");

        private static readonly Color FieldColor = new(0.45f, 0.85f, 1f);
        private static readonly Color ParryColor = new(1f, 0.85f, 0.4f);

        [SerializeField] private GameClient gameClient;
        [Tooltip("SpellGame/Shield/ForceField")]
        [SerializeField] private Material shieldMaterial;
        [Tooltip("SpellGame/Shield/Spark with Ring = 0")]
        [SerializeField] private Material sparkMaterial;
        [Tooltip("SpellGame/Shield/Spark with Ring = 1")]
        [SerializeField] private Material ringMaterial;

        [Header("Must match the server's Tuning")]
        [Tooltip("Tuning.shield_radius")]
        [SerializeField] private float shieldRadius = 0.3f;
        [Tooltip("Tuning.shield_offset")]
        [SerializeField] private float shieldOffset = 0.08f;
        [Tooltip("Tuning.shield_parry_min_boost")]
        [SerializeField] private float parryMinBoost = 0.3f;

        [Header("Look")]
        [Tooltip("Dome height as a fraction of the disc diameter; the rim stays on the hit-tested disc.")]
        [SerializeField] private float domeDepth = 0.12f;
        [Tooltip("Extra size at full boost.")]
        [SerializeField] private float boostSwell = 0.2f;
        [Tooltip("Seconds for the field to unfold from the centre when raised.")]
        [SerializeField] private float spawnTime = 0.18f;
        [Tooltip("Seconds for a parry flash to fade.")]
        [SerializeField] private float flashTime = 0.35f;

        private readonly Dictionary<string, PlayerSnapshot> _players = new();
        private readonly Dictionary<string, Disc> _discs = new();
        private Mesh _domeMesh;
        private ParticleSystem _sparks;
        private ParticleSystem _rings;

        private sealed class Disc
        {
            public Transform Transform;
            public MeshRenderer Renderer;
            public readonly MaterialPropertyBlock Props = new();
            public readonly Vector4[] Hits = new Vector4[MaxHits];
            public int NextHit;
            public bool Raised;
            public float RaisedAt;
            public float LastBoost;
            public float Flash;
            public float Diameter;
        }

        private void Awake()
        {
            _domeMesh = BuildDomeMesh(domeDepth, rings: 16, segments: 48);
            _sparks = CreateEmitter("Shield Sparks", sparkMaterial, stretched: true, maxParticles: 300, gravity: 0.5f,
                sizeCurve: AnimationCurve.Linear(0f, 1f, 1f, 0f));
            _rings = CreateEmitter("Shield Rings", ringMaterial, stretched: false, maxParticles: 16, gravity: 0f,
                sizeCurve: new AnimationCurve(new Keyframe(0f, 0.25f, 0f, 3f), new Keyframe(1f, 1f, 0.3f, 0f)));
        }

        private void OnEnable()
        {
            gameClient.SpellReceived += OnSpell;
            gameClient.StateReceived += OnState;
            gameClient.ImpactReceived += OnImpact;
        }

        private void OnDisable()
        {
            gameClient.SpellReceived -= OnSpell;
            gameClient.StateReceived -= OnState;
            gameClient.ImpactReceived -= OnImpact;
        }

        private void OnSpell(SpellMessage spell)
        {
            if (spell.Spell != SpellKind.Shield || spell.State != SpellState.Sheathed)
                return;

            var hasDisc = TryGetDisc(spell.CasterId, out var center, out var normal);
            if (_players.TryGetValue(spell.CasterId, out var player))
                player.Item = "none";

            var at = hasDisc ? center : ToVector(spell.Origin);
            if (at != null)
                EmitSparks(at.Value, hasDisc ? normal : Vector3.zero, FieldColor, count: 14, speed: 0.6f, size: 0.02f, lifetime: 0.35f);
        }

        private void OnState(StateMessage state)
        {
            _players.Clear();
            foreach (var player in state.Players)
                _players[player.PlayerId] = player;
        }

        private void OnImpact(ImpactMessage impact)
        {
            if (impact.Pos is not { Length: 3 })
                return;

            var parried = impact.Reason == ImpactReason.Parried;
            if (!parried && impact.Reason != ImpactReason.Blocked)
                return;

            var position = impact.Position;
            var normal = Vector3.zero;
            if (impact.TargetId != null && _discs.TryGetValue(impact.TargetId, out var disc) && disc.Raised)
            {
                normal = disc.Transform.up;
                AddRipple(disc, position);
                if (parried)
                    disc.Flash = 1f;
            }

            if (parried)
            {
                EmitSparks(position, normal, ParryColor, count: 60, speed: 4f, size: 0.03f, lifetime: 0.5f);
                EmitSparks(position, normal, Color.white, count: 20, speed: 2f, size: 0.02f, lifetime: 0.3f);
                EmitRing(position, ParryColor, size: 0.8f, lifetime: 0.35f);
                EmitRing(position, Color.white, size: 0.45f, lifetime: 0.2f);
            }
            else
            {
                EmitSparks(position, normal, FieldColor, count: 24, speed: 2.2f, size: 0.022f, lifetime: 0.35f);
                EmitRing(position, FieldColor, size: 0.4f, lifetime: 0.25f);
            }
        }

        private void Update()
        {
            var now = Time.timeSinceLevelLoad;
            foreach (var (playerId, player) in _players)
            {
                var disc = DiscFor(playerId);
                var center = Vector3.zero;
                var normal = Vector3.up;
                var raised = player.Item == SpellKind.Shield && TryGetDisc(playerId, out center, out normal);
                if (raised && !disc.Raised)
                {
                    disc.RaisedAt = now;
                    disc.LastBoost = 0f;
                    EmitRing(center, FieldColor, size: 2.4f * shieldRadius, lifetime: 0.25f);
                }

                disc.Raised = raised;
                disc.Transform.gameObject.SetActive(raised);
                if (!raised)
                    continue;

                var boost = Mathf.Clamp01(player.ShieldBoost);
                disc.Diameter = 2f * shieldRadius * (1f + boostSwell * boost);
                if (boost >= parryMinBoost && disc.LastBoost < parryMinBoost)
                    EmitRing(center, ParryColor, size: 1.3f * disc.Diameter, lifetime: 0.2f);
                disc.LastBoost = boost;

                disc.Transform.position = center;
                disc.Transform.rotation = Quaternion.FromToRotation(Vector3.up, normal);
                disc.Transform.localScale = Vector3.one * disc.Diameter;

                disc.Flash = Mathf.MoveTowards(disc.Flash, 0f, Time.deltaTime / Mathf.Max(flashTime, 0.01f));
                disc.Props.SetFloat(BoostId, Mathf.Max(boost, disc.Flash));
                disc.Props.SetFloat(SpawnId, Mathf.Clamp01((now - disc.RaisedAt) / Mathf.Max(spawnTime, 0.01f)));
                disc.Props.SetVectorArray(HitPointsId, disc.Hits);
                disc.Renderer.SetPropertyBlock(disc.Props);
            }

            foreach (var (playerId, disc) in _discs)
            {
                if (_players.ContainsKey(playerId))
                    continue;
                disc.Raised = false;
                disc.Transform.gameObject.SetActive(false);
            }
        }

        private Disc DiscFor(string playerId)
        {
            if (_discs.TryGetValue(playerId, out var disc))
                return disc;

            var go = new GameObject($"Shield {playerId}");
            go.transform.SetParent(transform, false);
            go.AddComponent<MeshFilter>().sharedMesh = _domeMesh;
            var renderer = go.AddComponent<MeshRenderer>();
            renderer.sharedMaterial = shieldMaterial;
            renderer.shadowCastingMode = ShadowCastingMode.Off;
            renderer.receiveShadows = false;
            go.SetActive(false);

            disc = new Disc { Transform = go.transform, Renderer = renderer };
            for (var i = 0; i < MaxHits; i++)
                disc.Hits[i] = new Vector4(0f, 0f, 0f, -1000f);
            _discs[playerId] = disc;
            return disc;
        }

        /// <summary>Queue a ripple in the field shader: hit point in the dome's object space, start time = shader <c>_Time.y</c>.</summary>
        private static void AddRipple(Disc disc, Vector3 worldPosition)
        {
            Vector4 hit = disc.Transform.InverseTransformPoint(worldPosition);
            hit.w = Time.timeSinceLevelLoad;
            disc.Hits[disc.NextHit] = hit;
            disc.NextHit = (disc.NextHit + 1) % MaxHits;
        }

        /// <summary>The disc the server hit-tests: <see cref="shieldOffset"/> in front of the band hand, facing chest → hand.</summary>
        private bool TryGetDisc(string playerId, out Vector3 center, out Vector3 normal)
        {
            center = normal = default;
            if (!gameClient.TryGetJoints(playerId, out var joints))
                return false;

            var left = (_players.TryGetValue(playerId, out var player) ? player.BandHand : HandSide.Right) == HandSide.Left;
            var hand = left ? joints.LHand : joints.RHand;
            var chest = joints.Chest ?? joints.Head;
            if (hand == null || chest == null)
                return false;

            var outward = hand.Position - chest.Position;
            if (outward.sqrMagnitude < 1e-6f)
                return false;

            normal = outward.normalized;
            center = hand.Position + normal * shieldOffset;
            return true;
        }

        /// <summary>Sparks fly out of the shield's front (<paramref name="normal"/>), or in all directions if it is zero.</summary>
        private void EmitSparks(Vector3 position, Vector3 normal, Color color, int count, float speed, float size, float lifetime)
        {
            var emit = new ParticleSystem.EmitParams { position = position, applyShapeToPosition = false };
            for (var i = 0; i < count; i++)
            {
                var direction = (normal + Random.insideUnitSphere * 0.9f).normalized;
                if (direction == Vector3.zero)
                    direction = Random.onUnitSphere;
                emit.velocity = direction * Random.Range(speed * 0.3f, speed);
                emit.startSize = Random.Range(size * 0.5f, size);
                emit.startLifetime = Random.Range(lifetime * 0.5f, lifetime);
                emit.startColor = color;
                _sparks.Emit(emit, 1);
            }
        }

        /// <summary>A camera-facing shock ring that grows to <paramref name="size"/> metres across and fades.</summary>
        private void EmitRing(Vector3 position, Color color, float size, float lifetime)
        {
            var emit = new ParticleSystem.EmitParams
            {
                position = position,
                applyShapeToPosition = false,
                velocity = Vector3.zero,
                startSize = size,
                startLifetime = lifetime,
                startColor = color,
            };
            _rings.Emit(emit, 1);
        }

        private ParticleSystem CreateEmitter(string name, Material material, bool stretched, int maxParticles, float gravity, AnimationCurve sizeCurve)
        {
            var go = new GameObject(name);
            go.transform.SetParent(transform, false);
            var particles = go.AddComponent<ParticleSystem>();
            particles.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);

            var main = particles.main;
            main.playOnAwake = false;
            main.loop = true;
            main.simulationSpace = ParticleSystemSimulationSpace.World;
            main.maxParticles = maxParticles;
            main.gravityModifier = gravity;

            var emission = particles.emission;
            emission.enabled = false;
            var shape = particles.shape;
            shape.enabled = false;

            var sizeOverLifetime = particles.sizeOverLifetime;
            sizeOverLifetime.enabled = true;
            sizeOverLifetime.size = new ParticleSystem.MinMaxCurve(1f, sizeCurve);

            var fade = new Gradient();
            fade.SetKeys(
                new[] { new GradientColorKey(Color.white, 0f), new GradientColorKey(Color.white, 1f) },
                new[] { new GradientAlphaKey(1f, 0f), new GradientAlphaKey(0.8f, 0.5f), new GradientAlphaKey(0f, 1f) });
            var colorOverLifetime = particles.colorOverLifetime;
            colorOverLifetime.enabled = true;
            colorOverLifetime.color = new ParticleSystem.MinMaxGradient(fade);

            var renderer = go.GetComponent<ParticleSystemRenderer>();
            renderer.renderMode = stretched ? ParticleSystemRenderMode.Stretch : ParticleSystemRenderMode.Billboard;
            if (stretched)
            {
                renderer.velocityScale = 0.04f;
                renderer.lengthScale = 1.5f;
            }
            renderer.sharedMaterial = material;
            renderer.shadowCastingMode = ShadowCastingMode.Off;
            renderer.receiveShadows = false;

            particles.Play();
            return particles;
        }

        /// <summary>
        /// Unit spherical cap: rim radius 0.5 on the y = 0 plane, apex at y = <paramref name="depth"/>, front faces towards +y.
        /// </summary>
        private static Mesh BuildDomeMesh(float depth, int rings, int segments)
        {
            var height = Mathf.Max(depth, 0.001f);
            var sphereRadius = (0.25f + height * height) / (2f * height);
            var sphereCenter = new Vector3(0f, height - sphereRadius, 0f);

            var vertices = new Vector3[1 + rings * segments];
            var normals = new Vector3[vertices.Length];
            vertices[0] = new Vector3(0f, height, 0f);
            normals[0] = Vector3.up;
            for (var ring = 1; ring <= rings; ring++)
            {
                var radius = 0.5f * ring / rings;
                var y = Mathf.Sqrt(sphereRadius * sphereRadius - radius * radius) + sphereCenter.y;
                for (var s = 0; s < segments; s++)
                {
                    var angle = 2f * Mathf.PI * s / segments;
                    var vertex = new Vector3(radius * Mathf.Cos(angle), y, radius * Mathf.Sin(angle));
                    var index = 1 + (ring - 1) * segments + s;
                    vertices[index] = vertex;
                    normals[index] = (vertex - sphereCenter).normalized;
                }
            }

            // Clockwise seen from +y, so front faces point out of the dome.
            var triangles = new List<int>(segments * 3 * (2 * rings - 1));
            for (var s = 0; s < segments; s++)
            {
                var next = (s + 1) % segments;
                triangles.Add(0);
                triangles.Add(1 + next);
                triangles.Add(1 + s);
            }
            for (var ring = 1; ring < rings; ring++)
            {
                var inner = 1 + (ring - 1) * segments;
                var outer = inner + segments;
                for (var s = 0; s < segments; s++)
                {
                    var next = (s + 1) % segments;
                    triangles.Add(inner + s);
                    triangles.Add(inner + next);
                    triangles.Add(outer + s);
                    triangles.Add(inner + next);
                    triangles.Add(outer + next);
                    triangles.Add(outer + s);
                }
            }

            var mesh = new Mesh { name = "Shield Dome" };
            mesh.SetVertices(vertices);
            mesh.SetNormals(normals);
            mesh.SetTriangles(triangles, 0);
            mesh.RecalculateBounds();
            return mesh;
        }

        private static Vector3? ToVector(float[] values) =>
            values is { Length: 3 } ? new Vector3(values[0], values[1], values[2]) : null;
    }
}
