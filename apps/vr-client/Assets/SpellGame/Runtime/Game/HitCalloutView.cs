using System.Collections.Generic;
using SpellGame.Protocol;
using UnityEngine;

namespace SpellGame.Game
{
    /// <summary>
    /// A Pokémon Go-style grade pops up where a hit lands instead of a damage number: GOOD / GREAT! / EXCELLENT! /
    /// PERFECT! from the server's <see cref="HitGrade"/> (HEADSHOT on head hits), GREAT / EXCELLENT BLOCK and PERFECT
    /// PARRY! on defence; older servers without grades fall back to LIGHT / SOLID / HEAVY! by damage. Drawn in the theme's
    /// display font (crystal or wizard). Not shown for hits on you (the edge flash covers those); it floats up and fades.
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
        private static readonly Color PerfectColor = new(1f, 0.85f, 0.25f);

        private sealed class Callout
        {
            public TMPro.TextMeshPro Text;
            public Vector3 Start;
            public float Born;
            public float Size;
            public Color Color;
        }

        private readonly List<Callout> _live = new();
        private readonly Stack<TMPro.TextMeshPro> _pool = new();

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
            if (damage.Grade != null)
            {
                var (word, color, size) = Graded(damage.Grade);
                Spawn(damage.Zone == HitZone.Head ? $"HEADSHOT\n{word}" : word, color, size, damage.Pos);
                return;
            }
            var (tier, tierColor, tierSize) = damage.Amount >= heavyFrom ? ("HEAVY!", HeavyColor, 1.5f)
                : damage.Amount >= solidFrom ? ("SOLID", SolidColor, 1.15f)
                : ("LIGHT", LightColor, 0.85f);
            Spawn(tier, tierColor, tierSize, damage.Pos);
        }

        private void OnImpact(ImpactMessage impact)
        {
            if (impact.Pos is not { Length: 3 })
                return;
            if (impact.Reason == "parried")
                Spawn("PERFECT PARRY!", ParryColor, 1.5f, impact.Pos);
            else if (impact.Reason == "blocked")
                Spawn(impact.Grade is HitGrade.Excellent or HitGrade.Perfect ? "EXCELLENT BLOCK!"
                    : impact.Grade == HitGrade.Great ? "GREAT BLOCK" : "BLOCKED", BlockColor, impact.Grade == HitGrade.Excellent ? 1.3f : 1f, impact.Pos);
        }

        /// <summary>Pokémon Go-style grades: brighter, bigger and warmer as they go up.</summary>
        private static (string Word, Color Color, float Size) Graded(string grade) => grade switch
        {
            HitGrade.Perfect => ("PERFECT!", PerfectColor, 1.6f),
            HitGrade.Excellent => ("EXCELLENT!", HeavyColor, 1.4f),
            HitGrade.Great => ("GREAT!", SolidColor, 1.15f),
            _ => ("GOOD", LightColor, 0.9f),
        };

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

        /// <summary>The theme's display font (crystal or wizard) with its outline, like the rest of the in-room text.</summary>
        private TMPro.TextMeshPro CreateText() =>
            UiStyle.CreateText("Callout", transform, "", Vector3.zero, 0.07f, Color.white, display: true, look: UiStyle.Look.Title);
    }
}
