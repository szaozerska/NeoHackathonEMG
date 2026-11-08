using System.Collections.Generic;
using SpellGame.Protocol;
using UnityEngine;

namespace SpellGame.Game
{
    /// <summary>
    /// Renders fireballs from server events and state (architecture.md §9). The snap and the throw look different:
    /// <list type="bullet">
    /// <item>snap (<c>spell charging</c>): a flash and spark burst, then a burning orb held on the caster's band hand;</item>
    /// <item>throw (<c>spell cast</c>): the orb leaves the hand as a projectile with a flame, smoke and glow trail;</item>
    /// <item><c>impact hit</c> explodes, <c>impact blocked</c> explodes smaller, <c>impact expired</c> and a fizzled
    /// hold (<c>spell cancelled</c>) puff out in smoke;</item>
    /// <item>while on cooldown, a small ember sits on the hand and shrinks until the next snap is allowed.</item>
    /// </list>
    /// The local player's held orb follows local hand tracking, so it never lags behind the real hand.
    /// The effects themselves are built by <see cref="FireballVfx"/>.
    /// </summary>
    public sealed class FireballView : MonoBehaviour
    {
        [SerializeField] private GameClient gameClient;
        [SerializeField] private FireballMaterials materials = new();

        [Header("Look")]
        [SerializeField] private float heldDiameter = 0.12f;
        [Tooltip("Seconds of holding until the held orb looks fully charged (visual only; damage doesn't change).")]
        [SerializeField] private float chargeSeconds = 1.5f;
        [Tooltip("Server Tuning.fireball_radius is 0.1, so 0.2 shows the true hit size.")]
        [SerializeField] private float projectileDiameter = 0.2f;
        [SerializeField] private float emberDiameter = 0.04f;
        [Tooltip("Size multiplier of the hit explosion; a shield block shows a smaller one.")]
        [SerializeField] private float explosionScale = 1f;
        [Tooltip("Server Tuning.fireball_cooldown_s, used to scale the ember.")]
        [SerializeField] private float fullCooldown = 0.75f;
        [Tooltip("How fast a projectile's drawn position converges onto the server's extrapolated position (1/s).")]
        [SerializeField] private float projectileCorrectionRate = 25f;

        private sealed class HandVisuals
        {
            public FireballOrb HeldOrb;
            public Transform Ember;
            public float HeldSince;
            public bool WasHolding;
        }

        private sealed class ProjectileVisual
        {
            public FireballOrb Orb;
            public Vector3 ServerPosition;
            public Vector3 ServerVelocity;
            public float ReceivedAt;
        }

        private readonly Dictionary<string, PlayerSnapshot> _players = new();
        private readonly Dictionary<string, HandVisuals> _hands = new();
        private readonly Dictionary<int, ProjectileVisual> _projectiles = new();
        private readonly HashSet<int> _seenProjectiles = new();

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
            if (spell.Spell != SpellKind.Fireball)
                return;

            var at = HandPosition(spell.CasterId) ?? ToVector(spell.Origin);
            if (at == null)
                return;

            switch (spell.State)
            {
                case SpellState.Charging:
                    FireballVfx.Ignite(at.Value, materials);
                    break;
                case SpellState.Cast:
                    FireballVfx.Launch(at.Value, materials);
                    break;
                case SpellState.Cancelled:
                    FireballVfx.Fizzle(at.Value, materials, scale: 0.7f);
                    break;
            }
        }

        private void OnState(StateMessage state)
        {
            _players.Clear();
            foreach (var player in state.Players)
                _players[player.PlayerId] = player;

            var live = new HashSet<int>();
            foreach (var snapshot in state.Projectiles)
            {
                if (snapshot.Kind != SpellKind.Fireball)
                    continue;

                live.Add(snapshot.Id);
                if (!_projectiles.TryGetValue(snapshot.Id, out var visual))
                {
                    if (!_seenProjectiles.Add(snapshot.Id))
                        continue;
                    visual = CreateProjectile(snapshot);
                    _projectiles[snapshot.Id] = visual;
                }

                visual.ServerPosition = snapshot.Position;
                visual.ServerVelocity = snapshot.Velocity;
                visual.ReceivedAt = Time.time;
            }

            foreach (var id in new List<int>(_projectiles.Keys))
            {
                if (!live.Contains(id))
                    RemoveProjectile(id);
            }
        }

        private void OnImpact(ImpactMessage impact)
        {
            if (impact.Kind != SpellKind.Fireball)
                return;

            var at = _projectiles.TryGetValue(impact.ProjectileId, out var visual) ? visual.Orb.Root.position : impact.Position;
            RemoveProjectile(impact.ProjectileId);
            _seenProjectiles.Add(impact.ProjectileId);

            switch (impact.Reason)
            {
                case ImpactReason.Hit:
                    FireballVfx.Explosion(at, materials, explosionScale);
                    break;
                case ImpactReason.Blocked:
                    FireballVfx.Explosion(at, materials, explosionScale * 0.6f);
                    break;
                default:
                    FireballVfx.Fizzle(at, materials, scale: 1f);
                    break;
            }
        }

        private void Update()
        {
            UpdateHands();
            UpdateProjectiles();
        }

        private void UpdateHands()
        {
            foreach (var (playerId, player) in _players)
            {
                var hand = HandFor(playerId);
                var position = HandPosition(playerId);
                var holding = player.Item == SpellKind.Fireball && position != null;
                var cooling = !holding && player.Cooldown > 0f && position != null;

                if (holding && !hand.WasHolding)
                    hand.HeldSince = Time.time;
                hand.WasHolding = holding;
                hand.HeldOrb.Root.gameObject.SetActive(holding);
                hand.Ember.gameObject.SetActive(cooling);

                if (holding)
                {
                    hand.HeldOrb.Root.position = position.Value;
                    // Charging up: the orb grows from 75% to 125% and pulses harder and faster the longer it's held.
                    var charge = Mathf.Clamp01((Time.time - hand.HeldSince) / chargeSeconds);
                    var pulse = 1f + (0.04f + 0.08f * charge) * Mathf.Sin(Time.time * (12f + 14f * charge));
                    hand.HeldOrb.Core.localScale = Vector3.one * (heldDiameter * (0.75f + 0.5f * charge) * pulse);
                }
                else if (cooling)
                {
                    hand.Ember.position = position.Value;
                    // The ember's glow scales with it; never quite zero, so the particle system's scale stays valid.
                    var left = Mathf.Max(0.05f, Mathf.Clamp01(player.Cooldown / fullCooldown));
                    hand.Ember.localScale = Vector3.one * (emberDiameter * left);
                }
            }

            foreach (var (playerId, hand) in _hands)
            {
                if (_players.ContainsKey(playerId))
                    continue;
                hand.HeldOrb.Root.gameObject.SetActive(false);
                hand.Ember.gameObject.SetActive(false);
            }
        }

        private void UpdateProjectiles()
        {
            var blend = 1f - Mathf.Exp(-projectileCorrectionRate * Time.deltaTime);
            foreach (var visual in _projectiles.Values)
            {
                var predicted = visual.ServerPosition + visual.ServerVelocity * (Time.time - visual.ReceivedAt);
                var root = visual.Orb.Root;
                var drifted = root.position + visual.ServerVelocity * Time.deltaTime;
                root.position = Vector3.Lerp(drifted, predicted, blend);
            }
        }

        private ProjectileVisual CreateProjectile(ProjectileSnapshot snapshot)
        {
            var orb = FireballVfx.CreateProjectile($"Fireball {snapshot.Id}", transform, materials, projectileDiameter, snapshot.Position);
            return new ProjectileVisual { Orb = orb };
        }

        private void RemoveProjectile(int id)
        {
            if (!_projectiles.Remove(id, out var visual))
                return;
            FireballVfx.Release(visual.Orb);
        }

        private HandVisuals HandFor(string playerId)
        {
            if (_hands.TryGetValue(playerId, out var hand))
                return hand;

            hand = new HandVisuals
            {
                HeldOrb = FireballVfx.CreateHeldOrb($"Held Fireball {playerId}", transform, materials, heldDiameter),
                Ember = FireballVfx.CreateEmber($"Ember {playerId}", transform, materials),
            };
            _hands[playerId] = hand;
            return hand;
        }

        private Vector3? HandPosition(string playerId)
        {
            if (!gameClient.TryGetJoints(playerId, out var joints))
                return null;

            var bandHand = _players.TryGetValue(playerId, out var player) ? player.BandHand : HandSide.Right;
            var palm = bandHand == HandSide.Left ? joints.LHand : joints.RHand;
            return palm?.Position;
        }

        private static Vector3? ToVector(float[] values) =>
            values is { Length: 3 } ? new Vector3(values[0], values[1], values[2]) : null;
    }
}
