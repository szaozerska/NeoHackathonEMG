using System.Collections.Generic;
using SpellGame.Protocol;
using UnityEngine;

namespace SpellGame.Game
{
    /// <summary>
    /// Renders shields from server events and state (game_plan.md stage 1c):
    /// <list type="bullet">
    /// <item>while <c>item == "shield"</c>, a disc sits in front of the band hand, facing away from the chest through
    /// the hand, the same disc the server hit-tests;</item>
    /// <item>the disc swells with <c>shield_boost</c> (push impulse);</item>
    /// <item><c>impact blocked</c> on a shield flashes sparks, <c>impact parried</c> flashes a bigger burst.</item>
    /// </list>
    /// The local player's shield follows local hand tracking.
    /// </summary>
    public sealed class ShieldView : MonoBehaviour
    {
        [SerializeField] private GameClient gameClient;
        [SerializeField] private Material shieldMaterial;
        [SerializeField] private Material sparkMaterial;

        [Header("Must match the server's Tuning")]
        [Tooltip("Tuning.shield_radius")]
        [SerializeField] private float shieldRadius = 0.3f;
        [Tooltip("Tuning.shield_offset")]
        [SerializeField] private float shieldOffset = 0.08f;

        [Header("Look")]
        [SerializeField] private float thickness = 0.015f;
        [Tooltip("Extra size at full boost.")]
        [SerializeField] private float boostSwell = 0.2f;

        private readonly Dictionary<string, PlayerSnapshot> _players = new();
        private readonly Dictionary<string, Transform> _discs = new();

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
            if (spell.Spell != SpellKind.Shield)
                return;

            Vector3? at = TryGetDisc(spell.CasterId, out var center, out _) ? center : ToVector(spell.Origin);
            if (spell.State == SpellState.Sheathed && _players.TryGetValue(spell.CasterId, out var player))
                player.Item = "none";
            if (at != null)
                SpellVfx.Burst(at.Value, shieldMaterial, count: 12, speed: 0.6f, size: 0.02f, lifetime: 0.25f);
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

            if (impact.Reason == ImpactReason.Blocked)
            {
                SpellVfx.Burst(impact.Position, sparkMaterial, count: 25, speed: 2f, size: 0.02f, lifetime: 0.3f);
                SpellVfx.Burst(impact.Position, shieldMaterial, count: 10, speed: 1f, size: 0.03f, lifetime: 0.25f);
            }
            else if (impact.Reason == ImpactReason.Parried)
            {
                SpellVfx.Burst(impact.Position, sparkMaterial, count: 60, speed: 4f, size: 0.03f, lifetime: 0.45f);
                SpellVfx.Burst(impact.Position, shieldMaterial, count: 30, speed: 2.5f, size: 0.04f, lifetime: 0.4f);
            }
        }

        private void Update()
        {
            foreach (var (playerId, player) in _players)
            {
                var disc = DiscFor(playerId);
                var center = Vector3.zero;
                var normal = Vector3.up;
                var raised = player.Item == SpellKind.Shield && TryGetDisc(playerId, out center, out normal);
                disc.gameObject.SetActive(raised);
                if (!raised)
                    continue;

                var diameter = 2f * shieldRadius * (1f + boostSwell * Mathf.Clamp01(player.ShieldBoost));
                disc.position = center;
                disc.rotation = Quaternion.FromToRotation(Vector3.up, normal);
                disc.localScale = new Vector3(diameter, thickness, diameter);
            }

            foreach (var (playerId, disc) in _discs)
            {
                if (!_players.ContainsKey(playerId))
                    disc.gameObject.SetActive(false);
            }
        }

        private Transform DiscFor(string playerId)
        {
            if (_discs.TryGetValue(playerId, out var disc))
                return disc;

            disc = SpellVfx.CreateOrb($"Shield {playerId}", transform, shieldMaterial, 1f);
            disc.gameObject.SetActive(false);
            _discs[playerId] = disc;
            return disc;
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

        private static Vector3? ToVector(float[] values) =>
            values is { Length: 3 } ? new Vector3(values[0], values[1], values[2]) : null;
    }
}
