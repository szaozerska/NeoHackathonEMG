using System.Collections.Generic;
using SpellGame.Protocol;
using TMPro;
using UnityEngine;

namespace SpellGame.Game
{
    /// <summary>
    /// Infinite Void charge-up: while a player holds the band's Infinite Void sign (<see cref="PlayerSnapshot.VoidCharge"/>,
    /// or B on the controller for this headset's player), a ring around their band hand fills up with a percentage above
    /// it, pulsing as it nears full; letting go empties it. The opponent's charge shows too, as a warning.
    /// </summary>
    public sealed class VoidChargeView : MonoBehaviour
    {
        [SerializeField] private GameClient gameClient;
        [SerializeField] private DomainExpansionButton domainButton;
        [SerializeField] private Material ringMaterial;
        [SerializeField] private float radius = 0.11f;
        [SerializeField] private Color chargeColor = new(0.62f, 0.35f, 1f);
        [SerializeField] private Color fullColor = Color.white;

        private const int Segments = 64;
        private readonly Dictionary<string, PlayerSnapshot> _players = new();
        private readonly Dictionary<string, Meter> _meters = new();

        private sealed class Meter
        {
            public Transform Root;
            public LineRenderer Track;
            public LineRenderer Fill;
            public TextMeshPro Label;
            public float Shown;
        }

        private void OnEnable() => gameClient.StateReceived += OnState;

        private void OnDisable() => gameClient.StateReceived -= OnState;

        private void OnState(StateMessage state)
        {
            _players.Clear();
            foreach (var player in state.Players)
                _players[player.PlayerId] = player;
        }

        private void Update()
        {
            var head = Camera.main != null ? Camera.main.transform : null;
            foreach (var (playerId, meter) in _meters)
                if (!_players.ContainsKey(playerId))
                    meter.Root.gameObject.SetActive(false);
            if (head == null)
                return;

            foreach (var (playerId, player) in _players)
            {
                var charge = player.VoidCharge;
                if (playerId == gameClient.PlayerId && domainButton != null)
                    charge = Mathf.Max(charge, domainButton.Progress);
                _meters.TryGetValue(playerId, out var meter);
                var hand = HandPosition(playerId, player);
                if (charge <= 0f || hand == null)
                {
                    if (meter != null)
                    {
                        meter.Root.gameObject.SetActive(false);
                        meter.Shown = 0f;
                    }
                    continue;
                }

                meter ??= _meters[playerId] = CreateMeter(playerId);
                meter.Root.gameObject.SetActive(true);
                meter.Shown = Mathf.MoveTowards(meter.Shown, charge, Time.deltaTime * 2f);
                Draw(meter, hand.Value, head, playerId == gameClient.PlayerId ? null : playerId);
            }
        }

        private void Draw(Meter meter, Vector3 hand, Transform head, string opponent)
        {
            var root = meter.Root;
            root.position = hand;
            root.rotation = Quaternion.LookRotation(hand - head.position, Vector3.up);

            var shown = meter.Shown;
            var full = shown >= 0.999f;
            var pulse = shown > 0.75f ? 0.5f + 0.5f * Mathf.Sin(Time.time * Mathf.Lerp(8f, 20f, (shown - 0.75f) * 4f)) : 0f;
            SetArc(meter.Fill, shown);
            meter.Fill.widthMultiplier = 0.012f + 0.008f * pulse + (full ? 0.01f : 0f);
            meter.Fill.sharedMaterial.color = Color.Lerp(chargeColor, fullColor, full ? 1f : pulse * 0.5f);
            var percent = Mathf.FloorToInt(shown * 100f);
            meter.Label.text = opponent == null
                ? full ? "INFINITE VOID!" : $"INFINITE VOID  {percent}%"
                : $"{opponent} CHARGING VOID  {percent}%";
        }

        private void SetArc(LineRenderer line, float fraction)
        {
            var count = Mathf.Max(2, Mathf.CeilToInt(Segments * fraction) + 1);
            line.positionCount = count;
            for (var i = 0; i < count; i++)
            {
                var angle = fraction * Mathf.PI * 2f * i / (count - 1);
                line.SetPosition(i, new Vector3(Mathf.Sin(angle) * radius, Mathf.Cos(angle) * radius, 0f));
            }
        }

        private Meter CreateMeter(string playerId)
        {
            var root = new GameObject($"Void Charge {playerId}").transform;
            root.SetParent(transform, false);
            var track = CreateLine("Track", root, new Color(chargeColor.r, chargeColor.g, chargeColor.b, 0.25f), 0.006f);
            SetArc(track, 1f);
            track.loop = true;
            var fill = CreateLine("Fill", root, chargeColor, 0.012f);
            var label = UiStyle.CreateText("Label", root, "", new Vector3(0f, radius + 0.05f, 0f), 0.03f, UiStyle.Text,
                display: true, look: UiStyle.Look.Title, width: 0.6f);
            return new Meter { Root = root, Track = track, Fill = fill, Label = label };
        }

        private LineRenderer CreateLine(string name, Transform parent, Color color, float width)
        {
            var line = new GameObject(name).AddComponent<LineRenderer>();
            line.transform.SetParent(parent, false);
            line.useWorldSpace = false;
            line.widthMultiplier = width;
            line.numCapVertices = 4;
            line.sharedMaterial = ringMaterial != null ? new Material(ringMaterial) { color = color } : null;
            line.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            line.receiveShadows = false;
            return line;
        }

        private Vector3? HandPosition(string playerId, PlayerSnapshot player)
        {
            if (!gameClient.TryGetJoints(playerId, out var joints))
                return null;
            var palm = player.BandHand == HandSide.Left ? joints.LHand : joints.RHand;
            return palm?.Position;
        }

        private void OnDestroy()
        {
            foreach (var meter in _meters.Values)
            {
                Destroy(meter.Track.sharedMaterial);
                Destroy(meter.Fill.sharedMaterial);
            }
        }
    }
}
