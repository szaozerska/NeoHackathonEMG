using System.Collections.Generic;
using SpellGame.Protocol;
using UnityEngine;

namespace SpellGame.Game
{
    /// <summary>
    /// Renders swords from server events and state (game_plan.md stage 1b):
    /// <list type="bullet">
    /// <item>draw (<c>spell cast</c>) flashes sparks at the hand, sheathe (<c>spell sheathed</c>) removes the blade at once;</item>
    /// <item>while <c>item == "sword"</c>, a glowing blade runs from the band hand along the forearm (elbow to hand),
    /// the same line the server hit-tests;</item>
    /// <item>a swing trail appears once the tip is fast enough to hurt and widens up to full-damage speed;</item>
    /// <item>sword <c>damage</c> throws sparks at the contact point.</item>
    /// </list>
    /// Like the fireball, the local player's blade follows local hand tracking.
    /// </summary>
    public sealed class SwordView : MonoBehaviour
    {
        [SerializeField] private GameClient gameClient;
        [SerializeField] private Material bladeMaterial;
        [SerializeField] private Material trailMaterial;
        [SerializeField] private Material sparkMaterial;

        [Header("Must match the server's Tuning")]
        [Tooltip("Tuning.sword_length")]
        [SerializeField] private float bladeLength = 0.9f;
        [Tooltip("Tuning.sword_min_tip_speed: slower swings don't hurt and draw no trail.")]
        [SerializeField] private float minTipSpeed = 2f;
        [Tooltip("Tuning.sword_full_damage_tip_speed")]
        [SerializeField] private float fullDamageTipSpeed = 8f;

        [Header("Look")]
        [Tooltip("Server Tuning.sword_radius is 0.04, so 0.08 shows the true hit width.")]
        [SerializeField] private float bladeWidth = 0.03f;
        [SerializeField] private float trailWidth = 0.08f;
        [SerializeField] private float trailTime = 0.15f;

        private sealed class BladeVisual
        {
            public Transform Blade;
            public Transform Tip;
            public TrailRenderer Trail;
            public Vector3? LastTip;
        }

        private readonly Dictionary<string, PlayerSnapshot> _players = new();
        private readonly Dictionary<string, BladeVisual> _blades = new();

        private void OnEnable()
        {
            gameClient.SpellReceived += OnSpell;
            gameClient.StateReceived += OnState;
            gameClient.DamageReceived += OnDamage;
        }

        private void OnDisable()
        {
            gameClient.SpellReceived -= OnSpell;
            gameClient.StateReceived -= OnState;
            gameClient.DamageReceived -= OnDamage;
        }

        private void OnSpell(SpellMessage spell)
        {
            if (spell.Spell != SpellKind.Sword)
                return;

            Vector3? at = TryGetBlade(spell.CasterId, out var hilt, out _) ? hilt : ToVector(spell.Origin);
            switch (spell.State)
            {
                case SpellState.Cast:
                    if (at != null)
                        SpellVfx.Burst(at.Value, sparkMaterial, count: 20, speed: 1.2f, size: 0.02f, lifetime: 0.3f);
                    break;
                case SpellState.Sheathed:
                    if (_players.TryGetValue(spell.CasterId, out var player))
                        player.Item = "none";
                    if (at != null)
                        SpellVfx.Burst(at.Value, sparkMaterial, count: 8, speed: 0.5f, size: 0.015f, lifetime: 0.25f);
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
            SpellVfx.Burst(at, sparkMaterial, count: 30, speed: 3f, size: 0.02f, lifetime: 0.35f);
            SpellVfx.Burst(at, bladeMaterial, count: 12, speed: 1.5f, size: 0.03f, lifetime: 0.25f);
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
            }
        }

        private void ShowBlade(BladeVisual visual, Vector3 hilt, Vector3 tip)
        {
            visual.Blade.gameObject.SetActive(true);
            SpellVfx.PlaceBlade(visual.Blade, hilt, tip, bladeWidth);
            visual.Tip.position = tip;

            var tipSpeed = visual.LastTip is { } lastTip && Time.deltaTime > 0f
                ? Vector3.Distance(tip, lastTip) / Time.deltaTime
                : 0f;
            visual.LastTip = tip;
            visual.Trail.emitting = tipSpeed >= minTipSpeed;
            visual.Trail.widthMultiplier = Mathf.Lerp(0.3f, 1f, Mathf.InverseLerp(minTipSpeed, fullDamageTipSpeed, tipSpeed));
        }

        private static void HideBlade(BladeVisual visual)
        {
            if (!visual.Blade.gameObject.activeSelf)
                return;
            visual.Blade.gameObject.SetActive(false);
            visual.Trail.emitting = false;
            visual.Trail.Clear();
            visual.LastTip = null;
        }

        private BladeVisual BladeFor(string playerId)
        {
            if (_blades.TryGetValue(playerId, out var visual))
                return visual;

            var blade = SpellVfx.CreateBlade($"Sword {playerId}", transform, bladeMaterial);
            blade.gameObject.SetActive(false);
            var tip = new GameObject($"Sword Tip {playerId}").transform;
            tip.SetParent(transform, false);
            var trail = SpellVfx.AddTrail(tip, trailMaterial, width: trailWidth, time: trailTime);
            trail.emitting = false;
            visual = new BladeVisual { Blade = blade, Tip = tip, Trail = trail };
            _blades[playerId] = visual;
            return visual;
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
    }
}
