using System.Collections.Generic;
using SpellGame.Protocol;
using UnityEngine;

namespace SpellGame.Game
{
    /// <summary>
    /// A word pops up where a hit lands instead of a damage number, so players read how good the hit was rather than
    /// doing arithmetic: LIGHT (grey, small), SOLID (orange), HEAVY! (red, big), plus HEADSHOT for head hits, BLOCKED
    /// (blue) and PARRY! (cyan). Not shown for hits on you (the edge flash covers those); it floats up and fades.
    /// </summary>
    public sealed class HitCalloutView : MonoBehaviour
    {
        [SerializeField] private GameClient gameClient;

        [Header("Tiers (damage per hit; fireball 8, sword 6-15)")]
        [SerializeField] private float solidFrom = 7f;
        [SerializeField] private float heavyFrom = 12f;

        [Header("Motion")]
        [SerializeField] private float lifetime = 0.9f;
        [SerializeField] private float rise = 0.25f;

        private static readonly Color LightColor = new(0.8f, 0.8f, 0.85f);
        private static readonly Color SolidColor = new(1f, 0.6f, 0.15f);
        private static readonly Color HeavyColor = new(1f, 0.2f, 0.15f);
        private static readonly Color BlockColor = new(0.4f, 0.6f, 1f);
        private static readonly Color ParryColor = new(0.35f, 1f, 1f);

        private sealed class Callout
        {
            public TextMesh Text;
            public Vector3 Start;
            public float Born;
            public float Size;
            public Color Color;
        }

        private readonly List<Callout> _live = new();
        private readonly Stack<TextMesh> _pool = new();

        private void OnEnable()
        {
            gameClient.DamageReceived += OnDamage;
            gameClient.ImpactReceived += OnImpact;
        }

        private void OnDisable()
        {
            gameClient.DamageReceived -= OnDamage;
            gameClient.ImpactReceived -= OnImpact;
        }

        private void OnDamage(DamageMessage damage)
        {
            if (damage.TargetId == gameClient.PlayerId || damage.Pos is not { Length: 3 })
                return;
            var (word, color, size) = damage.Amount >= heavyFrom ? ("HEAVY!", HeavyColor, 1.5f)
                : damage.Amount >= solidFrom ? ("SOLID", SolidColor, 1.15f)
                : ("LIGHT", LightColor, 0.85f);
            if (damage.Zone == HitZone.Head)
                word = $"HEADSHOT\n{word}";
            Spawn(word, color, size, damage.Pos);
        }

        private void OnImpact(ImpactMessage impact)
        {
            if (impact.Pos is not { Length: 3 })
                return;
            if (impact.Reason == "parried")
                Spawn("PARRY!", ParryColor, 1.4f, impact.Pos);
            else if (impact.Reason == "blocked")
                Spawn("BLOCKED", BlockColor, 1f, impact.Pos);
        }

        private void Spawn(string word, Color color, float size, float[] pos)
        {
            var text = _pool.Count > 0 ? _pool.Pop() : CreateText();
            text.gameObject.SetActive(true);
            text.text = word;
            _live.Add(new Callout
            {
                Text = text,
                Start = new Vector3(pos[0], pos[1], pos[2]) + Vector3.up * 0.1f,
                Born = Time.time,
                Size = size,
                Color = color,
            });
        }

        private void Update()
        {
            var viewer = Camera.main != null ? Camera.main.transform.position : Vector3.zero;
            for (var i = _live.Count - 1; i >= 0; i--)
            {
                var callout = _live[i];
                var t = (Time.time - callout.Born) / lifetime;
                if (t >= 1f)
                {
                    callout.Text.gameObject.SetActive(false);
                    _pool.Push(callout.Text);
                    _live.RemoveAt(i);
                    continue;
                }

                var tf = callout.Text.transform;
                tf.position = callout.Start + Vector3.up * (rise * (1f - (1f - t) * (1f - t)));
                var away = tf.position - viewer;
                if (away.sqrMagnitude > 1e-6f)
                    tf.rotation = Quaternion.LookRotation(away);
                var distance = Mathf.Max(1f, away.magnitude);
                var pop = t < 0.15f ? Mathf.Lerp(1.4f, 1f, t / 0.15f) : 1f;
                tf.localScale = Vector3.one * (callout.Size * pop * Mathf.Sqrt(distance));
                var color = callout.Color;
                color.a = t < 0.6f ? 1f : 1f - (t - 0.6f) / 0.4f;
                callout.Text.color = color;
            }
        }

        private TextMesh CreateText()
        {
            var label = new GameObject("Callout").AddComponent<TextMesh>();
            label.transform.SetParent(transform, false);
            label.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            label.GetComponent<MeshRenderer>().sharedMaterial = label.font.material;
            label.anchor = TextAnchor.MiddleCenter;
            label.alignment = TextAlignment.Center;
            label.characterSize = 0.012f;
            label.fontSize = 64;
            label.fontStyle = FontStyle.Bold;
            return label;
        }
    }
}
