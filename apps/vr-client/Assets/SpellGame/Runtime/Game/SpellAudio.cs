using System;
using SpellGame.Protocol;
using UnityEngine;

namespace SpellGame.Game
{
    /// <summary>
    /// Spell sounds, synthesised at startup (no audio assets) and played where the event happens in the room, so you can
    /// hear a fireball being thrown behind you: conjure crackle, throw whoosh, explosion, sword draw "shing", sword hit,
    /// shield hum, block ping, parry clang. Taking a hit plays a non-spatial thud.
    /// </summary>
    public sealed class SpellAudio : MonoBehaviour
    {
        [SerializeField] private GameClient gameClient;
        [SerializeField, Range(0f, 1f)] private float volume = 0.8f;

        private const int Rate = 44100;

        private float Volume => volume * GameSettings.EffectsVolume;

        private AudioClip _charge, _throw, _explode, _draw, _swordHit, _shield, _block, _parry, _hitTaken;
        private AudioSource _local;
        private readonly System.Random _random = new(7);

        private void Awake()
        {
            _local = gameObject.AddComponent<AudioSource>();
            _local.playOnAwake = false;
            _local.spatialBlend = 0f;

            _charge = Synth("Charge", 0.3f, t => Sine(300f + 900f * t, t) * 0.4f * (0.6f + 0.4f * Mathf.Sin(t * 180f)) + Noise() * 0.15f);
            _throw = Synth("Throw", 0.35f, t => LowPassNoise(0.05f + 0.5f * t) * Fade(t, 0.35f), lowPass: true);
            _explode = Synth("Explode", 0.7f, t => (LowPassNoise(0.12f) * 1.2f + Sine(55f, t) * 0.8f) * Mathf.Exp(-t * 7f), lowPass: true);
            _draw = Synth("Draw", 0.35f, t => (Sine(2400f + 1500f * t, t) * 0.25f + Noise() * 0.25f) * Mathf.Exp(-t * 8f));
            _swordHit = Synth("SwordHit", 0.2f, t => (Noise() * 0.7f + Sine(180f, t) * 0.6f) * Mathf.Exp(-t * 25f));
            _shield = Synth("Shield", 0.45f, t => (Sine(170f, t) + Sine(255f, t) * 0.6f) * 0.35f * Fade(t, 0.45f));
            _block = Synth("Block", 0.35f, t => (Sine(1250f, t) + Sine(1870f, t) * 0.5f) * 0.4f * Mathf.Exp(-t * 12f));
            _parry = Synth("Parry", 0.6f, t => (Sine(523f, t) + Sine(1377f, t) * 0.7f + Sine(2211f, t) * 0.4f) * 0.35f * Mathf.Exp(-t * 6f));
            _hitTaken = Synth("HitTaken", 0.3f, t => (Sine(85f, t) + LowPassNoise(0.2f) * 0.6f) * Mathf.Exp(-t * 12f), lowPass: true);
        }

        private void OnEnable()
        {
            gameClient.SpellReceived += OnSpell;
            gameClient.ImpactReceived += OnImpact;
            gameClient.DamageReceived += OnDamage;
        }

        private void OnDisable()
        {
            gameClient.SpellReceived -= OnSpell;
            gameClient.ImpactReceived -= OnImpact;
            gameClient.DamageReceived -= OnDamage;
        }

        private void OnSpell(SpellMessage spell)
        {
            var clip = (spell.Spell, spell.State) switch
            {
                (SpellKind.Fireball, SpellState.Charging) => _charge,
                (SpellKind.Fireball, SpellState.Cast) => _throw,
                (SpellKind.Sword, SpellState.Cast) => _draw,
                (SpellKind.Shield, SpellState.Cast) => _shield,
                _ => null,
            };
            PlayAt(clip, spell.Origin, spell.CasterId);
        }

        private void OnImpact(ImpactMessage impact)
        {
            var clip = impact.Reason switch
            {
                "parried" => _parry,
                "blocked" => _block,
                _ when impact.Kind == SpellKind.Fireball => _explode,
                _ => null,
            };
            PlayAt(clip, impact.Pos, impact.OwnerId);
        }

        private void OnDamage(DamageMessage damage)
        {
            if (damage.TargetId == gameClient.PlayerId)
                _local.PlayOneShot(_hitTaken, Volume);
            else if (damage.Kind == SpellKind.Sword)
                PlayAt(_swordHit, damage.Pos, damage.SourceId);
        }

        /// <summary>At <paramref name="pos"/>, else at the player's head, else non-spatial.</summary>
        private void PlayAt(AudioClip clip, float[] pos, string playerId)
        {
            if (clip == null)
                return;
            if (pos is { Length: 3 })
                AudioSource.PlayClipAtPoint(clip, new Vector3(pos[0], pos[1], pos[2]), Volume);
            else if (playerId != null && gameClient.TryGetJoints(playerId, out var joints) && joints?.Head != null)
                AudioSource.PlayClipAtPoint(clip, joints.Head.Position, Volume);
            else
                _local.PlayOneShot(clip, Volume);
        }

        private float _phase;
        private float _lowPass;

        private static float Fade(float t, float length) => Mathf.Min(1f, t / 0.02f) * Mathf.Clamp01((length - t) / (length * 0.6f));

        private float Sine(float frequency, float t) => Mathf.Sin(2f * Mathf.PI * frequency * t);

        private float Noise() => (float)(_random.NextDouble() * 2.0 - 1.0);

        /// <summary>One-pole low-passed noise; <paramref name="cutoff"/> 0–1 (fraction of a sample's step).</summary>
        private float LowPassNoise(float cutoff)
        {
            _lowPass += (Noise() - _lowPass) * Mathf.Clamp01(cutoff);
            return _lowPass * 3f;
        }

        private AudioClip Synth(string name, float seconds, Func<float, float> sample, bool lowPass = false)
        {
            _lowPass = 0f;
            var count = Mathf.CeilToInt(Rate * seconds);
            var data = new float[count];
            var peak = 1e-4f;
            for (var i = 0; i < count; i++)
            {
                var t = (float)i / Rate;
                var envelope = Mathf.Min(1f, i / (Rate * 0.003f)) * Mathf.Min(1f, (count - i) / (Rate * 0.01f));
                data[i] = sample(t) * envelope;
                peak = Mathf.Max(peak, Mathf.Abs(data[i]));
            }
            var gain = Mathf.Min(1f, 0.9f / peak);
            for (var i = 0; i < count; i++)
                data[i] *= gain;
            var clip = AudioClip.Create(name, count, 1, Rate, false);
            clip.SetData(data, 0);
            return clip;
        }
    }
}
