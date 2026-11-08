using System.Collections.Generic;
using SpellGame.Protocol;
using UnityEngine;
using UnityEngine.Rendering;

namespace SpellGame.Game
{
    /// <summary>
    /// Plays the server's <c>domain_expansion</c> (Infinite Void) on every headset: the world turns white, purple, pink
    /// and red streaks race from the caster to each target while an inky black void expands from the caster behind them,
    /// the streaks die out, the void fills the world, and each target's own view goes white while they are stunned.
    /// <para>
    /// The white world and the void are drawn first and write no depth, so the remote bodies, the AI and the streaks stay
    /// visible on top of them; the white-out is drawn over everything.
    /// </para>
    /// </summary>
    public sealed class InfiniteVoidView : MonoBehaviour
    {
        [SerializeField] private GameClient gameClient;
        [SerializeField] private Transform centerEye;
        [Tooltip("A material on SpellGame/InfiniteVoid/Void; copied and tinted per layer.")]
        [SerializeField] private Material voidMaterial;

        [Header("Timing (seconds)")]
        [SerializeField] private float whiteInSeconds = 0.4f;
        [SerializeField] private float engulfSeconds = 0.6f;
        [SerializeField] private float whiteoutInSeconds = 0.25f;
        [SerializeField] private float fadeOutSeconds = 0.5f;

        [Header("Streaks")]
        [SerializeField, Min(1)] private int streaksPerTarget = 14;
        [SerializeField] private float streakWidth = 0.05f;
        [SerializeField] private float streakTrailSeconds = 0.35f;
        [SerializeField] private float streakSpread = 0.3f;
        [SerializeField] private float streakMaxBow = 0.6f;
        [Tooltip("The void's edge trails this share of the way behind the streaks.")]
        [SerializeField, Range(0f, 1f)] private float voidLag = 0.1f;

        [Header("Size (metres)")]
        [SerializeField] private float worldRadius = 20f;
        [SerializeField] private float filledVoidRadius = 30f;
        [SerializeField] private float whiteoutRadius = 0.3f;

        private static readonly int ColorId = Shader.PropertyToID("_Color");
        private static readonly Color[] StreakColors =
        {
            new(0.62f, 0.2f, 1f),
            new(1f, 0.35f, 0.75f),
            new(1f, 0.12f, 0.2f),
        };

        private const int WorldQueue = (int)RenderQueue.Background;
        private const int VoidQueue = (int)RenderQueue.Background + 1;
        private const int StreakQueue = (int)RenderQueue.Transparent;
        private const int WhiteoutQueue = (int)RenderQueue.Overlay;

        private Material _worldMaterial;
        private Material _voidMaterial;
        private Material _whiteoutMaterial;
        private Material[] _streakMaterials;
        private Transform _world;
        private Transform _void;
        private Transform _whiteout;
        private Domain _domain;

        private sealed class Streak
        {
            public Transform Head;
            public MeshRenderer HeadRenderer;
            public string TargetId;
            public Vector3 Start;
            public Vector3 Bow;

            /// <summary>Share of the travel time this streak needs; below 1 it lands early.</summary>
            public float Pace;
        }

        private sealed class Domain
        {
            public DomainExpansionMessage Message;
            public float StartTime;
            public Vector3 Origin;
            public readonly Dictionary<string, Vector3> TargetPositions = new();
            public readonly List<Streak> Streaks = new();
            public Transform StreakRoot;

            public float End => Message.ExpandS + Message.StunS;
        }

        private void Awake()
        {
            _worldMaterial = Layer(Color.white, WorldQueue, CompareFunction.Always);
            _voidMaterial = Layer(Color.black, VoidQueue, CompareFunction.Always);
            _whiteoutMaterial = Layer(Color.white, WhiteoutQueue, CompareFunction.Always);
            _streakMaterials = new Material[StreakColors.Length];
            for (var i = 0; i < StreakColors.Length; i++)
                _streakMaterials[i] = Layer(StreakColors[i], StreakQueue, CompareFunction.LessEqual);

            _world = SpellVfx.CreateOrb("Infinite Void World", transform, _worldMaterial, worldRadius * 2f);
            _void = SpellVfx.CreateOrb("Infinite Void", transform, _voidMaterial, 1f);
            _whiteout = SpellVfx.CreateOrb("Infinite Void Whiteout", transform, _whiteoutMaterial, whiteoutRadius * 2f);
            ShowLayers(false, false);
        }

        private void OnEnable() => gameClient.DomainExpansionReceived += OnDomainExpansion;

        private void OnDisable() => gameClient.DomainExpansionReceived -= OnDomainExpansion;

        private void OnDestroy()
        {
            Destroy(_worldMaterial);
            Destroy(_voidMaterial);
            Destroy(_whiteoutMaterial);
            foreach (var material in _streakMaterials)
                Destroy(material);
        }

        private Material Layer(Color color, int queue, CompareFunction depthTest)
        {
            var material = new Material(voidMaterial) { renderQueue = queue };
            material.SetColor(ColorId, color);
            material.SetFloat("_ZTest", (float)depthTest);
            return material;
        }

        private void OnDomainExpansion(DomainExpansionMessage message)
        {
            if (!TryGetChest(message.CasterId, out var origin))
            {
                Debug.LogWarning($"[InfiniteVoidView] No pose for caster {message.CasterId}; not showing their domain.");
                return;
            }

            EndDomain();
            _domain = new Domain { Message = message, StartTime = Time.time, Origin = origin };
            _domain.StreakRoot = new GameObject("Infinite Void Streaks").transform;
            _domain.StreakRoot.SetParent(transform, false);
            foreach (var targetId in message.TargetIds)
            {
                if (!TryGetChest(targetId, out var target))
                    continue;
                _domain.TargetPositions[targetId] = target;
                for (var i = 0; i < streaksPerTarget; i++)
                    _domain.Streaks.Add(CreateStreak(targetId, origin, target, i));
            }

            _void.position = origin;
            ShowLayers(true, message.TargetIds.Contains(gameClient.PlayerId));
        }

        private Streak CreateStreak(string targetId, Vector3 origin, Vector3 target, int index)
        {
            var material = _streakMaterials[index % _streakMaterials.Length];
            var head = SpellVfx.CreateOrb("Streak", _domain.StreakRoot, material, streakWidth);
            var start = origin + Random.insideUnitSphere * streakSpread;
            head.position = start;
            SpellVfx.AddTrail(head, material, streakWidth, streakTrailSeconds);
            var bow = Vector3.ProjectOnPlane(Random.onUnitSphere, target - origin).normalized * Random.Range(0f, streakMaxBow);
            return new Streak { Head = head, HeadRenderer = head.GetComponent<MeshRenderer>(), TargetId = targetId, Start = start, Bow = bow, Pace = Random.Range(0.8f, 1f) };
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

            var travel = TravelProgress(elapsed);
            UpdateTargetPositions();
            UpdateStreaks(travel);
            _void.localScale = Vector3.one * (2f * VoidRadius(elapsed, travel));
        }

        /// <summary>0 when the world has turned white, 1 when the streaks land; eased in so they accelerate.</summary>
        private float TravelProgress(float elapsed)
        {
            var linear = Mathf.Clamp01((elapsed - whiteInSeconds) / (_domain.Message.ExpandS - whiteInSeconds));
            return linear * linear;
        }

        private float VoidRadius(float elapsed, float travel)
        {
            var reach = 0f;
            foreach (var target in _domain.TargetPositions.Values)
                reach = Mathf.Max(reach, Vector3.Distance(_domain.Origin, target));

            var landed = elapsed - _domain.Message.ExpandS;
            if (landed < 0f)
                return reach * travel * (1f - voidLag);
            return Mathf.Lerp(reach * (1f - voidLag), filledVoidRadius, Mathf.Clamp01(landed / engulfSeconds));
        }

        private void UpdateTargetPositions()
        {
            foreach (var targetId in _domain.Message.TargetIds)
            {
                if (_domain.TargetPositions.ContainsKey(targetId) && TryGetChest(targetId, out var chest))
                    _domain.TargetPositions[targetId] = chest;
            }
        }

        /// <summary>Heads fly a bowed path to the target's chest and vanish there; their trails then shrink away.</summary>
        private void UpdateStreaks(float travel)
        {
            foreach (var streak in _domain.Streaks)
            {
                if (!streak.HeadRenderer.enabled)
                    continue;
                var progress = Mathf.Clamp01(travel / streak.Pace);
                var target = _domain.TargetPositions[streak.TargetId];
                streak.Head.position = Vector3.Lerp(streak.Start, target, progress) + streak.Bow * Mathf.Sin(progress * Mathf.PI);
                streak.HeadRenderer.enabled = progress < 1f;
            }
        }

        private void EndDomain()
        {
            if (_domain == null)
                return;

            Destroy(_domain.StreakRoot.gameObject);
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
