using System.Collections.Generic;
using System.Linq;
using SpellGame.Protocol;
using UnityEngine;
using UnityEngine.Rendering;

namespace SpellGame.Game
{
    /// <summary>
    /// The end-of-match moment in the room, above the results panel (<see cref="MatchMenu"/> keeps the Rematch and Main menu
    /// buttons): a big VICTORY / DEFEAT / DRAW banner about 2 m away with the reason and each fighter's match stats,
    /// confetti bursts for a win, falling ash for a loss, and a gold crown ring over the winner's head. Stats are counted
    /// on the client from the server's `damage`, `impact` and `spell` events between the countdown and the end.
    /// </summary>
    public sealed class EndGameView : MonoBehaviour
    {
        [SerializeField] private GameClient gameClient;
        [SerializeField] private OVRCameraRig cameraRig;
        [Tooltip("Unlit material the banner and particle materials are copied from (only its colour is changed).")]
        [SerializeField] private Material baseMaterial;

        [Header("Placement")]
        [SerializeField] private float bannerDistance = 2.2f;
        [SerializeField] private float bannerLift = 0.3f;
        [Tooltip("Degrees off your view before the banner glides back in front of you.")]
        [SerializeField] private float refollowAngle = 45f;
        [SerializeField] private float followSpeed = 2.5f;

        [Header("Celebration")]
        [SerializeField] private float confettiInterval = 0.7f;
        [SerializeField] private int confettiBursts = 6;
        [SerializeField] private float crownHeight = 0.62f;

        private static readonly Color VictoryColor = new(1f, 0.8f, 0.25f);
        private static readonly Color DefeatColor = new(0.85f, 0.25f, 0.25f);
        private static readonly Color NeutralColor = new(0.75f, 0.85f, 1f);
        private static readonly Color BannerBack = new(0.05f, 0.06f, 0.11f);
        private static readonly Color[] ConfettiColors =
        {
            new(1f, 0.8f, 0.25f), new(1f, 0.35f, 0.3f), new(0.3f, 0.6f, 1f), new(0.35f, 1f, 0.6f), new(0.9f, 0.45f, 1f),
        };

        private sealed class Stats
        {
            public float Dealt;
            public int Hits;
            public int Throws;
            public int FireballHits;
            public int Blocks;
            public float BiggestHit;
        }

        private readonly Dictionary<string, Stats> _stats = new();
        private MatchSnapshot _match = new();
        private StateMessage _state;
        private string _lastPhase;
        private bool _counting;

        private Transform _banner;
        private Material _bannerBackMaterial;
        private Material _accentMaterial;
        private TextMesh _title;
        private TextMesh _subtitle;
        private TextMesh _body;
        private Vector3 _bannerTarget;
        private float _shownAt;
        private float _showAt = float.PositiveInfinity;
        private Color _titleColor;
        private bool _won;
        private int _burstsLeft;
        private float _nextBurst;
        private ParticleSystem _ash;
        private Transform _crown;
        private Material[] _confettiMaterials;

        private static Mesh _quadMesh;

        private static Mesh QuadMesh
        {
            get
            {
                if (_quadMesh != null)
                    return _quadMesh;
                var primitive = GameObject.CreatePrimitive(PrimitiveType.Quad);
                _quadMesh = primitive.GetComponent<MeshFilter>().sharedMesh;
                Destroy(primitive);
                return _quadMesh;
            }
        }

        private Transform Eye => cameraRig != null ? cameraRig.centerEyeAnchor : Camera.main.transform;

        private string Me => gameClient.PlayerId;

        private void Awake()
        {
            _confettiMaterials = ConfettiColors.Select(Tinted).ToArray();
            CreateBanner();
            CreateCrown();
            _ash = CreateParticles("Ash", transform, Tinted(new Color(0.35f, 0.35f, 0.4f)));
            ConfigureAsh(_ash);
        }

        private void OnEnable()
        {
            gameClient.StateReceived += OnState;
            gameClient.DamageReceived += OnDamage;
            gameClient.ImpactReceived += OnImpact;
            gameClient.SpellReceived += OnSpell;
        }

        private void OnDisable()
        {
            gameClient.StateReceived -= OnState;
            gameClient.DamageReceived -= OnDamage;
            gameClient.ImpactReceived -= OnImpact;
            gameClient.SpellReceived -= OnSpell;
        }

        // ---------------------------------------------------------------- stats

        private Stats StatsFor(string playerId)
        {
            if (!_stats.TryGetValue(playerId, out var stats))
                _stats[playerId] = stats = new Stats();
            return stats;
        }

        private void OnDamage(DamageMessage damage)
        {
            if (!_counting || damage.SourceId == null)
                return;
            var stats = StatsFor(damage.SourceId);
            stats.Dealt += damage.Amount;
            stats.Hits++;
            stats.BiggestHit = Mathf.Max(stats.BiggestHit, damage.Amount);
            if (damage.Kind == SpellKind.Fireball)
                stats.FireballHits++;
        }

        private void OnImpact(ImpactMessage impact)
        {
            if (_counting && impact.TargetId != null && impact.Reason is ImpactReason.Blocked or ImpactReason.Parried)
                StatsFor(impact.TargetId).Blocks++;
        }

        private void OnSpell(SpellMessage spell)
        {
            if (_counting && spell.Spell == SpellKind.Fireball && spell.State == SpellState.Cast && spell.CasterId != null)
                StatsFor(spell.CasterId).Throws++;
        }

        // ---------------------------------------------------------------- phases

        private void OnState(StateMessage state)
        {
            _state = state;
            _match = state.Match ?? new MatchSnapshot();
            if (_match.Phase == _lastPhase)
                return;
            var from = _lastPhase;
            _lastPhase = _match.Phase;

            if (_match.Phase == MatchPhase.Countdown)
                _stats.Clear();
            // The KO hit's damage event arrives in the same tick as the `ended` state, before it.
            _counting = _match.Phase is MatchPhase.Countdown or MatchPhase.Playing;

            // After a K.O. the banner waits for the K.O. moment (MatchMomentsView).
            if (_match.Phase == MatchPhase.Ended && from == MatchPhase.Playing)
                _showAt = Time.unscaledTime + (_match.Reason == MatchEndReason.Ko ? MatchMomentsView.KoBeatSeconds : 0f);
            else if (_match.Phase != MatchPhase.Ended)
                Hide();
        }

        private void Show()
        {
            var isFighter = Me != null && _match.Fighters.Contains(Me);
            string title;
            if (_match.Reason == MatchEndReason.Quit)
                (title, _titleColor) = ("MATCH ENDED", NeutralColor);
            else if (_match.Winner == null)
                (title, _titleColor) = ("DRAW", NeutralColor);
            else if (_match.Winner == Me)
                (title, _titleColor) = ("VICTORY!", VictoryColor);
            else if (isFighter)
                (title, _titleColor) = ("DEFEAT", DefeatColor);
            else
                (title, _titleColor) = ($"{NameOf(_match.Winner)} WINS", VictoryColor);
            _won = _match.Winner != null && (_match.Winner == Me || !isFighter);

            _title.text = title;
            _title.color = _titleColor;
            _subtitle.text = _match.Reason switch
            {
                MatchEndReason.Ko => "KNOCKOUT",
                MatchEndReason.Time => _match.SuddenDeath ? "SUDDEN DEATH" : "TIME'S UP · MOST HP WINS",
                MatchEndReason.Quit => $"ENDED BY {NameOf(_match.EndedBy).ToUpperInvariant()}",
                MatchEndReason.Disconnect => "OPPONENT DISCONNECTED",
                _ => "",
            };
            _body.text = string.Join("\n", _match.Fighters.Select(StatsLine));
            _accentMaterial.SetColor("_BaseColor", _titleColor);

            _bannerTarget = BannerSpot();
            _banner.position = _bannerTarget;
            FaceViewer(_banner);
            _banner.gameObject.SetActive(true);
            _shownAt = Time.time;

            _burstsLeft = _won ? confettiBursts : 0;
            _nextBurst = Time.time + 0.15f;
            if (_match.Winner != null && _match.Winner != Me && isFighter && _match.Reason != MatchEndReason.Quit)
                _ash.Play();
        }

        private void Hide()
        {
            _showAt = float.PositiveInfinity;
            _banner.gameObject.SetActive(false);
            _crown.gameObject.SetActive(false);
            _burstsLeft = 0;
            _ash.Stop(true, ParticleSystemStopBehavior.StopEmitting);
        }

        private string NameOf(string playerId) =>
            playerId == null ? "?" : playerId == Me ? "You" : playerId == _match.AiId ? "AI mage" : playerId;

        private string StatsLine(string fighter)
        {
            var stats = StatsFor(fighter);
            var hp = _state?.Players.FirstOrDefault(p => p.PlayerId == fighter)?.Hp ?? 0f;
            var accuracy = stats.Throws > 0 ? $"  ·  {Mathf.RoundToInt(100f * stats.FireballHits / stats.Throws)}% aim" : "";
            return $"{NameOf(fighter)}:  {Mathf.Max(0f, hp):0} HP left  ·  {stats.Dealt:0} dmg in {stats.Hits} hits" +
                   $"{accuracy}  ·  {stats.Blocks} blocks  ·  best {stats.BiggestHit:0}";
        }

        // ---------------------------------------------------------------- per frame

        private void Update()
        {
            if (Time.unscaledTime >= _showAt)
            {
                _showAt = float.PositiveInfinity;
                Show();
            }
            if (!_banner.gameObject.activeSelf)
                return;

            FollowView();
            var age = Time.time - _shownAt;
            var pop = age < 0.5f ? EaseOutBack(age / 0.5f) : 1f;
            _banner.localScale = Vector3.one * Mathf.Max(0.01f, pop);
            var shimmer = _won ? 0.15f * Mathf.Sin(Time.time * 4f) : 0f;
            _title.color = Color.Lerp(_titleColor, Color.white, Mathf.Max(0f, shimmer));
            _ash.transform.position = Eye.position + Vector3.up * 1.2f;

            if (_burstsLeft > 0 && Time.time >= _nextBurst)
            {
                _burstsLeft--;
                _nextBurst = Time.time + confettiInterval;
                var side = Random.Range(-0.6f, 0.6f);
                Confetti(_banner.position + _banner.right * side + Vector3.up * Random.Range(0.1f, 0.4f));
            }

            UpdateCrown();
        }

        private void UpdateCrown()
        {
            var winner = _match.Winner;
            BodyJoints joints = null;
            var visible = winner != null && winner != Me && _match.Reason != MatchEndReason.Quit &&
                          gameClient.TryGetJoints(winner, out joints) && joints.Head != null;
            _crown.gameObject.SetActive(visible);
            if (!visible)
                return;
            _crown.position = joints.Head.Position + Vector3.up * (crownHeight + 0.03f * Mathf.Sin(Time.time * 3f));
            _crown.rotation = Quaternion.Euler(0f, Time.time * 60f, 0f);
        }

        private static float EaseOutBack(float t)
        {
            const float c = 1.70158f;
            t -= 1f;
            return 1f + (c + 1f) * t * t * t + c * t * t;
        }

        // ---------------------------------------------------------------- placement

        private Vector3 FlatForward()
        {
            var forward = Eye.forward;
            forward.y = 0f;
            return forward.sqrMagnitude > 1e-4f ? forward.normalized : Vector3.forward;
        }

        private Vector3 BannerSpot() => Eye.position + FlatForward() * bannerDistance + Vector3.up * bannerLift;

        private void FollowView()
        {
            var toBanner = _bannerTarget - Eye.position;
            toBanner.y = 0f;
            if (toBanner.sqrMagnitude < 1e-4f || Vector3.Angle(FlatForward(), toBanner) > refollowAngle)
                _bannerTarget = BannerSpot();
            var t = 1f - Mathf.Exp(-followSpeed * Time.deltaTime);
            _banner.position = Vector3.Lerp(_banner.position, _bannerTarget, t);
            FaceViewer(_banner);
        }

        private void FaceViewer(Transform root)
        {
            var away = root.position - Eye.position;
            away.y *= 0.5f;
            if (away.sqrMagnitude > 1e-6f)
                root.rotation = Quaternion.LookRotation(away);
        }

        // ---------------------------------------------------------------- construction

        private void CreateBanner()
        {
            _banner = new GameObject("End Banner").transform;
            _banner.SetParent(transform, false);
            _bannerBackMaterial = Tinted(BannerBack);
            _accentMaterial = Tinted(VictoryColor);

            var back = CreateQuad("Back", _banner, _bannerBackMaterial);
            back.localScale = new Vector3(1.5f, 0.5f, 1f);
            var top = CreateQuad("Accent Top", _banner, _accentMaterial);
            top.localPosition = new Vector3(0f, 0.25f, -0.001f);
            top.localScale = new Vector3(1.5f, 0.012f, 1f);
            var bottom = CreateQuad("Accent Bottom", _banner, _accentMaterial);
            bottom.localPosition = new Vector3(0f, -0.25f, -0.001f);
            bottom.localScale = new Vector3(1.5f, 0.012f, 1f);

            _title = CreateText("Title", _banner, new Vector3(0f, 0.13f, -0.004f), 0.034f, FontStyle.Bold);
            _subtitle = CreateText("Reason", _banner, new Vector3(0f, 0.02f, -0.004f), 0.011f, FontStyle.Bold);
            _subtitle.color = new Color(0.85f, 0.88f, 0.95f);
            _body = CreateText("Stats", _banner, new Vector3(0f, -0.13f, -0.004f), 0.0085f, FontStyle.Normal);
            _body.color = Color.white;
            _banner.gameObject.SetActive(false);
        }

        private void CreateCrown()
        {
            _crown = new GameObject("Winner Crown").transform;
            _crown.SetParent(transform, false);
            var gold = Tinted(VictoryColor);
            const int points = 7;
            for (var i = 0; i < points; i++)
            {
                var angle = i * Mathf.PI * 2f / points;
                var spot = new Vector3(Mathf.Cos(angle), 0f, Mathf.Sin(angle)) * 0.14f;
                var gem = SpellVfx.CreateOrb($"Point {i}", _crown, gold, 0.045f);
                gem.localPosition = spot;
            }
            _crown.gameObject.SetActive(false);
        }

        private void Confetti(Vector3 at)
        {
            var root = new GameObject("Confetti").transform;
            root.position = at;
            foreach (var material in _confettiMaterials)
            {
                var particles = CreateParticles("Pieces", root, material);
                var main = particles.main;
                main.loop = false;
                main.duration = 0.1f;
                main.startLifetime = new ParticleSystem.MinMaxCurve(1.4f, 2.2f);
                main.startSpeed = new ParticleSystem.MinMaxCurve(1.2f, 2.6f);
                main.startSize = new ParticleSystem.MinMaxCurve(0.015f, 0.03f);
                main.startRotation = new ParticleSystem.MinMaxCurve(-Mathf.PI, Mathf.PI);
                main.gravityModifier = 0.35f;
                var emission = particles.emission;
                emission.rateOverTime = 0f;
                emission.SetBursts(new[] { new ParticleSystem.Burst(0f, 14) });
                var shape = particles.shape;
                shape.shapeType = ParticleSystemShapeType.Sphere;
                shape.radius = 0.05f;
                var rotation = particles.rotationOverLifetime;
                rotation.enabled = true;
                rotation.z = new ParticleSystem.MinMaxCurve(-6f, 6f);
                particles.Play();
            }
            Destroy(root.gameObject, 2.5f);
        }

        private static void ConfigureAsh(ParticleSystem ash)
        {
            var main = ash.main;
            main.loop = true;
            main.startLifetime = new ParticleSystem.MinMaxCurve(2.5f, 3.5f);
            main.startSpeed = 0f;
            main.startSize = new ParticleSystem.MinMaxCurve(0.006f, 0.014f);
            main.gravityModifier = 0.03f;
            main.simulationSpace = ParticleSystemSimulationSpace.World;
            var emission = ash.emission;
            emission.rateOverTime = 40f;
            var shape = ash.shape;
            shape.shapeType = ParticleSystemShapeType.Box;
            shape.scale = new Vector3(2.5f, 0.1f, 2.5f);
            ash.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
        }

        private static ParticleSystem CreateParticles(string name, Transform parent, Material material)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            var particles = go.AddComponent<ParticleSystem>();
            particles.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
            var main = particles.main;
            main.playOnAwake = false;
            main.simulationSpace = ParticleSystemSimulationSpace.World;
            var renderer = go.GetComponent<ParticleSystemRenderer>();
            renderer.sharedMaterial = material;
            renderer.shadowCastingMode = ShadowCastingMode.Off;
            renderer.receiveShadows = false;
            return particles;
        }

        private TextMesh CreateText(string name, Transform parent, Vector3 localPosition, float size, FontStyle style)
        {
            var label = new GameObject(name).AddComponent<TextMesh>();
            label.transform.SetParent(parent, false);
            label.transform.localPosition = localPosition;
            label.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            label.GetComponent<MeshRenderer>().sharedMaterial = label.font.material;
            label.anchor = TextAnchor.MiddleCenter;
            label.alignment = TextAlignment.Center;
            label.characterSize = size;
            label.fontSize = 64;
            label.fontStyle = style;
            return label;
        }

        private static Transform CreateQuad(string name, Transform parent, Material material)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            go.AddComponent<MeshFilter>().sharedMesh = QuadMesh;
            var renderer = go.AddComponent<MeshRenderer>();
            renderer.sharedMaterial = material;
            renderer.shadowCastingMode = ShadowCastingMode.Off;
            renderer.receiveShadows = false;
            return go.transform;
        }

        private Material Tinted(Color color)
        {
            var material = new Material(baseMaterial);
            material.SetColor("_BaseColor", color);
            return material;
        }
    }
}
