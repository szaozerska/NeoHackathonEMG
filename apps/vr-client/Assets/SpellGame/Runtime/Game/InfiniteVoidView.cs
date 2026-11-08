using System.Collections.Generic;
using SpellGame.Protocol;
using UnityEngine;
using UnityEngine.Rendering;

namespace SpellGame.Game
{
    /// <summary>
    /// Plays the server's <c>domain_expansion</c> (Infinite Void) on every headset: the world turns white, hundreds of thin
    /// straight purple, pink, red and white streaks race from the caster to each target like a jump to warp speed while an
    /// inky, starry void expands from the caster behind them, the streaks die out, the void fills the world, and each
    /// target's own view goes white while they are stunned.
    /// <para>
    /// The white world and the void are drawn first and write no depth, so the remote bodies, the AI and the streaks stay
    /// visible on top of them; the white-out is drawn over everything.
    /// </para>
    /// </summary>
    public sealed class InfiniteVoidView : MonoBehaviour
    {
        [SerializeField] private GameClient gameClient;
        [SerializeField] private Transform centerEye;
        [Tooltip("A material on SpellGame/InfiniteVoid/Void; copied for the white world and the white-out.")]
        [SerializeField] private Material flatMaterial;
        [Tooltip("A material on SpellGame/InfiniteVoid/Ink: the starry black void.")]
        [SerializeField] private Material inkMaterial;
        [Tooltip("A material on SpellGame/InfiniteVoid/Streak, coloured per particle.")]
        [SerializeField] private Material streakMaterial;

        [Header("Timing (seconds)")]
        [SerializeField] private float whiteInSeconds = 0.4f;
        [Tooltip("The black void starts growing from the caster this long after the cast; until then the world is white.")]
        [SerializeField] private float voidStartSeconds = 0.9f;
        [Tooltip("The black void reaches the targets this long after the cast, then fills the world.")]
        [SerializeField] private float voidReachSeconds = 3f;
        [SerializeField] private float engulfSeconds = 0.6f;
        [SerializeField] private float whiteoutInSeconds = 0.25f;
        [SerializeField] private float fadeOutSeconds = 0.5f;

        [Header("Streaks")]
        [SerializeField, Min(1f)] private float streaksPerSecond = 2400f;
        [SerializeField] private float streakDelaySeconds = 1.6f;
        [Tooltip("Streaks keep coming until this long after the server's expand time (when the stun's white-out starts).")]
        [SerializeField] private float streakTailSeconds = 0.4f;
        [Tooltip("Streaks start between these distances from the line between caster and target: far enough to keep clear " +
                 "of the players' heads, wide enough to fill the view.")]
        [SerializeField] private float tunnelInnerRadius = 1.5f;
        [SerializeField] private float tunnelRadius = 7.5f;
        [SerializeField] private Vector2 streakSpeed = new(54f, 90f);
        [SerializeField] private Vector2 streakWidth = new(0.012f, 0.036f);
        [Tooltip("Streaks fill the line from this far behind the caster to this far past the target, into the vanishing point.")]
        [SerializeField] private float streakFarDistance = 60f;
        [Tooltip("Rendered length per m/s of speed.")]
        [SerializeField] private float streakStretch = 0.27f;
        [SerializeField, Range(0f, 1f)] private float whiteStreakShare = 0.35f;

        [Header("Size (metres)")]
        [SerializeField] private float worldRadius = 20f;
        [SerializeField] private float filledVoidRadius = 30f;
        [SerializeField] private float whiteoutRadius = 0.3f;

        private static readonly int ColorId = Shader.PropertyToID("_Color");
        private static readonly Color[] StreakColors =
        {
            new(0.85f, 0.55f, 1f),
            new(1f, 0.6f, 0.95f),
            new(1f, 0.4f, 0.45f),
        };

        private const int WorldQueue = (int)RenderQueue.Background;
        private const int VoidQueue = (int)RenderQueue.Background + 1;
        private const int WhiteoutQueue = (int)RenderQueue.Overlay;

        private Material _worldMaterial;
        private Material _voidMaterial;
        private Material _whiteoutMaterial;
        private Transform _world;
        private Transform _void;
        private Transform _whiteout;
        private ParticleSystem _streaks;
        private float _streakDebt;
        private Domain _domain;

        private sealed class Domain
        {
            public DomainExpansionMessage Message;
            public float StartTime;
            public Vector3 Origin;

            /// <summary>Where each target was at the cast; the streaks and the void aim there even if the target moves.</summary>
            public readonly Dictionary<string, Vector3> TargetPositions = new();


            public float End => Message.ExpandS + Message.StunS;
        }

        private void Awake()
        {
            _worldMaterial = Layer(flatMaterial, WorldQueue);
            _voidMaterial = Layer(inkMaterial, VoidQueue);
            _whiteoutMaterial = Layer(flatMaterial, WhiteoutQueue);

            _world = SpellVfx.CreateOrb("Infinite Void World", transform, _worldMaterial, worldRadius * 2f);
            _void = SpellVfx.CreateOrb("Infinite Void", transform, _voidMaterial, 1f);
            _whiteout = SpellVfx.CreateOrb("Infinite Void Whiteout", transform, _whiteoutMaterial, whiteoutRadius * 2f);
            _streaks = CreateStreaks();
            ShowLayers(false, false);
        }

        private void OnEnable() => gameClient.DomainExpansionReceived += OnDomainExpansion;

        private void OnDisable() => gameClient.DomainExpansionReceived -= OnDomainExpansion;

        private void OnDestroy()
        {
            Destroy(_worldMaterial);
            Destroy(_voidMaterial);
            Destroy(_whiteoutMaterial);
        }

        /// <summary>A copy of <paramref name="source"/> drawn at <paramref name="queue"/> over whatever is already there.</summary>
        private static Material Layer(Material source, int queue)
        {
            var material = new Material(source) { renderQueue = queue };
            material.SetFloat("_ZTest", (float)CompareFunction.Always);
            return material;
        }

        /// <summary>One particle system for every streak: thin billboards stretched along their velocity.</summary>
        private ParticleSystem CreateStreaks()
        {
            var go = new GameObject("Infinite Void Streaks");
            go.transform.SetParent(transform, false);
            var particles = go.AddComponent<ParticleSystem>();
            particles.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);

            var main = particles.main;
            main.playOnAwake = false;
            main.loop = true;
            main.simulationSpace = ParticleSystemSimulationSpace.World;
            main.maxParticles = 20000;
            var emission = particles.emission;
            emission.enabled = false;
            var shape = particles.shape;
            shape.enabled = false;
            var colorOverLifetime = particles.colorOverLifetime;
            colorOverLifetime.enabled = true;
            var fadeOut = new Gradient();
            fadeOut.SetKeys(
                new[] { new GradientColorKey(Color.white, 0f), new GradientColorKey(Color.white, 1f) },
                new[] { new GradientAlphaKey(0f, 0f), new GradientAlphaKey(1f, 0.1f), new GradientAlphaKey(1f, 0.7f), new GradientAlphaKey(0f, 1f) });
            colorOverLifetime.color = fadeOut;

            var renderer = go.GetComponent<ParticleSystemRenderer>();
            renderer.renderMode = ParticleSystemRenderMode.Stretch;
            renderer.velocityScale = streakStretch;
            renderer.lengthScale = 1f;
            renderer.sharedMaterial = streakMaterial;
            renderer.shadowCastingMode = ShadowCastingMode.Off;
            renderer.receiveShadows = false;
            particles.Play();
            return particles;
        }

        private void OnDomainExpansion(DomainExpansionMessage message)
        {
            if (!TryGetChest(message.CasterId, out var origin))
            {
                Debug.LogWarning($"[InfiniteVoidView] No pose for caster {message.CasterId}; not showing their domain.");
                return;
            }

            EndDomain();
            _domain = new Domain
            {
                Message = message,
                StartTime = Time.time,
                Origin = origin,
            };
            foreach (var targetId in message.TargetIds)
            {
                if (TryGetChest(targetId, out var target))
                    _domain.TargetPositions[targetId] = target;
            }

            _void.position = origin;
            ShowLayers(true, message.TargetIds.Contains(gameClient.PlayerId));
        }

        private void Update()
        {
            if (_domain == null)
                return;

            var elapsed = Time.time - _domain.StartTime;
            if (elapsed >= _domain.End + fadeOutSeconds)
            {
                EndDomain();
                return;
            }

            var fade = 1f - Mathf.Clamp01((elapsed - _domain.End) / fadeOutSeconds);
            var eye = centerEye.position;
            _world.position = eye;
            _whiteout.position = eye;
            SetAlpha(_worldMaterial, Mathf.Clamp01(elapsed / whiteInSeconds) * fade);
            SetAlpha(_voidMaterial, fade);
            SetAlpha(_whiteoutMaterial, Mathf.Clamp01((elapsed - _domain.Message.ExpandS) / whiteoutInSeconds) * fade);

            EmitStreaks(elapsed);
            _void.localScale = Vector3.one * (2f * VoidRadius(elapsed));
        }

        /// <summary>
        /// Grows from the caster from <see cref="voidStartSeconds"/>, eased in so it accelerates, reaching the farthest target
        /// at <see cref="voidReachSeconds"/>; then fills the world over <see cref="engulfSeconds"/>.
        /// </summary>
        private float VoidRadius(float elapsed)
        {
            var reach = 0f;
            foreach (var target in _domain.TargetPositions.Values)
                reach = Mathf.Max(reach, Vector3.Distance(_domain.Origin, target));

            var landed = elapsed - voidReachSeconds;
            if (landed >= 0f)
                return Mathf.Lerp(reach, filledVoidRadius, Mathf.Clamp01(landed / engulfSeconds));
            var growing = Mathf.Clamp01((elapsed - voidStartSeconds) / (voidReachSeconds - voidStartSeconds));
            return reach * growing * growing;
        }

        /// <summary>
        /// From <see cref="streakDelaySeconds"/> after the cast, straight streaks parallel to the line from caster to target, spread across a ring around it,
        /// fly toward the target the whole way from <see cref="streakFarDistance"/> behind the caster to
        /// <see cref="streakFarDistance"/> past the target, fading in where they appear and out where they end.
        /// </summary>
        private void EmitStreaks(float elapsed)
        {
            var emitting = elapsed >= streakDelaySeconds && elapsed < _domain.Message.ExpandS + streakTailSeconds;
            if (!emitting || _domain.TargetPositions.Count == 0)
                return;

            _streakDebt += streaksPerSecond * Time.deltaTime;
            var count = Mathf.FloorToInt(_streakDebt);
            _streakDebt -= count;
            var targets = new List<Vector3>(_domain.TargetPositions.Values);
            for (var i = 0; i < count; i++)
                EmitStreak(targets[Random.Range(0, targets.Count)]);
        }

        private void EmitStreak(Vector3 target)
        {
            var axis = target - _domain.Origin;
            var distance = axis.magnitude;
            var offset = RandomPerpendicular(axis) * RandomTunnelRadius();
            var direction = axis / distance;
            var end = distance + streakFarDistance;
            var along = Random.Range(-streakFarDistance, end);
            var speed = Random.Range(streakSpeed.x, streakSpeed.y);
            _streaks.Emit(new ParticleSystem.EmitParams
            {
                position = _domain.Origin + offset + direction * along,
                velocity = direction * speed,
                startSize = Random.Range(streakWidth.x, streakWidth.y),
                startLifetime = (end - along) / speed,
                startColor = Random.value < whiteStreakShare ? Color.white : StreakColors[Random.Range(0, StreakColors.Length)],
                applyShapeToPosition = false,
            }, 1);
        }

        /// <summary>Uniform over the ring's area, so the outer streaks aren't sparser than the inner ones.</summary>
        private float RandomTunnelRadius() =>
            Mathf.Sqrt(Mathf.Lerp(tunnelInnerRadius * tunnelInnerRadius, tunnelRadius * tunnelRadius, Random.value));

        private static Vector3 RandomPerpendicular(Vector3 axis)
        {
            var perpendicular = Vector3.ProjectOnPlane(Random.onUnitSphere, axis);
            return perpendicular.normalized;
        }

        private void EndDomain()
        {
            if (_domain == null)
                return;

            _streaks.Clear();
            _streakDebt = 0f;
            _domain = null;
            ShowLayers(false, false);
        }

        private void ShowLayers(bool world, bool whiteout)
        {
            _world.gameObject.SetActive(world);
            _void.gameObject.SetActive(world);
            _whiteout.gameObject.SetActive(whiteout);
            if (!world)
                return;
            SetAlpha(_worldMaterial, 0f);
            SetAlpha(_whiteoutMaterial, 0f);
            _void.localScale = Vector3.zero;
        }

        private static void SetAlpha(Material material, float alpha)
        {
            var color = material.GetColor(ColorId);
            color.a = alpha;
            material.SetColor(ColorId, color);
        }

        private bool TryGetChest(string playerId, out Vector3 chest)
        {
            chest = default;
            if (!gameClient.TryGetJoints(playerId, out var joints))
                return false;
            var joint = joints.Chest ?? joints.Head;
            if (joint == null)
                return false;
            chest = joint.Position;
            return true;
        }
    }
}
