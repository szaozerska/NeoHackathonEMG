using System.Collections.Generic;
using SpellGame.Protocol;
using UnityEngine;

namespace SpellGame.Game
{
    /// <summary>
    /// Renders fireballs from server events and state (architecture.md §9). The snap and the throw look different:
    /// <list type="bullet">
    /// <item>snap (<c>spell charging</c>): a spark burst, then a held orb on the caster's band hand;</item>
    /// <item>throw (<c>spell cast</c>): the orb leaves the hand as a projectile with a trail;</item>
    /// <item><c>impact hit</c> explodes, <c>impact expired</c> and a fizzled hold (<c>spell cancelled</c>) puff out;</item>
    /// <item>while on cooldown, a small ember sits on the hand and shrinks until the next snap is allowed.</item>
    /// </list>
    /// The local player's held orb follows local hand tracking, so it never lags behind the real hand.
    /// </summary>
    public sealed class FireballView : MonoBehaviour
    {
        [SerializeField] private GameClient gameClient;
        [SerializeField] private Material fireMaterial;
        [SerializeField] private Material sparkMaterial;
        [SerializeField] private Material smokeMaterial;

        [Header("Look")]
        [SerializeField] private float heldDiameter = 0.12f;
        [Tooltip("Server Tuning.fireball_radius is 0.15, so 0.3 shows the true hit size.")]
        [SerializeField] private float projectileDiameter = 0.2f;
        [SerializeField] private float emberDiameter = 0.04f;
        [Tooltip("Server Tuning.fireball_cooldown_s, used to scale the ember.")]
        [SerializeField] private float fullCooldown = 0.75f;
        [Tooltip("How fast a projectile's drawn position converges onto the server's extrapolated position (1/s).")]
        [SerializeField] private float projectileCorrectionRate = 25f;

        private sealed class HandVisuals
        {
            public Transform HeldOrb;
            public Transform Ember;
        }

        private sealed class ProjectileVisual
        {
            public Transform Orb;
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
                    SpellVfx.Burst(at.Value, sparkMaterial, count: 24, speed: 1.5f, size: 0.02f, lifetime: 0.35f);
                    SpellVfx.Burst(at.Value, fireMaterial, count: 10, speed: 0.6f, size: 0.04f, lifetime: 0.3f);
                    break;
                case SpellState.Cast:
                    SpellVfx.Burst(at.Value, sparkMaterial, count: 12, speed: 1f, size: 0.02f, lifetime: 0.25f);
                    break;
                case SpellState.Cancelled:
                    SpellVfx.Burst(at.Value, smokeMaterial, count: 16, speed: 0.4f, size: 0.05f, lifetime: 0.8f);
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

            var at = _projectiles.TryGetValue(impact.ProjectileId, out var visual) ? visual.Orb.position : impact.Position;
            RemoveProjectile(impact.ProjectileId);
            _seenProjectiles.Add(impact.ProjectileId);

            if (impact.Reason == ImpactReason.Hit)
            {
                SpellVfx.Burst(at, fireMaterial, count: 40, speed: 2.5f, size: 0.07f, lifetime: 0.5f);
                SpellVfx.Burst(at, sparkMaterial, count: 30, speed: 4f, size: 0.02f, lifetime: 0.4f);
            }
            else
            {
                SpellVfx.Burst(at, smokeMaterial, count: 20, speed: 0.6f, size: 0.06f, lifetime: 0.9f);
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

                hand.HeldOrb.gameObject.SetActive(holding);
                hand.Ember.gameObject.SetActive(cooling);

                if (holding)
                {
                    hand.HeldOrb.position = position.Value;
                    var pulse = 1f + 0.08f * Mathf.Sin(Time.time * 18f);
                    hand.HeldOrb.localScale = Vector3.one * (heldDiameter * pulse);
                }
                else if (cooling)
                {
                    hand.Ember.position = position.Value;
                    hand.Ember.localScale = Vector3.one * (emberDiameter * Mathf.Clamp01(player.Cooldown / fullCooldown));
                }
            }

            foreach (var (playerId, hand) in _hands)
            {
                if (_players.ContainsKey(playerId))
                    continue;
                hand.HeldOrb.gameObject.SetActive(false);
                hand.Ember.gameObject.SetActive(false);
            }
        }

        private void UpdateProjectiles()
        {
            var blend = 1f - Mathf.Exp(-projectileCorrectionRate * Time.deltaTime);
            foreach (var visual in _projectiles.Values)
            {
                var predicted = visual.ServerPosition + visual.ServerVelocity * (Time.time - visual.ReceivedAt);
                var drifted = visual.Orb.position + visual.ServerVelocity * Time.deltaTime;
                visual.Orb.position = Vector3.Lerp(drifted, predicted, blend);
            }
        }

        private ProjectileVisual CreateProjectile(ProjectileSnapshot snapshot)
        {
            var orb = SpellVfx.CreateOrb($"Fireball {snapshot.Id}", transform, fireMaterial, projectileDiameter);
            orb.position = snapshot.Position;
            SpellVfx.AddFlames(orb, sparkMaterial, rate: 60f);
            SpellVfx.AddTrail(orb, fireMaterial, width: projectileDiameter * 0.8f, time: 0.2f);
            return new ProjectileVisual { Orb = orb };
        }

        private void RemoveProjectile(int id)
        {
            if (!_projectiles.Remove(id, out var visual))
                return;
            Destroy(visual.Orb.gameObject);
        }

        private HandVisuals HandFor(string playerId)
        {
            if (_hands.TryGetValue(playerId, out var hand))
                return hand;

            var heldOrb = SpellVfx.CreateOrb($"Held Fireball {playerId}", transform, fireMaterial, heldDiameter);
            SpellVfx.AddFlames(heldOrb, sparkMaterial, rate: 30f);
            hand = new HandVisuals
            {
                HeldOrb = heldOrb,
                Ember = SpellVfx.CreateOrb($"Ember {playerId}", transform, sparkMaterial, emberDiameter),
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
