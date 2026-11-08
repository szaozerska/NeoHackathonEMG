using System.Collections.Generic;
using System.Linq;
using SpellGame.Protocol;
using TMPro;
using UnityEngine;
using UnityEngine.Rendering;

namespace SpellGame.Game
{
    /// <summary>
    /// The end-of-match moment in the room, above the results panel (<see cref="MatchMenu"/> keeps the Rematch and Main menu
    /// buttons): a big VICTORY / DEFEAT / DRAW crystal banner (<see cref="UiStyle"/>) about 2 m away with the reason and a
    /// result card per fighter (stats and award badges), confetti bursts for a win, falling ash for a loss, and a crown
    /// ring over the winner's head. Stats are counted
    /// on the client from the server's `damage`, `impact` and `spell` events between the countdown and the end.
    /// </summary>
    public sealed class EndGameView : MonoBehaviour
    {
        [SerializeField] private GameClient gameClient;
        [SerializeField] private OVRCameraRig cameraRig;
        [Tooltip("Unlit material the particle and crown materials are copied from (only its colour is changed).")]
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

        private const float BannerWidth = 1.5f;
        private const float BannerPad = 0.06f;
        private const float CardGap = 0.04f;
        private const float CardPad = 0.035f;

        private sealed class Stats
        {
            public float Dealt;
            public int Hits;
            public int Throws;
            public int FireballHits;
            public int Blocks;
            public float BiggestHit;
            public float Taken;
        }

        private readonly Dictionary<string, Stats> _stats = new();
        private MatchSnapshot _match = new();
        private StateMessage _state;
        private string _lastPhase;
        private bool _counting;

        private Transform _banner;
        private UiStyle.Crystal _bannerBack;
        private TextMeshPro _title;
        private TextMeshPro _subtitle;
        private Transform _cards;
        private readonly List<Material> _cardMaterials = new();
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

        private Transform Eye => cameraRig != null ? cameraRig.centerEyeAnchor : Camera.main.transform;

        private string Me => gameClient.PlayerId;

        private void Awake()
        {
            _confettiMaterials = UiStyle.Confetti.Select(Tinted).ToArray();
            CreateBanner();
            CreateCrown();
            _ash = CreateParticles("Ash", transform, Tinted(UiStyle.Ash));
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
            if (!_counting)
                return;
            if (damage.TargetId != null)
                StatsFor(damage.TargetId).Taken += damage.Amount;
            if (damage.SourceId == null)
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
                (title, _titleColor) = ("MATCH ENDED", UiStyle.Text);
            else if (_match.Winner == null)
                (title, _titleColor) = ("DRAW", UiStyle.Text);
            else if (_match.Winner == Me)
                (title, _titleColor) = ("VICTORY!", UiStyle.Text);
            else if (isFighter)
                (title, _titleColor) = ("DEFEAT", UiStyle.TextDim);
            else
                (title, _titleColor) = ($"{NameOf(_match.Winner)} WINS", UiStyle.Text);
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
            LayoutBanner(BuildCards());

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

        // ---------------------------------------------------------------- result cards

        /// <summary>
        /// One slanted crystal card per fighter, Smash style: big place number, name in their colour, ink stats, award
        /// tags. The winner (then most HP left) comes first; later places sit a little lower and smaller. Returns the height.
        /// </summary>
        private float BuildCards()
        {
            foreach (Transform child in _cards)
                Destroy(child.gameObject);
            UiStyle.DestroyAll(_cardMaterials);
            var fighters = _match.Fighters
                .OrderByDescending(f => f == _match.Winner)
                .ThenByDescending(HpOf)
                .ToList();
            if (fighters.Count == 0)
                return 0f;

            var awards = Awards(fighters);
            var width = Mathf.Min(0.58f, (BannerWidth - CardGap * (fighters.Count - 1)) / fighters.Count);
            var cards = new List<(Transform Root, string Fighter)>();
            var height = 0f;
            for (var i = 0; i < fighters.Count; i++)
            {
                var card = new GameObject($"Card {fighters[i]}").transform;
                card.SetParent(_cards, false);
                var place = i == 0 || _match.Winner != null ? i + 1 : 1;
                card.localPosition = new Vector3((i - (fighters.Count - 1) * 0.5f) * (width + CardGap), i > 0 ? -0.03f : 0f, -0.002f);
                card.localScale = Vector3.one * (i > 0 ? 0.92f : 1f);
                height = Mathf.Max(height, FillCard(card, fighters[i], place, width, awards[fighters[i]]));
                cards.Add((card, fighters[i]));
            }
            foreach (var (root, fighter) in cards)
            {
                // Follow the slant: shift each row by how far it sits above the card's bottom edge.
                foreach (Transform child in root)
                {
                    var p = child.localPosition;
                    child.localPosition = new Vector3(p.x + UiStyle.Skew * (p.y + height * 0.5f), p.y, p.z);
                }
                var style = fighter == _match.Winner ? UiStyle.Pulsing(UiStyle.Card, 0.35f) : UiStyle.Card;
                UiStyle.CreateCrystal("Back", root, new Vector2(width, height), style, new Vector3(0f, -height * 0.5f, 0f),
                    UiStyle.SortSurface, _cardMaterials);
            }
            return height + 0.03f;
        }

        private float HpOf(string fighter) =>
            Mathf.Max(0f, _state?.Players.FirstOrDefault(p => p.PlayerId == fighter)?.Hp ?? 0f);

        /// <summary>Lays a card's contents out downwards from its top edge (the card's origin); returns the height used.</summary>
        private float FillCard(Transform card, string fighter, int place, float width, List<string> awards)
        {
            var stats = StatsFor(fighter);
            var inner = width - 2f * CardPad;
            var left = -width * 0.5f + CardPad;
            var y = -CardPad * 0.6f;

            var number = UiStyle.CreateText("Place", card, place.ToString(), Vector3.zero, 0.13f, UiStyle.Text, display: true,
                look: UiStyle.Look.Title, alignment: TextAlignmentOptions.Left, width: 0.12f);
            var numberWidth = UiStyle.Width(number);
            var numberHeight = UiStyle.Height(number);
            number.transform.localPosition = new Vector3(left + 0.06f, y - numberHeight * 0.5f, -0.004f);
            var name = UiStyle.CreateText("Name", card, NameOf(fighter).ToUpperInvariant(), Vector3.zero, 0.055f,
                UiStyle.PlayerColor(fighter), display: true, alignment: TextAlignmentOptions.Left, width: inner);
            name.transform.localPosition = new Vector3(numberWidth + 0.015f, y - numberHeight * 0.6f, -0.004f);
            y -= numberHeight * 0.9f;

            TextMeshPro Row(string label, string text, float size)
            {
                var row = UiStyle.CreateText(label, card, text, Vector3.zero, size, UiStyle.Ink, look: UiStyle.Look.Ink,
                    alignment: TextAlignmentOptions.Left, width: inner);
                var h = UiStyle.Height(row);
                row.transform.localPosition = new Vector3(0f, y - h * 0.5f, -0.004f);
                y -= h;
                return row;
            }

            var aim = stats.Throws > 0 ? $"{Mathf.RoundToInt(100f * stats.FireballHits / stats.Throws)}%" : "–";
            Row("Stats", $"{HpOf(fighter):0} HP · {stats.Dealt:0} dmg · {aim} aim", 0.034f);
            Row("More Stats", $"{stats.Hits} hits · {stats.Blocks} blocks · best hit {stats.BiggestHit:0}", 0.025f);

            if (awards.Count > 0)
            {
                const float badgeHeight = 0.036f;
                const float badgeGap = 0.012f;
                y -= 0.015f;
                var x = left;
                foreach (var award in awards)
                {
                    var text = UiStyle.CreateText("Award", card, award, Vector3.zero, 0.022f, UiStyle.Ink, display: true,
                        look: UiStyle.Look.Ink, spacing: 3f);
                    var badgeWidth = UiStyle.Width(text) + 0.03f;
                    if (x > left && x + badgeWidth > left + inner)
                    {
                        x = left;
                        y -= badgeHeight + badgeGap;
                    }
                    var center = new Vector3(x + badgeWidth * 0.5f, y - badgeHeight * 0.5f, 0f);
                    text.transform.localPosition = center + new Vector3(0f, 0.001f, -0.006f);
                    UiStyle.CreateCrystal("Badge", card, new Vector2(badgeWidth, badgeHeight), UiStyle.Badge, center + new Vector3(0f, 0f, -0.003f),
                        UiStyle.SortBar, _cardMaterials);
                    x += badgeWidth + badgeGap;
                }
                y -= badgeHeight;
            }
            return CardPad - y;
        }

        /// <summary>Cheap awards from the counted stats: best aim (3+ throws), most blocks, and no damage taken in a full match.</summary>
        private Dictionary<string, List<string>> Awards(List<string> fighters)
        {
            var awards = fighters.ToDictionary(f => f, _ => new List<string>());

            void Best(string award, System.Func<Stats, float> score)
            {
                var ranked = fighters.Select(f => (Fighter: f, Score: score(StatsFor(f)))).OrderByDescending(r => r.Score).ToList();
                if (ranked[0].Score > 0f && (ranked.Count == 1 || ranked[1].Score < ranked[0].Score))
                    awards[ranked[0].Fighter].Add(award);
            }

            Best("SHARPSHOOTER", s => s.Throws >= 3 ? (float)s.FireballHits / s.Throws : 0f);
            Best("IRON WALL", s => s.Blocks);
            if (_match.Reason is MatchEndReason.Ko or MatchEndReason.Time)
                foreach (var fighter in fighters.Where(f => StatsFor(f).Taken <= 0f))
                    awards[fighter].Add("UNTOUCHABLE");
            return awards;
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
            _title.color = Color.Lerp(_titleColor, UiStyle.Accent, Mathf.Max(0f, shimmer) * 2f);
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
            _bannerBack = UiStyle.CreateCrystal("Title Card", _banner, new Vector2(1f, 0.3f), UiStyle.Panel, Vector3.zero);
            _title = UiStyle.CreateText("Title", _banner, "", new Vector3(0f, 0f, -0.004f), 0.17f, UiStyle.Text, display: true,
                look: UiStyle.Look.Title, width: BannerWidth, spacing: 2f);
            _subtitle = UiStyle.CreateText("Reason", _banner, "", new Vector3(0f, 0f, -0.004f), 0.036f, UiStyle.Ink, display: true,
                look: UiStyle.Look.Ink, width: BannerWidth, spacing: 6f);
            _cards = new GameObject("Cards").transform;
            _cards.SetParent(_banner, false);
            _banner.gameObject.SetActive(false);
        }

        /// <summary>Big slanted title card (title + reason) on top, the result cards under it.</summary>
        private void LayoutBanner(float cardsHeight)
        {
            var titleHeight = UiStyle.Height(_title);
            var subtitleHeight = UiStyle.Height(_subtitle);
            var cardHeight = titleHeight + subtitleHeight + BannerPad;
            var cardWidth = Mathf.Max(0.9f, Mathf.Max(UiStyle.Width(_title), UiStyle.Width(_subtitle)) + 0.25f);
            var height = cardHeight + (cardsHeight > 0f ? CardGap + cardsHeight : 0f);
            var top = height * 0.5f;
            _bannerBack.Transform.localPosition = new Vector3(0f, top - cardHeight * 0.5f, 0f);
            _bannerBack.Resize(new Vector2(cardWidth, cardHeight));
            var y = top - BannerPad * 0.5f;
            _title.transform.localPosition = new Vector3(0f, y - titleHeight * 0.5f, -0.004f);
            y -= titleHeight;
            _subtitle.transform.localPosition = new Vector3(-UiStyle.Skew * subtitleHeight, y - subtitleHeight * 0.5f, -0.004f);
            _cards.localPosition = new Vector3(0f, top - cardHeight - CardGap, 0f);
        }

        private void CreateCrown()
        {
            _crown = new GameObject("Winner Crown").transform;
            _crown.SetParent(transform, false);
            var gold = Tinted(UiStyle.Rim);
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

        private Material Tinted(Color color)
        {
            var material = new Material(baseMaterial);
            material.SetColor("_BaseColor", color);
            return material;
        }
    }
}
