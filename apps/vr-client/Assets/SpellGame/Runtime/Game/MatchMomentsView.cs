using System.Collections.Generic;
using SpellGame.Protocol;
using TMPro;
using UnityEngine;
using UnityEngine.Rendering;

namespace SpellGame.Game
{
    /// <summary>
    /// The big moments of a match, fighting-game style, each step paired with an announcer line, a sound and a buzz on
    /// both controllers (the server buzzes the bands at match start and end):
    /// <list type="bullet">
    /// <item>Countdown: 3-2-1 fly from about 4 m toward you and land with a drum hit.</item>
    /// <item>FIGHT! slams in with a shockwave ring and sparks.</item>
    /// <item>SUDDEN DEATH when time runs out on a tie.</item>
    /// <item>K.O.: about 0.8 s of slow motion with the passthrough darkened and desaturated, then K.O. slams in at a tilt.
    /// The results (<see cref="EndGameView"/>, <see cref="MatchMenu"/>) wait <see cref="KoBeatSeconds"/>.</item>
    /// <item>Time out: the announcer calls TIME!</item>
    /// </list>
    /// The server stays authoritative: this only reacts to <see cref="MatchSnapshot"/> phase changes, and slow motion is
    /// client presentation only (<see cref="Time.timeScale"/>). Animation runs on unscaled time.
    /// </summary>
    public sealed class MatchMomentsView : MonoBehaviour
    {
        /// <summary>Real seconds from the K.O. until the results appear.</summary>
        public const float KoBeatSeconds = 1.9f;

        /// <summary>Real seconds from the start of play until FIGHT! has faded (the timer badge appears then).</summary>
        public const float FightSeconds = FightFly + FightHold + FightFade;

        private const float FightFly = 0.14f, FightHold = 0.8f, FightFade = 0.3f;

        [SerializeField] private GameClient gameClient;
        [SerializeField] private OVRCameraRig cameraRig;
        [Tooltip("Darkened and desaturated during the K.O. slow motion; left alone if it already has a colour map.")]
        [SerializeField] private OVRPassthroughLayer passthrough;
        [Tooltip("Unlit material the ring and spark materials are copied from (only its colour is changed).")]
        [SerializeField] private Material baseMaterial;

        [Header("Text")]
        [SerializeField] private TMP_FontAsset font;
        [Tooltip("TextMeshPro material for the font with GLOW_ON and UNDERLAY_ON, copied per moment.")]
        [SerializeField] private Material textMaterial;

        [Header("Announcer")]
        [SerializeField] private AudioClip three;
        [SerializeField] private AudioClip two;
        [SerializeField] private AudioClip one;
        [SerializeField] private AudioClip fight;
        [SerializeField] private AudioClip ko;
        [SerializeField] private AudioClip time;
        [SerializeField] private AudioClip suddenDeath;
        [SerializeField, Range(0f, 1f)] private float voiceVolume = 1f;
        [SerializeField, Range(0f, 1f)] private float effectsVolume = 0.8f;

        [Header("Countdown")]
        [SerializeField] private float spawnDistance = 4f;
        [SerializeField] private float landDistance = 1.9f;
        [SerializeField] private float flySeconds = 0.25f;
        [SerializeField] private float countdownFontSize = 8f;

        [Header("FIGHT!")]
        [SerializeField] private float fightDistance = 2.2f;
        [SerializeField] private float fightFontSize = 6f;

        [Header("K.O.")]
        [SerializeField] private float koDistance = 2f;
        [SerializeField] private float koFontSize = 7f;
        [Tooltip("Degrees; positive tips the right end up.")]
        [SerializeField] private float koTilt = 7f;
        [SerializeField, Range(0.05f, 1f)] private float slowMotionScale = 0.25f;
        [Tooltip("Real seconds of slow motion.")]
        [SerializeField] private float slowMotionSeconds = 0.8f;
        [SerializeField, Range(-1f, 0f)] private float passthroughBrightness = -0.3f;
        [SerializeField, Range(-1f, 0f)] private float passthroughSaturation = -0.85f;

        /// <summary>A text that flies or slams in, holds, then fades; driven on unscaled time.</summary>
        private sealed class Pop
        {
            public Transform Root;
            public TextMeshPro Text;
            public Vector3 From, To, Drift;
            public Quaternion Rotation;
            public float Born, Fly, Hold, Fade;
            public float StartScale = 1f;
            public float Shake;
            public bool Landed;
            public System.Action OnLand;
        }

        private readonly List<Pop> _pops = new();
        private MatchSnapshot _match = new();
        private string _lastPhase;
        private int _lastCount = -1;
        private bool _suddenDeathShown;
        private Vector3 _eye, _forward;

        private Material _countdownMaterial, _fightMaterial, _koMaterial;
        private TextMeshPro _controllersPrompt;
        private AudioSource _audio;
        private AudioClip _drum, _whoosh, _impact, _bass;

        private Transform _ring;
        private LineRenderer _ringLine;
        private float _ringBorn = float.NegativeInfinity;
        private ParticleSystem _sparks;

        private float _slowStart = float.NegativeInfinity;
        private bool _slowActive;
        private bool _tintActive;

        private float _buzzStart, _buzzEnd, _buzzAmplitude, _buzzFrequency;
        private bool _buzzDecays;
        private bool _buzzing;

        private const int RingSegments = 64;
        private const float RingSeconds = 0.45f;

        private Transform Eye => cameraRig != null ? cameraRig.centerEyeAnchor : Camera.main.transform;
        private float Now => Time.unscaledTime;

        private void Awake()
        {
            _audio = gameObject.AddComponent<AudioSource>();
            _audio.playOnAwake = false;
            _audio.spatialBlend = 0f;
            _drum = Drum();
            _whoosh = Whoosh();
            _impact = Impact();
            _bass = Bass();

            if (!MomentText.Available)
            {
                Debug.LogError("[SpellGame] TMP Essential Resources are missing, so the countdown/FIGHT!/K.O. text is off. " +
                               "Run SpellGame/Rebuild Main Scene in the editor to import them.");
                return;
            }
            var template = textMaterial != null ? textMaterial : font != null ? font.material : TMP_Settings.defaultFontAsset.material;
            _countdownMaterial = MomentText.GlowMaterial(template, MomentPalette.CountdownGlow, MomentPalette.NoShadow);
            _fightMaterial = MomentText.GlowMaterial(template, MomentPalette.FightGlow, MomentPalette.NoShadow);
            _koMaterial = MomentText.GlowMaterial(template, MomentPalette.KoGlow, MomentPalette.KoShadow);
            CreateRing();
            CreateSparks();
        }

        private void OnEnable()
        {
            gameClient.StateReceived += OnState;
            gameClient.ConnectionChanged += OnConnectionChanged;
        }

        private void OnDisable()
        {
            gameClient.StateReceived -= OnState;
            gameClient.ConnectionChanged -= OnConnectionChanged;
            EndSlowMotion();
            StopBuzz();
        }

        private void OnConnectionChanged(ConnectionState connection)
        {
            if (connection == ConnectionState.Connected)
                return;
            _lastPhase = null;
            _match = new MatchSnapshot();
            EndSlowMotion();
        }

        // ---------------------------------------------------------------- phases

        private void OnState(StateMessage state)
        {
            _match = state.Match ?? new MatchSnapshot();
            var from = _lastPhase;
            var to = _match.Phase;
            _lastPhase = to;

            if (to != from)
            {
                switch (to)
                {
                    case MatchPhase.Countdown:
                        EndSlowMotion();
                        CaptureView();
                        _lastCount = -1;
                        _suddenDeathShown = false;
                        ShowControllersPrompt(true);
                        break;
                    case MatchPhase.Playing when from == MatchPhase.Countdown:
                        Fight();
                        break;
                    case MatchPhase.Ended when from == MatchPhase.Playing && _match.Reason == MatchEndReason.Ko:
                        KnockOut();
                        break;
                    case MatchPhase.Ended when from == MatchPhase.Playing && _match.Reason == MatchEndReason.Time:
                        Announce(time);
                        Buzz(0.7f, 0.25f, 1f, false);
                        break;
                }
                if (to != MatchPhase.Ended)
                    EndSlowMotion();
                if (to != MatchPhase.Countdown)
                    ShowControllersPrompt(false);
            }

            if (to == MatchPhase.Countdown)
            {
                var count = Mathf.Max(1, Mathf.CeilToInt(_match.Countdown));
                if (count != _lastCount)
                {
                    _lastCount = count;
                    CountdownNumber(count);
                }
            }
            else if (to == MatchPhase.Playing && _match.SuddenDeath && !_suddenDeathShown)
            {
                _suddenDeathShown = true;
                SuddenDeath();
            }
        }

        /// <summary>
        /// "Put your controllers down!" during the countdown, 1.5 m ahead and well below eye level, so it sits under
        /// where the 3-2-1 lands (eye level, <see cref="landDistance"/>) without overlapping it.
        /// </summary>
        private void ShowControllersPrompt(bool show)
        {
            if (!show)
            {
                if (_controllersPrompt != null)
                    _controllersPrompt.gameObject.SetActive(false);
                return;
            }

            _controllersPrompt ??= UiStyle.CreateText("Controllers Prompt", transform, "PUT YOUR CONTROLLERS DOWN!", Vector3.zero,
                0.07f, UiStyle.Text, display: true, look: UiStyle.Look.Title, width: 1.6f);
            var prompt = _controllersPrompt.transform;
            prompt.SetPositionAndRotation(_eye + _forward * 1.5f + Vector3.down * 0.55f, Quaternion.LookRotation(_forward));
            _controllersPrompt.gameObject.SetActive(true);
        }

        private void CountdownNumber(int count)
        {
            var clip = count switch { 3 => three, 2 => two, 1 => one, _ => null };
            var pop = Spawn(count.ToString(), _countdownMaterial, countdownFontSize, MomentPalette.Text, false,
                spawnDistance, landDistance, 0f);
            if (pop == null)
                return;
            pop.Fly = flySeconds;
            pop.Hold = Mathf.Max(0.1f, 0.95f - flySeconds - 0.2f);
            pop.Fade = 0.2f;
            pop.StartScale = 0.5f;
            pop.Drift = -_forward * 0.25f;
            pop.OnLand = () =>
            {
                _audio.PlayOneShot(_drum, effectsVolume);
                Announce(clip);
                Buzz(0.5f, 0.08f, 1f, false);
            };
        }

        private void Fight()
        {
            CaptureView();
            _audio.PlayOneShot(_whoosh, effectsVolume * 0.7f);
            var pop = Spawn("FIGHT!", _fightMaterial, fightFontSize, MomentPalette.FightText, true, fightDistance, fightDistance, 0f);
            if (pop == null)
            {
                Announce(fight);
                return;
            }
            pop.Fly = FightFly;
            pop.Hold = FightHold;
            pop.Fade = FightFade;
            pop.StartScale = 2.2f;
            pop.Shake = 0.015f;
            pop.OnLand = () =>
            {
                _audio.PlayOneShot(_impact, effectsVolume);
                Announce(fight);
                Buzz(1f, 0.35f, 1f, false);
                Shockwave(pop.To, pop.Rotation);
            };
        }

        private void SuddenDeath()
        {
            CaptureView();
            var pop = Spawn("SUDDEN DEATH", _koMaterial, fightFontSize * 0.7f, MomentPalette.Text, true, fightDistance, fightDistance, 0f);
            if (pop != null)
            {
                pop.Fly = 0.14f;
                pop.Hold = 1f;
                pop.Fade = 0.3f;
                pop.StartScale = 1.8f;
            }
            _audio.PlayOneShot(_impact, effectsVolume * 0.7f);
            Announce(suddenDeath);
            Buzz(0.8f, 0.3f, 1f, false);
        }

        private void KnockOut()
        {
            CaptureView();
            StartSlowMotion();
            var pop = Spawn("K.O.", _koMaterial, koFontSize, MomentPalette.Text, true, koDistance, koDistance, koTilt);
            if (pop == null)
            {
                _audio.PlayOneShot(_bass, effectsVolume);
                Announce(ko);
                Buzz(1f, 1f, 0.5f, true);
                return;
            }
            const float delay = 0.1f;
            pop.Born += delay;
            pop.Fly = 0.16f;
            pop.Fade = 0.25f;
            pop.Hold = KoBeatSeconds - delay - pop.Fly - pop.Fade;
            pop.StartScale = 2.8f;
            pop.Shake = 0.03f;
            pop.OnLand = () =>
            {
                _audio.PlayOneShot(_bass, effectsVolume);
                Announce(ko);
                Buzz(1f, 1f, 0.5f, true);
            };
        }

        private void Announce(AudioClip clip)
        {
            if (clip != null)
                _audio.PlayOneShot(clip, voiceVolume);
        }

        // ---------------------------------------------------------------- per frame

        private void Update()
        {
            for (var i = _pops.Count - 1; i >= 0; i--)
            {
                if (!UpdatePop(_pops[i]))
                {
                    Destroy(_pops[i].Root.gameObject);
                    _pops.RemoveAt(i);
                }
            }
            UpdateRing();
            UpdateSlowMotion();
            UpdateBuzz();
        }

        /// <returns>False once the pop has faded out.</returns>
        private bool UpdatePop(Pop pop)
        {
            var age = Now - pop.Born;
            pop.Root.gameObject.SetActive(age >= 0f);
            if (age < 0f)
                return true;

            float scale;
            Vector3 position;
            var alpha = 1f;
            if (age < pop.Fly)
            {
                var t = EaseOutCubic(age / pop.Fly);
                position = Vector3.Lerp(pop.From, pop.To, t);
                scale = Mathf.Lerp(pop.StartScale, 1f, t);
            }
            else
            {
                if (!pop.Landed)
                {
                    pop.Landed = true;
                    pop.OnLand?.Invoke();
                }
                var since = age - pop.Fly;
                var settle = Mathf.Exp(-since * 12f);
                position = pop.To + pop.Drift * since + Random.insideUnitSphere * (pop.Shake * settle);
                scale = 1f + 0.12f * settle;
                var fading = since - pop.Hold;
                if (fading > 0f)
                {
                    var f = Mathf.Clamp01(fading / Mathf.Max(pop.Fade, 0.01f));
                    alpha = 1f - f;
                    scale *= 1f + 0.25f * f;
                    if (f >= 1f)
                        return false;
                }
            }
            pop.Root.position = position;
            pop.Root.rotation = pop.Rotation;
            pop.Root.localScale = Vector3.one * scale;
            pop.Text.alpha = alpha;
            return true;
        }

        private void UpdateRing()
        {
            if (_ring == null)
                return;
            var t = (Now - _ringBorn) / RingSeconds;
            var visible = t is >= 0f and < 1f;
            _ring.gameObject.SetActive(visible);
            if (!visible)
                return;
            var eased = EaseOutCubic(t);
            _ring.localScale = Vector3.one * Mathf.Lerp(0.35f, 1.6f, eased);
            _ringLine.widthMultiplier = Mathf.Lerp(0.05f, 0f, t);
        }

        // ---------------------------------------------------------------- slow motion and passthrough tint

        private void StartSlowMotion()
        {
            _slowStart = Now;
            _slowActive = true;
            Time.timeScale = slowMotionScale;
            _tintActive = passthrough != null && passthrough.colorMapEditorType == OVRPassthroughLayer.ColorMapEditorType.None;
        }

        private void UpdateSlowMotion()
        {
            if (!_slowActive)
                return;
            var p = (Now - _slowStart) / Mathf.Max(slowMotionSeconds, 0.01f);
            if (p >= 1f)
            {
                EndSlowMotion();
                return;
            }
            // Ease back to full speed over the last quarter so the world doesn't snap.
            Time.timeScale = Mathf.Lerp(slowMotionScale, 1f, Mathf.SmoothStep(0f, 1f, Mathf.InverseLerp(0.75f, 1f, p)));
            if (_tintActive)
            {
                var amount = Mathf.Min(Mathf.Clamp01(p / 0.12f), Mathf.Clamp01((1f - p) / 0.3f));
                passthrough.SetBrightnessContrastSaturation(passthroughBrightness * amount, 0f, passthroughSaturation * amount);
            }
        }

        private void EndSlowMotion()
        {
            if (_slowActive)
                Time.timeScale = 1f;
            _slowActive = false;
            if (_tintActive && passthrough != null)
                passthrough.DisableColorMap();
            _tintActive = false;
        }

        // ---------------------------------------------------------------- controller haptics

        private void Buzz(float amplitude, float seconds, float frequency, bool decays)
        {
            _buzzStart = Now;
            _buzzEnd = Now + seconds;
            _buzzAmplitude = amplitude;
            _buzzFrequency = frequency;
            _buzzDecays = decays;
            _buzzing = true;
        }

        private void UpdateBuzz()
        {
            if (!_buzzing)
                return;
            if (Now >= _buzzEnd)
            {
                StopBuzz();
                return;
            }
            var amplitude = _buzzAmplitude;
            if (_buzzDecays)
                amplitude *= 1f - Mathf.InverseLerp(_buzzStart, _buzzEnd, Now);
            OVRInput.SetControllerVibration(_buzzFrequency, amplitude, OVRInput.Controller.LTouch);
            OVRInput.SetControllerVibration(_buzzFrequency, amplitude, OVRInput.Controller.RTouch);
        }

        private void StopBuzz()
        {
            if (!_buzzing)
                return;
            _buzzing = false;
            OVRInput.SetControllerVibration(0f, 0f, OVRInput.Controller.LTouch);
            OVRInput.SetControllerVibration(0f, 0f, OVRInput.Controller.RTouch);
        }

        // ---------------------------------------------------------------- construction

        private void CaptureView()
        {
            var eye = Eye;
            _eye = eye.position;
            var forward = eye.forward;
            forward.y = 0f;
            _forward = forward.sqrMagnitude > 1e-4f ? forward.normalized : Vector3.forward;
        }

        private Vector3 Spot(float distance) => _eye + _forward * distance + Vector3.down * 0.05f;

        private Pop Spawn(string text, Material material, float fontSize, Color color, bool italic, float from, float to, float tilt)
        {
            if (!MomentText.Available)
                return null;
            var root = new GameObject($"Moment {text}").transform;
            root.SetParent(transform, false);
            var label = MomentText.Create("Text", root, font, material, text, fontSize, color, italic);
            var pop = new Pop
            {
                Root = root,
                Text = label,
                From = Spot(from),
                To = Spot(to),
                Rotation = Quaternion.LookRotation(_forward) * Quaternion.Euler(0f, 0f, tilt),
                Born = Now,
            };
            _pops.Add(pop);
            UpdatePop(pop);
            return pop;
        }

        private void Shockwave(Vector3 at, Quaternion rotation)
        {
            if (_ring == null)
                return;
            _ring.SetPositionAndRotation(at + _forward * 0.02f, rotation);
            _ringBorn = Now;
            _sparks.transform.SetPositionAndRotation(at, rotation);
            _sparks.Play();
        }

        private void CreateRing()
        {
            _ring = new GameObject("Shockwave").transform;
            _ring.SetParent(transform, false);
            _ringLine = _ring.gameObject.AddComponent<LineRenderer>();
            _ringLine.useWorldSpace = false;
            _ringLine.loop = true;
            _ringLine.positionCount = RingSegments;
            for (var i = 0; i < RingSegments; i++)
            {
                var angle = i * Mathf.PI * 2f / RingSegments;
                _ringLine.SetPosition(i, new Vector3(Mathf.Cos(angle), Mathf.Sin(angle) * 0.7f, 0f));
            }
            _ringLine.sharedMaterial = Tinted(MomentPalette.FightGlow);
            _ringLine.shadowCastingMode = ShadowCastingMode.Off;
            _ringLine.receiveShadows = false;
            _ring.gameObject.SetActive(false);
        }

        private void CreateSparks()
        {
            var go = new GameObject("Sparks");
            go.transform.SetParent(transform, false);
            _sparks = go.AddComponent<ParticleSystem>();
            _sparks.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
            var main = _sparks.main;
            main.playOnAwake = false;
            main.loop = false;
            main.duration = 0.1f;
            main.simulationSpace = ParticleSystemSimulationSpace.World;
            main.startLifetime = new ParticleSystem.MinMaxCurve(0.4f, 0.8f);
            main.startSpeed = new ParticleSystem.MinMaxCurve(1.5f, 3.5f);
            main.startSize = new ParticleSystem.MinMaxCurve(0.012f, 0.03f);
            main.gravityModifier = 0.4f;
            var emission = _sparks.emission;
            emission.rateOverTime = 0f;
            emission.SetBursts(new[] { new ParticleSystem.Burst(0f, 40) });
            var shape = _sparks.shape;
            shape.shapeType = ParticleSystemShapeType.Circle;
            shape.radius = 0.4f;
            var renderer = go.GetComponent<ParticleSystemRenderer>();
            renderer.sharedMaterial = Tinted(MomentPalette.FightText);
            renderer.shadowCastingMode = ShadowCastingMode.Off;
            renderer.receiveShadows = false;
        }

        private Material Tinted(Color color)
        {
            var material = new Material(baseMaterial);
            material.SetColor("_BaseColor", new Color(color.r, color.g, color.b, 1f));
            return material;
        }

        private static float EaseOutCubic(float t)
        {
            t = 1f - Mathf.Clamp01(t);
            return 1f - t * t * t;
        }

        // ---------------------------------------------------------------- synthesised effects (voice lines are assets)

        private const int Rate = 44100;

        /// <summary>Sine whose frequency falls exponentially from <paramref name="f0"/> to <paramref name="f1"/>.</summary>
        private static float Sweep(float t, float f0, float f1, float rate) =>
            Mathf.Sin(2f * Mathf.PI * (f1 * t + (f0 - f1) * (1f - Mathf.Exp(-rate * t)) / rate));

        private static AudioClip Clip(string name, float[] data)
        {
            var clip = AudioClip.Create(name, data.Length, 1, Rate, false);
            clip.SetData(data, 0);
            return clip;
        }

        private static float[] Render(float seconds, System.Func<float, float, float> sample, float lowPass = 1f)
        {
            var random = new System.Random(11);
            var data = new float[Mathf.CeilToInt(Rate * seconds)];
            var noise = 0f;
            for (var i = 0; i < data.Length; i++)
            {
                var t = (float)i / Rate;
                noise += lowPass * ((float)(random.NextDouble() * 2.0 - 1.0) - noise);
                var attack = Mathf.Min(1f, i / (Rate * 0.002f));
                var release = Mathf.Min(1f, (data.Length - i) / (Rate * 0.02f));
                data[i] = Mathf.Clamp(sample(t, noise), -1f, 1f) * attack * release;
            }
            return data;
        }

        private static AudioClip Drum() => Clip("Moment Drum", Render(0.5f,
            (t, n) => Sweep(t, 170f, 65f, 18f) * 0.9f * Mathf.Exp(-t * 9f) + n * 0.5f * Mathf.Exp(-t * 60f), 0.4f));

        private static AudioClip Impact() => Clip("Moment Impact", Render(0.9f,
            (t, n) => Sweep(t, 130f, 45f, 10f) * 0.85f * Mathf.Exp(-t * 5f) + n * 0.7f * Mathf.Exp(-t * 16f), 0.25f));

        private static AudioClip Bass() => Clip("Moment Bass", Render(1.8f,
            (t, n) => Sweep(t, 95f, 32f, 4f) * 0.95f * Mathf.Exp(-t * 2.2f) + n * 0.8f * Mathf.Exp(-t * 22f), 0.15f));

        private static AudioClip Whoosh()
        {
            const float seconds = 0.3f;
            var random = new System.Random(5);
            var data = new float[Mathf.CeilToInt(Rate * seconds)];
            var noise = 0f;
            for (var i = 0; i < data.Length; i++)
            {
                var p = (float)i / data.Length;
                noise += (0.03f + 0.4f * p) * ((float)(random.NextDouble() * 2.0 - 1.0) - noise);
                data[i] = noise * 1.6f * Mathf.Sin(Mathf.PI * p) * p;
            }
            return Clip("Moment Whoosh", data);
        }
    }
}
