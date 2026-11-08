using System.Collections.Generic;
using SpellGame.Protocol;
using UnityEngine;
using UnityEngine.Rendering;

namespace SpellGame.Game
{
    /// <summary>
    /// Renders swords from server events and state (game_plan.md stage 1b):
    /// <list type="bullet">
    /// <item>draw (<c>spell cast</c>) ignites the blade out of the hand with a spark flash, sheathe (<c>spell sheathed</c>)
    /// removes the blade at once;</item>
    /// <item>while <c>item == "sword"</c>, an energy blade runs from the band hand along the forearm (elbow to hand), the same
    /// line the server hit-tests: an opaque white-hot core inside an additive glow, tinted per player (P1 red, P2 blue);</item>
    /// <item>a swept swing trail appears once the tip is fast enough to hurt, and grows from the tip down to the whole blade
    /// (and brightens) up to full-damage speed;</item>
    /// <item>sword <c>damage</c> and sword clashes on a shield (<c>impact</c> blocked/parried) throw streaking sparks and a flash
    /// at the contact point.</item>
    /// </list>
    /// Like the fireball, the local player's blade follows local hand tracking. Shaders and their passthrough alpha handling
    /// are in <c>Assets/SpellGame/Sword</c>.
    /// </summary>
    public sealed class SwordView : MonoBehaviour
    {
        private static readonly int ColorId = Shader.PropertyToID("_Color");

        /// <summary>Blade colours, matching the player-ID markers; other players keep the materials' own colour.</summary>
        private static readonly Dictionary<string, Color> PlayerColors = new()
        {
            ["P1"] = new Color(1f, 0.12f, 0.08f),
            ["P2"] = new Color(0.2f, 0.5f, 1f),
        };

        /// <summary>Seconds without a new tip position before the tip counts as still (remote poses arrive slower than frames).</summary>
        private const float StaleTipTime = 0.1f;

        [SerializeField] private GameClient gameClient;
        [Tooltip("Opaque blade core (SpellGame/Sword/BladeCore).")]
        [SerializeField] private Material bladeMaterial;
        [Tooltip("Additive glow around the core (SpellGame/Sword/BladeGlow).")]
        [SerializeField] private Material glowMaterial;
        [Tooltip("Swept swing trail (SpellGame/Sword/Trail).")]
        [SerializeField] private Material trailMaterial;
        [Tooltip("Additive sparks and flashes (SpellGame/Sword/Spark).")]
        [SerializeField] private Material sparkMaterial;

        [Header("Must match the server's Tuning")]
        [Tooltip("Tuning.sword_length")]
        [SerializeField] private float bladeLength = 0.9f;
        [Tooltip("Tuning.sword_min_tip_speed: slower swings don't hurt and draw no trail.")]
        [SerializeField] private float minTipSpeed = 2f;
        [Tooltip("Tuning.sword_full_damage_tip_speed")]
        [SerializeField] private float fullDamageTipSpeed = 8f;

        [Header("Look")]
        [Tooltip("Diameter of the solid core.")]
        [SerializeField] private float bladeWidth = 0.03f;
        [Tooltip("Diameter of the glow. Server Tuning.sword_radius is 0.04, so 0.08 shows the true hit width.")]
        [SerializeField] private float glowWidth = 0.1f;
        [Tooltip("Seconds a point of the swing trail stays visible.")]
        [SerializeField] private float trailTime = 0.2f;
        [Tooltip("Share of the blade, from the tip, the trail covers at the slowest damaging swing; the whole blade at full-damage speed.")]
        [Range(0.05f, 1f)]
        [SerializeField] private float minTrailCoverage = 0.35f;
        [Tooltip("Smoothing steps between trail samples, so fast swings stay round at frame (or network) rate.")]
        [Range(1, 8)]
        [SerializeField] private int trailSubdivisions = 4;
        [Tooltip("Seconds the blade takes to extend out of the hand on draw. Visual only: the server hits with the whole blade at once.")]
        [SerializeField] private float igniteTime = 0.1f;

        private sealed class BladeVisual
        {
            public Transform Core;
            public Transform Glow;
            public SweptTrail Trail;
            public Color Color;
            public bool Visible;
            public float ShownAt;
            public Vector3? LastTip;
            public float LastTipTime;
            public float TipSpeed;
        }

        private readonly Dictionary<string, PlayerSnapshot> _players = new();
        private readonly Dictionary<string, BladeVisual> _blades = new();
        private Mesh _coreMesh;
        private Mesh _glowMesh;

        private void OnEnable()
        {
            gameClient.SpellReceived += OnSpell;
            gameClient.StateReceived += OnState;
            gameClient.DamageReceived += OnDamage;
            gameClient.ImpactReceived += OnImpact;
        }

        private void OnDisable()
        {
            gameClient.SpellReceived -= OnSpell;
            gameClient.StateReceived -= OnState;
            gameClient.DamageReceived -= OnDamage;
            gameClient.ImpactReceived -= OnImpact;
        }

        private void OnSpell(SpellMessage spell)
        {
            if (spell.Spell != SpellKind.Sword)
                return;

            Vector3? at = TryGetBlade(spell.CasterId, out var hilt, out _) ? hilt : ToVector(spell.Origin);
            var color = ColorFor(spell.CasterId);
            switch (spell.State)
            {
                case SpellState.Cast:
                    if (at != null)
                        Sparks(at.Value, color, count: 24, speed: 1.5f, size: 0.012f, lifetime: 0.35f, flashSize: 0.15f);
                    break;
                case SpellState.Sheathed:
                    if (_players.TryGetValue(spell.CasterId, out var player))
                        player.Item = "none";
                    if (at != null)
                        Sparks(at.Value, color, count: 10, speed: 0.6f, size: 0.01f, lifetime: 0.3f, flashSize: 0f);
                    break;
            }
        }

        private void OnState(StateMessage state)
        {
            _players.Clear();
            foreach (var player in state.Players)
                _players[player.PlayerId] = player;
        }

        private void OnDamage(DamageMessage damage)
        {
            if (damage.Kind != SpellKind.Sword || ToVector(damage.Pos) is not { } at)
                return;
            Sparks(at, ColorFor(damage.SourceId), count: 45, speed: 4f, size: 0.015f, lifetime: 0.45f, flashSize: 0.3f);
        }

        private void OnImpact(ImpactMessage impact)
        {
            if (impact.Kind != SpellKind.Sword || impact.Pos is not { Length: 3 })
                return;
            var parried = impact.Reason == ImpactReason.Parried;
            Sparks(impact.Position, ColorFor(impact.OwnerId), count: parried ? 50 : 25, speed: parried ? 4.5f : 3f,
                size: 0.012f, lifetime: 0.4f, flashSize: parried ? 0.3f : 0.18f);
        }

        private void Update()
        {
            foreach (var (playerId, player) in _players)
            {
                var visual = BladeFor(playerId);
                if (player.Item == SpellKind.Sword && TryGetBlade(playerId, out var hilt, out var tip))
                    ShowBlade(visual, hilt, tip);
                else
                    HideBlade(visual);
            }

            foreach (var (playerId, visual) in _blades)
            {
                if (!_players.ContainsKey(playerId))
                    HideBlade(visual);
                visual.Trail.Rebuild(trailTime, trailSubdivisions);
            }
        }

        private void ShowBlade(BladeVisual visual, Vector3 hilt, Vector3 tip)
        {
            var now = Time.time;
            if (!visual.Visible)
            {
                visual.Visible = true;
                visual.ShownAt = now;
                visual.Core.gameObject.SetActive(true);
                if (visual.Glow != null)
                    visual.Glow.gameObject.SetActive(true);
                visual.Trail.Clear();
            }

            var extended = igniteTime > 0f ? Mathf.SmoothStep(0.05f, 1f, (now - visual.ShownAt) / igniteTime) : 1f;
            var rotation = Quaternion.FromToRotation(Vector3.up, tip - hilt);
            PlaceAlong(visual.Core, hilt, rotation, extended);
            if (visual.Glow != null)
                PlaceAlong(visual.Glow, hilt, rotation, extended);

            var tipSpeed = UpdateTipSpeed(visual, tip, now, out var tipMoved);
            if (!tipMoved)
                return;

            var speed01 = Mathf.InverseLerp(minTipSpeed, fullDamageTipSpeed, tipSpeed);
            var strength = tipSpeed >= minTipSpeed ? Mathf.Lerp(0.4f, 1f, speed01) : 0f;
            var inner = Vector3.Lerp(tip, hilt, Mathf.Lerp(minTrailCoverage, 1f, speed01));
            visual.Trail.Add(inner, tip, now, strength);
        }

        /// <summary>
        /// Tip speed by finite difference, measured only between frames where the tip actually moved, so remote blades
        /// (whose poses arrive at network rate) don't flicker between fast and still.
        /// </summary>
        private static float UpdateTipSpeed(BladeVisual visual, Vector3 tip, float now, out bool moved)
        {
            moved = false;
            if (visual.LastTip is not { } lastTip)
            {
                visual.LastTip = tip;
                visual.LastTipTime = now;
                visual.TipSpeed = 0f;
                moved = true;
                return 0f;
            }

            var elapsed = now - visual.LastTipTime;
            var distance = Vector3.Distance(tip, lastTip);
            if (distance > 1e-4f && elapsed > 0f)
            {
                visual.TipSpeed = distance / elapsed;
                visual.LastTip = tip;
                visual.LastTipTime = now;
                moved = true;
            }
            else if (elapsed > StaleTipTime)
            {
                visual.TipSpeed = 0f;
            }

            return visual.TipSpeed;
        }

        private static void PlaceAlong(Transform blade, Vector3 hilt, Quaternion rotation, float extended)
        {
            blade.SetPositionAndRotation(hilt, rotation);
            blade.localScale = new Vector3(1f, extended, 1f);
        }

        private static void HideBlade(BladeVisual visual)
        {
            if (!visual.Visible)
                return;
            visual.Visible = false;
            visual.Core.gameObject.SetActive(false);
            if (visual.Glow != null)
                visual.Glow.gameObject.SetActive(false);
            visual.LastTip = null;
            visual.TipSpeed = 0f;
        }

        private BladeVisual BladeFor(string playerId)
        {
            if (_blades.TryGetValue(playerId, out var visual))
                return visual;

            _coreMesh ??= BuildBladeMesh(bladeWidth * 0.5f, bladeLength, segments: 12);
            _glowMesh ??= BuildBladeMesh(glowWidth * 0.5f, bladeLength, segments: 16);

            visual = new BladeVisual { Color = ColorFor(playerId) };
            var tint = new MaterialPropertyBlock();
            var tinted = PlayerColors.ContainsKey(playerId);
            if (tinted)
                tint.SetColor(ColorId, visual.Color);

            visual.Core = CreateMeshObject($"Sword {playerId}", _coreMesh, bladeMaterial, tinted ? tint : null);
            visual.Core.gameObject.SetActive(false);
            if (glowMaterial != null)
            {
                visual.Glow = CreateMeshObject($"Sword Glow {playerId}", _glowMesh, glowMaterial, tinted ? tint : null);
                visual.Glow.gameObject.SetActive(false);
            }

            var trail = CreateMeshObject($"Sword Trail {playerId}", null, trailMaterial, tinted ? tint : null);
            visual.Trail = new SweptTrail(trail);
            _blades[playerId] = visual;
            return visual;
        }

        private Transform CreateMeshObject(string objectName, Mesh mesh, Material material, MaterialPropertyBlock tint)
        {
            var go = new GameObject(objectName);
            go.transform.SetParent(transform, false);
            go.AddComponent<MeshFilter>().sharedMesh = mesh;
            var meshRenderer = go.AddComponent<MeshRenderer>();
            meshRenderer.sharedMaterial = material;
            meshRenderer.shadowCastingMode = ShadowCastingMode.Off;
            meshRenderer.receiveShadows = false;
            meshRenderer.lightProbeUsage = LightProbeUsage.Off;
            meshRenderer.reflectionProbeUsage = ReflectionProbeUsage.Off;
            if (tint != null)
                meshRenderer.SetPropertyBlock(tint);
            return go.transform;
        }

        private Color ColorFor(string playerId)
        {
            if (playerId != null && PlayerColors.TryGetValue(playerId, out var color))
                return color;
            return glowMaterial != null ? glowMaterial.color : bladeMaterial != null ? bladeMaterial.color : Color.cyan;
        }

        /// <summary>The blade the server hit-tests: from the band hand, <see cref="bladeLength"/> along elbow → hand.</summary>
        private bool TryGetBlade(string playerId, out Vector3 hilt, out Vector3 tip)
        {
            hilt = tip = default;
            if (!gameClient.TryGetJoints(playerId, out var joints))
                return false;

            var left = (_players.TryGetValue(playerId, out var player) ? player.BandHand : HandSide.Right) == HandSide.Left;
            var hand = left ? joints.LHand : joints.RHand;
            var forearmBase = (left ? joints.LElbow : joints.RElbow) ?? (left ? joints.LWrist : joints.RWrist);
            if (hand == null || forearmBase == null)
                return false;

            var direction = hand.Position - forearmBase.Position;
            if (direction.sqrMagnitude < 1e-6f)
                return false;

            hilt = hand.Position;
            tip = hilt + direction.normalized * bladeLength;
            return true;
        }

        private static Vector3? ToVector(float[] values) =>
            values is { Length: 3 } ? new Vector3(values[0], values[1], values[2]) : null;

        /// <summary>
        /// A capsule along +y with true round ends: the shaft runs from the hilt (y = 0) to the tip (y = <paramref name="length"/>)
        /// and each end is capped by a hemisphere of <paramref name="radius"/>, like the server's hit capsule. Built at real
        /// size so the caps aren't squashed the way a scaled primitive capsule's are.
        /// </summary>
        private static Mesh BuildBladeMesh(float radius, float length, int segments, int capRings = 5)
        {
            var vertices = new List<Vector3>();
            var normals = new List<Vector3>();
            var triangles = new List<int>();

            var rings = 2 * (capRings + 1);
            for (var ring = 0; ring < rings; ring++)
            {
                var topCap = ring > capRings;
                var step = topCap ? ring - capRings - 1 : ring;
                var angle = Mathf.Deg2Rad * (topCap ? Mathf.Lerp(0f, 90f, step / (float)capRings) : Mathf.Lerp(-90f, 0f, step / (float)capRings));
                var ringRadius = Mathf.Cos(angle);
                var ringHeight = Mathf.Sin(angle);
                var centre = topCap ? length : 0f;
                for (var segment = 0; segment < segments; segment++)
                {
                    var around = 2f * Mathf.PI * segment / segments;
                    var normal = new Vector3(Mathf.Cos(around) * ringRadius, ringHeight, Mathf.Sin(around) * ringRadius);
                    normals.Add(normal);
                    vertices.Add(new Vector3(0f, centre, 0f) + normal * radius);
                }
            }

            for (var ring = 0; ring < rings - 1; ring++)
            {
                for (var segment = 0; segment < segments; segment++)
                {
                    var a = ring * segments + segment;
                    var b = ring * segments + (segment + 1) % segments;
                    var c = a + segments;
                    var d = b + segments;
                    triangles.Add(a);
                    triangles.Add(c);
                    triangles.Add(b);
                    triangles.Add(b);
                    triangles.Add(c);
                    triangles.Add(d);
                }
            }

            var mesh = new Mesh { name = "Sword Blade" };
            mesh.SetVertices(vertices);
            mesh.SetNormals(normals);
            mesh.SetTriangles(triangles, 0);
            mesh.RecalculateBounds();
            return mesh;
        }

        /// <summary>
        /// One-shot additive sparks at a world position: streaking stretched-billboard sparks plus an optional soft flash,
        /// destroyed when done.
        /// </summary>
        private void Sparks(Vector3 position, Color color, int count, float speed, float size, float lifetime, float flashSize)
        {
            if (sparkMaterial == null)
                return;

            var root = new GameObject("Sword Sparks");
            root.transform.position = position;

            var sparks = CreateBurst("Sparks", root.transform, count, lifetime);
            var main = sparks.main;
            main.startLifetime = new ParticleSystem.MinMaxCurve(lifetime * 0.4f, lifetime);
            main.startSpeed = new ParticleSystem.MinMaxCurve(speed * 0.3f, speed);
            main.startSize = new ParticleSystem.MinMaxCurve(size * 0.6f, size);
            main.startColor = new ParticleSystem.MinMaxGradient(Color.white, color);
            main.gravityModifier = 0.5f;
            var shape = sparks.shape;
            shape.enabled = true;
            shape.shapeType = ParticleSystemShapeType.Sphere;
            shape.radius = 0.01f;
            var sparkRenderer = sparks.GetComponent<ParticleSystemRenderer>();
            sparkRenderer.renderMode = ParticleSystemRenderMode.Stretch;
            sparkRenderer.velocityScale = 0.04f;
            sparkRenderer.lengthScale = 1f;
            sparks.Play();

            if (flashSize > 0f)
            {
                var flash = CreateBurst("Flash", root.transform, 1, 0.1f);
                var flashMain = flash.main;
                flashMain.startLifetime = 0.1f;
                flashMain.startSpeed = 0f;
                flashMain.startSize = flashSize;
                flashMain.startColor = Color.Lerp(color, Color.white, 0.5f);
                var flashShape = flash.shape;
                flashShape.enabled = false;
                var flashSizeOverLifetime = flash.sizeOverLifetime;
                flashSizeOverLifetime.size = new ParticleSystem.MinMaxCurve(1f, AnimationCurve.Linear(0f, 0.6f, 1f, 1.2f));
                flash.GetComponent<ParticleSystemRenderer>().renderMode = ParticleSystemRenderMode.Billboard;
                flash.Play();
            }

            Destroy(root, lifetime + 0.1f);
        }

        private ParticleSystem CreateBurst(string objectName, Transform parent, int count, float duration)
        {
            var go = new GameObject(objectName);
            go.transform.SetParent(parent, false);
            var particles = go.AddComponent<ParticleSystem>();
            particles.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);

            var main = particles.main;
            main.playOnAwake = false;
            main.loop = false;
            main.duration = duration;
            main.simulationSpace = ParticleSystemSimulationSpace.World;
            main.maxParticles = count;

            var emission = particles.emission;
            emission.rateOverTime = 0f;
            emission.SetBursts(new[] { new ParticleSystem.Burst(0f, (short)count) });

            var fade = new Gradient();
            fade.SetKeys(
                new[] { new GradientColorKey(Color.white, 0f), new GradientColorKey(Color.white, 1f) },
                new[] { new GradientAlphaKey(1f, 0f), new GradientAlphaKey(1f, 0.4f), new GradientAlphaKey(0f, 1f) });
            var colorOverLifetime = particles.colorOverLifetime;
            colorOverLifetime.enabled = true;
            colorOverLifetime.color = fade;

            var sizeOverLifetime = particles.sizeOverLifetime;
            sizeOverLifetime.enabled = true;
            sizeOverLifetime.size = new ParticleSystem.MinMaxCurve(1f, AnimationCurve.Linear(0f, 1f, 1f, 0.3f));

            var particleRenderer = go.GetComponent<ParticleSystemRenderer>();
            particleRenderer.sharedMaterial = sparkMaterial;
            particleRenderer.shadowCastingMode = ShadowCastingMode.Off;
            particleRenderer.receiveShadows = false;
            return particles;
        }

        /// <summary>
        /// The swing trail: a ribbon swept between the inner edge and the tip of recent blade samples, smoothed with
        /// Catmull-Rom between samples. Vertex uv.x = age (0 new .. 1 old), uv.y = 0 inner .. 1 tip, vertex alpha = strength
        /// (see the SpellGame/Sword/Trail shader).
        /// </summary>
        private sealed class SweptTrail
        {
            private struct Sample
            {
                public Vector3 Inner;
                public Vector3 Outer;
                public float Time;
                public float Strength;
            }

            private readonly Transform _transform;
            private readonly Mesh _mesh;
            private readonly List<Sample> _samples = new();
            private readonly List<Vector3> _vertices = new();
            private readonly List<Vector2> _uvs = new();
            private readonly List<Color> _colors = new();
            private readonly List<int> _triangles = new();

            public SweptTrail(Transform holder)
            {
                _transform = holder;
                _mesh = new Mesh { name = "Sword Trail" };
                _mesh.MarkDynamic();
                holder.GetComponent<MeshFilter>().sharedMesh = _mesh;
            }

            public void Add(Vector3 inner, Vector3 outer, float time, float strength) =>
                _samples.Add(new Sample { Inner = inner, Outer = outer, Time = time, Strength = strength });

            public void Clear()
            {
                _samples.Clear();
                _mesh.Clear();
            }

            public void Rebuild(float lifetime, int subdivisions)
            {
                var now = Time.time;
                var expired = 0;
                while (expired < _samples.Count && now - _samples[expired].Time > lifetime)
                    expired++;
                _samples.RemoveRange(0, expired);

                var anyStrength = false;
                foreach (var sample in _samples)
                    anyStrength |= sample.Strength > 0f;
                if (_samples.Count < 2 || !anyStrength)
                {
                    if (_mesh.vertexCount > 0)
                        _mesh.Clear();
                    return;
                }

                _vertices.Clear();
                _uvs.Clear();
                _colors.Clear();
                _triangles.Clear();
                for (var i = 0; i < _samples.Count - 1; i++)
                {
                    var p0 = _samples[Mathf.Max(i - 1, 0)];
                    var p1 = _samples[i];
                    var p2 = _samples[i + 1];
                    var p3 = _samples[Mathf.Min(i + 2, _samples.Count - 1)];
                    for (var step = 0; step < subdivisions; step++)
                    {
                        var t = step / (float)subdivisions;
                        AddPoint(
                            CatmullRom(p0.Inner, p1.Inner, p2.Inner, p3.Inner, t),
                            CatmullRom(p0.Outer, p1.Outer, p2.Outer, p3.Outer, t),
                            Mathf.Lerp(p1.Time, p2.Time, t),
                            Mathf.Lerp(p1.Strength, p2.Strength, t),
                            now, lifetime);
                    }
                }

                var last = _samples[_samples.Count - 1];
                AddPoint(last.Inner, last.Outer, last.Time, last.Strength, now, lifetime);

                for (var point = 0; point < _vertices.Count / 2 - 1; point++)
                {
                    var inner = point * 2;
                    _triangles.Add(inner);
                    _triangles.Add(inner + 1);
                    _triangles.Add(inner + 2);
                    _triangles.Add(inner + 2);
                    _triangles.Add(inner + 1);
                    _triangles.Add(inner + 3);
                }

                _mesh.Clear();
                _mesh.SetVertices(_vertices);
                _mesh.SetUVs(0, _uvs);
                _mesh.SetColors(_colors);
                _mesh.SetTriangles(_triangles, 0);
            }

            private void AddPoint(Vector3 inner, Vector3 outer, float time, float strength, float now, float lifetime)
            {
                var age = Mathf.Clamp01((now - time) / lifetime);
                var color = new Color(1f, 1f, 1f, strength);
                _vertices.Add(_transform.InverseTransformPoint(inner));
                _vertices.Add(_transform.InverseTransformPoint(outer));
                _uvs.Add(new Vector2(age, 0f));
                _uvs.Add(new Vector2(age, 1f));
                _colors.Add(color);
                _colors.Add(color);
            }

            private static Vector3 CatmullRom(Vector3 p0, Vector3 p1, Vector3 p2, Vector3 p3, float t)
            {
                var t2 = t * t;
                var t3 = t2 * t;
                return 0.5f * (2f * p1 + (p2 - p0) * t + (2f * p0 - 5f * p1 + 4f * p2 - p3) * t2 + (3f * p1 - p0 - 3f * p2 + p3) * t3);
            }
        }
    }
}
