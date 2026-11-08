using System;
using System.Collections.Generic;
using System.Linq;
using SpellGame.Protocol;
using TMPro;
using UnityEngine;
using UnityEngine.Rendering;

namespace SpellGame.Game
{
    /// <summary>
    /// The match menus (architecture.md §5.2), all in passthrough: small crystal panels (<see cref="UiStyle"/>) placed in the room about a metre in
    /// front, a little below eye level, never a full-view or opaque screen. A panel stays put while you look around and
    /// glides back in front of you when it leaves your view (lazy follow), so nothing is glued to your head.
    /// <list type="bullet">
    /// <item>Point with the controller in the hand without the band and pull its trigger (the band hand's trigger is the
    /// snap stand-in); without controllers, look at a button for a moment to press it.</item>
    /// <item>Menu button (left controller): during a match, end it; otherwise bring the panel back in front of you.</item>
    /// </list>
    /// Screens: mode → length → how to cast (first time) → ready → timer badge → results. The 3-2-1-FIGHT! and K.O.
    /// moments are <see cref="MatchMomentsView"/>; after a K.O. the results wait for it.
    /// The server owns the flow; this only sends intents and renders <see cref="MatchSnapshot"/>.
    /// </summary>
    public sealed class MatchMenu : MonoBehaviour
    {
        [SerializeField] private GameClient gameClient;
        [SerializeField] private OVRCameraRig cameraRig;
        [SerializeField] private SharedSpaceAligner spaceAligner;
        [Tooltip("Unlit material the pointer material is copied from (only its colour is changed).")]
        [SerializeField] private Material baseMaterial;

        [Header("Placement")]
        [SerializeField] private float panelDistance = 1.1f;
        [SerializeField] private float panelDrop = 0.05f;
        [Tooltip("The results buttons sit lower, under the end-of-match banner.")]
        [SerializeField] private float resultsPanelDrop = 0.24f;
        [Tooltip("Degrees off your view before a panel glides back in front of you.")]
        [SerializeField] private float refollowAngle = 35f;
        [SerializeField] private float followSpeed = 4f;

        [Header("Input")]
        [SerializeField] private float dwellSeconds = 1.2f;
        [SerializeField] private float pointerLength = 3f;

        [Header("Layout (metres)")]
        [SerializeField] private float panelWidth = 0.62f;
        [SerializeField] private float buttonHeight = 0.075f;
        [SerializeField] private float buttonGap = 0.018f;
        [SerializeField] private float textScale = 1f;

        private static readonly float[] Durations = { 60f, 120f, 300f };

        private const float DwellBarInset = 0.03f;

        private enum Kind { Primary, Secondary }

        private enum View { None, Connection, Mode, Duration, Controls, Ready, Pause, Results, Settings }

        private sealed class Button
        {
            public Rect Rect;
            public UiStyle.Crystal Back;
            public UiStyle.Crystal Dwell;
            public UiStyle.CrystalStyle Style;
            public Action OnPress;
        }

        private sealed class Panel
        {
            public Transform Root;
            public TextMeshPro Footer;
            public string Key;
            public readonly List<Button> Buttons = new();
            public readonly List<Material> Materials = new();
            public Vector3 Target;
            public bool Placed;
        }

        private Panel _panel;
        private View _view = View.Mode;
        private View _controlsReturn = View.Mode;
        private bool _seenControls;

        private const string MenuColoursPref = "SpellGame.MenuColours";
        private UiTheme[] _menuThemes;
        private int _menuColours;
        private string _pendingMode = MatchMode.Solo;
        private MatchSnapshot _match = new();
        private StateMessage _state;
        private string _lastPhase;
        private int _stateVersion;
        private int _keyStateVersion = -1;
        private View _keyView;
        private string _key;
        private ConnectionState _keyConnection;

        private Button _hovered;
        private float _hoverStart;
        private bool _dwellFired;
        private LineRenderer _pointer;
        private Transform _pointerDot;
        private float _hapticStop;
        private OVRInput.Controller _hapticController;

        private Transform _timerBadge;
        private UiStyle.Crystal _timerBack;
        private TextMeshPro _timerText;
        private bool _timerPlaced;
        private float _timerAt;
        private float _resultsAt;

        private AudioSource _audio;
        private AudioClip _tick, _beep, _end;
        private AudioClip _toneTick, _toneBeep, _toneEnd;
        private int _themeVersion, _panelThemeVersion;

        private Transform Eye => cameraRig != null ? cameraRig.centerEyeAnchor : Camera.main.transform;

        private string Me => gameClient.PlayerId;
        private bool IsFighter => Me != null && _match.Fighters.Contains(Me);

        /// <summary>The connection screen covers every other screen until the server has welcomed this headset.</summary>
        private View ShownView => gameClient.Connection != ConnectionState.Connected ? View.Connection
            : _view == View.Results && Time.unscaledTime < _resultsAt ? View.None
            : _view;

        private void Awake()
        {
            if (spaceAligner == null)
                spaceAligner = FindAnyObjectByType<SharedSpaceAligner>();
            _audio = gameObject.AddComponent<AudioSource>();
            _audio.playOnAwake = false;
            _audio.spatialBlend = 0f;
            CreatePointer();
            CreateTimerBadge();
            LoadMenuColours();
            ApplyTheme();
        }

        /// <summary>Theme sounds (synthesised tones where the theme has none), pointer colour, and a rebuilt panel.</summary>
        private void ApplyTheme()
        {
            var sounds = UiStyle.Sounds;
            _tick = sounds.Hover != null ? sounds.Hover : _toneTick ??= Tone("Tick", 1400f, 0.03f, 0.15f);
            _beep = sounds.Press != null ? sounds.Press : _toneBeep ??= Tone("Beep", 660f, 0.18f, 0.35f);
            _end = sounds.TimeUp != null ? sounds.TimeUp : _toneEnd ??= Tone("End", 440f, 0.6f, 0.35f);
            _pointer.sharedMaterial.SetColor("_BaseColor", UiStyle.Pointer);
            UiStyle.Restyle(_timerText, true);
            _themeVersion++;
        }

        /// <summary>The menu colours picked in Settings last time (default Smoky Opal, the theme asset's own palette).</summary>
        private void LoadMenuColours()
        {
            var baseTheme = UiStyle.Theme;
            if (baseTheme == null)
                return;
            _menuThemes = new UiTheme[UiPalette.Presets.Length];
            _menuThemes[0] = baseTheme;
            _menuColours = Mathf.Clamp(PlayerPrefs.GetInt(MenuColoursPref, 0), 0, _menuThemes.Length - 1);
            UiStyle.Theme = MenuTheme(_menuColours);
        }

        private void NextMenuColours()
        {
            if (_menuThemes == null)
                return;
            _menuColours = (_menuColours + 1) % _menuThemes.Length;
            PlayerPrefs.SetInt(MenuColoursPref, _menuColours);
            PlayerPrefs.Save();
            UiStyle.Theme = MenuTheme(_menuColours);
        }

        private UiTheme MenuTheme(int index) =>
            _menuThemes[index] ??= _menuThemes[0].WithPalette(UiPalette.Presets[index].Name, UiPalette.Presets[index].Palette);

        private string MenuColoursName => UiPalette.Presets[_menuThemes == null ? 0 : _menuColours].Name;

        private void OnEnable()
        {
            gameClient.StateReceived += OnState;
            gameClient.ConnectionChanged += OnConnectionChanged;
            UiStyle.ThemeChanged += ApplyTheme;
        }

        private void OnDisable()
        {
            gameClient.StateReceived -= OnState;
            gameClient.ConnectionChanged -= OnConnectionChanged;
            UiStyle.ThemeChanged -= ApplyTheme;
        }

        /// <summary>Forgets the last server's match, so a rejoin starts from the menu the new state puts it on.</summary>
        private void OnConnectionChanged(ConnectionState connection)
        {
            if (connection == ConnectionState.Connected)
                return;

            _state = null;
            _match = new MatchSnapshot();
            _lastPhase = null;
            _view = View.Mode;
        }

        private void OnState(StateMessage state)
        {
            _state = state;
            _stateVersion++;
            _match = state.Match ?? new MatchSnapshot();
            if (_match.Phase == _lastPhase)
                return;
            OnPhaseChanged(_lastPhase, _match.Phase);
            _lastPhase = _match.Phase;
        }

        private void OnPhaseChanged(string from, string to)
        {
            switch (to)
            {
                case MatchPhase.Lobby:
                    if (_view is not (View.Duration or View.Controls or View.Settings))
                        _view = View.Mode;
                    break;
                case MatchPhase.Ready:
                    if (!_seenControls && from == MatchPhase.Lobby)
                        ShowControls(View.Ready);
                    else if (_view != View.Controls)
                        _view = View.Ready;
                    break;
                case MatchPhase.Countdown:
                    _view = View.None;
                    break;
                case MatchPhase.Playing:
                    _view = View.None;
                    _timerPlaced = false;
                    _timerAt = Time.unscaledTime + (from == MatchPhase.Countdown ? MatchMomentsView.FightSeconds : 0f);
                    break;
                case MatchPhase.Ended:
                    _view = View.Results;
                    var knockout = from == MatchPhase.Playing && _match.Reason == MatchEndReason.Ko;
                    _resultsAt = Time.unscaledTime + (knockout ? MatchMomentsView.KoBeatSeconds : 0f);
                    if (!knockout)
                        _audio.PlayOneShot(_end);
                    break;
            }
        }

        private void Update()
        {
            if (OVRInput.GetDown(OVRInput.Button.Start))
                OnMenuButton();

            UpdatePanel();
            UpdatePointer();
            UpdateTimer();
            if (_hapticStop > 0f && Time.time >= _hapticStop)
            {
                OVRInput.SetControllerVibration(0f, 0f, _hapticController);
                _hapticStop = 0f;
            }
        }

        private void OnMenuButton()
        {
            var inMatch = _match.Phase is MatchPhase.Countdown or MatchPhase.Playing;
            if (inMatch && IsFighter)
                _view = _view == View.Pause ? View.None : View.Pause;
            else if (_panel != null)
                _panel.Target = PanelSpot();
        }

        // ---------------------------------------------------------------- screens

        private void UpdatePanel()
        {
            var view = ShownView;
            if (view != _keyView || _stateVersion != _keyStateVersion || gameClient.Connection != _keyConnection || _key == null)
            {
                _key = PanelKey(view);
                _keyView = view;
                _keyStateVersion = _stateVersion;
                _keyConnection = gameClient.Connection;
            }
            var key = _key;
            if (_panel != null && _panel.Key == key && _panelThemeVersion == _themeVersion)
            {
                FollowView(_panel);
                UpdateFooter(_panel);
                return;
            }

            var keep = _panel is { Placed: true } ? _panel.Root.position : (Vector3?)null;
            if (_panel != null)
            {
                Destroy(_panel.Root.gameObject);
                UiStyle.DestroyAll(_panel.Materials);
            }
            _panel = null;
            _hovered = null;
            if (view == View.None)
                return;

            _panel = BuildPanel(view, key);
            _panelThemeVersion = _themeVersion;
            _panel.Target = keep ?? PanelSpot();
            _panel.Root.position = _panel.Target;
            _panel.Placed = true;
            FaceViewer(_panel.Root);
            UpdateFooter(_panel);
        }

        /// <summary>Connection, pairing and HP status from <see cref="GameClient"/>, in small text under the panel.</summary>
        private void UpdateFooter(Panel panel)
        {
            if (panel.Footer != null && panel.Footer.text != gameClient.StatusText)
                panel.Footer.text = gameClient.StatusText;
        }

        /// <summary>Changes whenever what the current screen shows changes, so the panel is rebuilt only then.</summary>
        private string PanelKey(View view)
        {
            return view switch
            {
                View.Connection => $"connection|{gameClient.Connection}|{gameClient.ServerEndpoint}",
                View.Ready => $"ready|{Me}|{_match.Mode}|{_match.DurationS}|{string.Join(",", _match.Fighters)}|{string.Join(",", _match.Ready)}|{string.Join(",", AlignedFighters())}",
                View.Results => $"results|{IsFighter}",
                _ => view.ToString(),
            };
        }

        private IEnumerable<string> AlignedFighters() =>
            _match.Fighters.Where(f => _state?.Players.Any(p => p.PlayerId == f && p.Aligned) == true);

        private Panel BuildPanel(View view, string key)
        {
            var panel = new Panel { Key = key, Root = new GameObject($"Menu {view}").transform };
            panel.Root.SetParent(transform, false);
            switch (view)
            {
                case View.Connection:
                    BuildConnection(panel);
                    break;
                case View.Mode:
                    Layout(panel, "SPELL DUEL", "Choose your match",
                        ("1 Player  ·  vs AI", Kind.Primary, () => PickMode(MatchMode.Solo)),
                        ("2 Players", Kind.Primary, () => PickMode(MatchMode.Versus)),
                        ("How to cast", Kind.Secondary, () => ShowControls(View.Mode)),
                        ("Settings", Kind.Secondary, () => _view = View.Settings));
                    break;
                case View.Settings:
                    Layout(panel, "SETTINGS", "Menu colours change menus and buttons only; spells look the same.",
                        ($"Menu colours: {MenuColoursName}", Kind.Primary, NextMenuColours),
                        ("Back", Kind.Secondary, () => _view = View.Mode));
                    break;
                case View.Duration:
                    Layout(panel, _pendingMode == MatchMode.Solo ? "1 PLAYER  ·  vs AI" : "2 PLAYERS", "How long?",
                        ("1 minute", Kind.Primary, () => PickDuration(Durations[0])),
                        ("2 minutes", Kind.Primary, () => PickDuration(Durations[1])),
                        ("5 minutes", Kind.Primary, () => PickDuration(Durations[2])),
                        ("Back", Kind.Secondary, () => _view = View.Mode));
                    break;
                case View.Controls:
                    Layout(panel, "HOW TO CAST", ControlsText(),
                        ("Got it", Kind.Primary, () => { _seenControls = true; _view = _controlsReturn; }));
                    break;
                case View.Ready:
                    BuildReady(panel);
                    break;
                case View.Pause:
                    Layout(panel, "END MATCH?", "Ends it for everyone, with no winner.",
                        ("End match", Kind.Secondary, () => { gameClient.Send(new MatchQuitMessage()); _view = View.None; }),
                        ("Keep fighting", Kind.Primary, () => _view = View.None));
                    break;
                case View.Results:
                    BuildResults(panel);
                    break;
            }
            return panel;
        }

        /// <summary>Cancel while finding or joining the server; Rescan once that has stopped, failed or dropped.</summary>
        private void BuildConnection(Panel panel)
        {
            var server = gameClient.ServerEndpoint;
            (string Label, Kind Kind, Action OnPress) cancel = ("Cancel", Kind.Secondary, gameClient.CancelConnecting);
            (string Label, Kind Kind, Action OnPress) rescan = ("Rescan for servers", Kind.Primary, gameClient.Rescan);
            switch (gameClient.Connection)
            {
                case ConnectionState.Searching:
                    Layout(panel, "FINDING SERVER", "Looking for the game server on this network…", cancel);
                    break;
                case ConnectionState.Connecting:
                    Layout(panel, "CONNECTING", $"Joining the server at {server}…", cancel);
                    break;
                case ConnectionState.Cancelled:
                    Layout(panel, "NOT CONNECTED", "Connection cancelled.", rescan);
                    break;
                case ConnectionState.Unreachable:
                    Layout(panel, "CAN'T REACH SERVER",
                        $"No answer from {server}.\nCheck the server is running and both devices\nare on the same network.", rescan);
                    break;
                case ConnectionState.Disconnected:
                    Layout(panel, "DISCONNECTED", $"Lost the connection to {server}.", rescan);
                    break;
            }
        }

        private void BuildReady(Panel panel)
        {
            var title = $"{(_match.Mode == MatchMode.Solo ? "1 PLAYER  ·  vs AI" : "2 PLAYERS")}  ·  {Minutes(_match.DurationS)}";
            var lines = new List<string>();
            foreach (var fighter in _match.Fighters)
            {
                var name = fighter == Me ? $"{fighter} (you)" : fighter == _match.AiId ? "AI mage" : fighter;
                var aligned = _match.Mode != MatchMode.Versus || AlignedFighters().Contains(fighter);
                var ready = _match.Ready.Contains(fighter)
                    ? "<b>READY</b>"
                    : "not ready";
                lines.Add($"<color={UiStyle.Hex(UiStyle.PlayerColor(fighter))}><b>{name}</b></color>   {ready}{(aligned ? "" : "  ·  not calibrated")}");
            }
            var versusFighter = _match.Mode == MatchMode.Versus && IsFighter;
            var marker = spaceAligner == null || spaceAligner.MarkerAvailable;
            if (versusFighter && !AlignedFighters().Contains(Me))
            {
                if (!_match.Ready.Contains(Me))
                    lines.Add("\nPress I'm ready, then calibrate the room.");
                else if (marker)
                    lines.Add("\n<b>CALIBRATE THE ROOM</b>\n" +
                              "1. Walk to the QR marker on the floor in the middle\n" +
                              "2. Stand next to it and look straight down at it\n" +
                              "3. Hold still until a cyan ring appears on it\n" +
                              "No marker? Touch right controller tips in the middle\n" +
                              "(each pointing at the other), click the LEFT thumbstick.");
                else
                    lines.Add($"\n{spaceAligner?.MarkerProblem}" +
                              "\n<b>CALIBRATE THE ROOM</b> (both players)\n" +
                              "1. Meet in the middle of the room, facing each other\n" +
                              "2. Touch your right controller tips together,\n    each pointing at the other person\n" +
                              "3. Click the LEFT thumbstick and hold still a moment\n" +
                              "4. Walk back to your side");
            }
            else if (versusFighter)
            {
                var waiting = _match.Fighters.Where(f => f != Me && !AlignedFighters().Contains(f)).ToList();
                lines.Add(waiting.Count > 0
                    ? $"\nRoom calibrated. Waiting for {string.Join(", ", waiting)} to calibrate…"
                    : "\nRoom calibrated.");
            }
            if (_match.Mode == MatchMode.Versus && _match.Fighters.Count < 2)
                lines.Add("Waiting for a second headset to join…");
            if (!IsFighter && _match.Fighters.Count > 0)
                lines.Insert(0, $"Watching {string.Join(" vs ", _match.Fighters)}");

            var buttons = new List<(string, Kind, Action)>();
            if (IsFighter)
            {
                var ready = _match.Ready.Contains(Me);
                buttons.Add(ready
                    ? ("Not ready", Kind.Secondary, () => gameClient.Send(new ReadyMessage { Ready = false }))
                    : ("I'm ready!", Kind.Primary, () =>
                    {
                        spaceAligner?.RequestMarkerPermission();
                        gameClient.Send(new ReadyMessage { Ready = true });
                    }));
            }
            buttons.Add(("How to cast", Kind.Secondary, () => ShowControls(View.Ready)));
            buttons.Add(("Back to menu", Kind.Secondary, () => gameClient.Send(new MatchQuitMessage())));
            Layout(panel, title, string.Join("\n", lines), buttons.ToArray());
        }

        /// <summary>Just the choices: <see cref="EndGameView"/>'s banner above shows the result, reason and stats.</summary>
        private void BuildResults(Panel panel)
        {
            var buttons = new List<(string, Kind, Action)>();
            if (IsFighter)
                buttons.Add(("Rematch", Kind.Primary, () => gameClient.Send(new RematchMessage())));
            buttons.Add(("Main menu", Kind.Secondary, () => gameClient.Send(new MatchQuitMessage())));
            Layout(panel, "PLAY AGAIN?", "", buttons.ToArray());
        }

        private static string ControlsText()
        {
            return string.Join("\n",
                "<b>FIREBALL</b>   snap your fingers (trigger), then throw overhand",
                "<b>SWORD</b>   make a fist (grip) at your opposite hip,",
                "draw up and across, then slash",
                "<b>SHIELD</b>   open palm forward (A); push it to parry a sword",
                "",
                "Dodge! Fireballs fly straight, so step out of the way.",
                "Band: B / Y to pair",
                "Room: after I'm ready, look at the QR marker in the middle of the room",
                "No marker: touch right controller tips in the middle, click left stick",
                "Menu button: end a match, or bring this panel back");
        }

        private void PickMode(string mode)
        {
            _pendingMode = mode;
            _view = View.Duration;
        }

        private void PickDuration(float seconds)
        {
            gameClient.Send(new MatchSetupMessage { Mode = _pendingMode, DurationS = seconds });
            _view = View.Ready;
        }

        private void ShowControls(View returnTo)
        {
            _controlsReturn = returnTo;
            _view = View.Controls;
        }

        private static string Minutes(float seconds) => $"{seconds / 60f:0.#} min";

        /// <summary>A big title card, a card for the body text, then a column of button cards; status text hangs below.</summary>
        private void Layout(Panel panel, string title, string body, params (string Label, Kind Kind, Action OnPress)[] buttons)
        {
            const float pad = 0.03f;
            const float gap = 0.022f;
            var root = panel.Root;
            var titleText = string.IsNullOrEmpty(title)
                ? null
                : UiStyle.CreateText("Title", root, title, Vector3.zero, 0.075f * textScale, UiStyle.Text, display: true,
                    look: UiStyle.Look.Title, spacing: 2f);
            var bodyText = string.IsNullOrEmpty(body)
                ? null
                : UiStyle.CreateText("Body", root, body, Vector3.zero, 0.024f * textScale, UiStyle.Text);
            var titleHeight = titleText != null ? UiStyle.Height(titleText) + pad : 0f;
            var bodyHeight = bodyText != null ? UiStyle.Height(bodyText) + 2f * pad : 0f;
            var buttonsHeight = buttons.Length * buttonHeight + Mathf.Max(0, buttons.Length - 1) * buttonGap;
            var parts = (titleText != null ? 1 : 0) + (bodyText != null ? 1 : 0) + (buttons.Length > 0 ? 1 : 0);
            var height = titleHeight + bodyHeight + buttonsHeight + Mathf.Max(0, parts - 1) * gap;

            panel.Footer = UiStyle.CreateText("Status", root, "", new Vector3(0f, -height * 0.5f - 0.03f, -0.003f), 0.017f * textScale,
                UiStyle.Text, alignment: TextAlignmentOptions.Top);
            panel.Footer.rectTransform.pivot = new Vector2(0.5f, 1f);

            var y = height * 0.5f;
            if (titleText != null)
            {
                var cy = y - titleHeight * 0.5f;
                var w = Mathf.Max(panelWidth * 0.8f, UiStyle.Width(titleText) + 0.1f);
                UiStyle.CreateCrystal("Title Card", root, new Vector2(w, titleHeight), UiStyle.Panel, new Vector3(0f, cy, 0f),
                    UiStyle.SortPanel, panel.Materials);
                titleText.transform.localPosition = new Vector3(0f, cy, -0.004f);
                y -= titleHeight + gap;
            }
            if (bodyText != null)
            {
                var cy = y - bodyHeight * 0.5f;
                var w = Mathf.Max(panelWidth, UiStyle.Width(bodyText) + 2f * pad + UiStyle.Shape.Skew * bodyHeight);
                UiStyle.CreateCrystal("Body Card", root, new Vector2(w, bodyHeight), UiStyle.Card, new Vector3(0f, cy, 0f),
                    UiStyle.SortPanel, panel.Materials);
                bodyText.transform.localPosition = new Vector3(0f, cy, -0.004f);
                y -= bodyHeight + gap;
            }

            var width = panelWidth * 0.85f;
            foreach (var (label, kind, onPress) in buttons)
            {
                var center = new Vector2(0f, y - buttonHeight * 0.5f);
                var size = new Vector2(width, buttonHeight);
                var style = kind == Kind.Primary ? UiStyle.Primary : UiStyle.Secondary;
                var back = UiStyle.CreateCrystal("Button", root, size, style, new Vector3(center.x, center.y, -0.002f), UiStyle.SortSurface, panel.Materials);
                var dwell = UiStyle.CreateCrystal("Dwell", root, new Vector2(0f, 0.005f), UiStyle.Bar,
                    new Vector3(center.x, center.y - buttonHeight * 0.32f, -0.004f), UiStyle.SortBar, panel.Materials);
                dwell.Transform.gameObject.SetActive(false);
                var text = UiStyle.CreateText("Label", root, label, new Vector3(center.x, center.y + buttonHeight * 0.04f, -0.005f),
                    0.032f * textScale, UiStyle.Text, display: true, spacing: 2f);
                text.fontStyle = FontStyles.UpperCase;
                panel.Buttons.Add(new Button
                {
                    Rect = new Rect(center - size * 0.5f, size),
                    Back = back,
                    Dwell = dwell,
                    Style = style,
                    OnPress = onPress,
                });
                y -= buttonHeight + buttonGap;
            }
        }

        // ---------------------------------------------------------------- placement

        private Vector3 FlatForward()
        {
            var forward = Eye.forward;
            forward.y = 0f;
            return forward.sqrMagnitude > 1e-4f ? forward.normalized : Vector3.forward;
        }

        private Vector3 InFront(float distance, float drop) => Eye.position + FlatForward() * distance + Vector3.down * drop;

        private Vector3 PanelSpot() => InFront(panelDistance, _view == View.Results ? resultsPanelDrop : panelDrop);

        private void FollowView(Panel panel)
        {
            var toPanel = panel.Target - Eye.position;
            toPanel.y = 0f;
            if (toPanel.sqrMagnitude < 1e-4f || Vector3.Angle(FlatForward(), toPanel) > refollowAngle ||
                toPanel.magnitude > panelDistance * 2f)
                panel.Target = PanelSpot();
            var t = 1f - Mathf.Exp(-followSpeed * Time.deltaTime);
            panel.Root.position = Vector3.Lerp(panel.Root.position, panel.Target, t);
            FaceViewer(panel.Root);
        }

        private void FaceViewer(Transform root)
        {
            var away = root.position - Eye.position;
            away.y *= 0.5f;
            if (away.sqrMagnitude > 1e-6f)
                root.rotation = Quaternion.LookRotation(away);
        }

        // ---------------------------------------------------------------- input

        private OVRInput.Controller PointerController()
        {
            var bandHand = _state?.Players.FirstOrDefault(p => p.PlayerId == Me)?.BandHand ?? HandSide.Right;
            return bandHand == HandSide.Left ? OVRInput.Controller.RTouch : OVRInput.Controller.LTouch;
        }

        private void UpdatePointer()
        {
            var controller = PointerController();
            var useController = OVRInput.IsControllerConnected(controller) && cameraRig != null;
            var anchor = controller == OVRInput.Controller.LTouch ? cameraRig?.leftControllerAnchor : cameraRig?.rightControllerAnchor;
            var origin = useController ? anchor : Eye;

            Button hit = null;
            var hitPoint = Vector3.zero;
            if (_panel != null && origin != null)
            {
                var plane = new Plane(-_panel.Root.forward, _panel.Root.position);
                var ray = new Ray(origin.position, origin.forward);
                if (plane.Raycast(ray, out var distance) && distance < pointerLength)
                {
                    hitPoint = ray.GetPoint(distance);
                    var local = _panel.Root.InverseTransformPoint(hitPoint);
                    hit = _panel.Buttons.FirstOrDefault(b => b.Rect.Contains(new Vector2(local.x, local.y)));
                }
            }

            var showRay = useController && _panel != null;
            _pointer.enabled = showRay;
            _pointerDot.gameObject.SetActive(showRay && hit != null);
            if (showRay)
            {
                var end = hit != null ? hitPoint : origin.position + origin.forward * 0.6f;
                _pointer.SetPosition(0, origin.position);
                _pointer.SetPosition(1, end);
                _pointerDot.position = end;
            }

            if (hit != _hovered)
            {
                if (_hovered != null)
                    SetHover(_hovered, false);
                _hovered = hit;
                _hoverStart = Time.time;
                _dwellFired = false;
                if (hit != null)
                {
                    SetHover(hit, true);
                    _audio.PlayOneShot(_tick, 0.5f);
                    Buzz(controller, 0.25f, 0.03f);
                }
            }
            if (hit == null)
                return;

            if (useController)
            {
                if (OVRInput.GetDown(OVRInput.Button.PrimaryIndexTrigger, controller))
                    Press(hit, controller);
                return;
            }

            var progress = Mathf.Clamp01((Time.time - _hoverStart) / dwellSeconds);
            var barWidth = hit.Rect.width - 2f * DwellBarInset;
            var bar = hit.Dwell;
            bar.Transform.gameObject.SetActive(progress > 0f);
            bar.Resize(new Vector2(barWidth * progress, bar.Size.y));
            var barPosition = bar.Transform.localPosition;
            bar.Transform.localPosition = new Vector3(hit.Rect.xMin + DwellBarInset + barWidth * progress * 0.5f, barPosition.y, barPosition.z);
            if (progress >= 1f && !_dwellFired)
            {
                _dwellFired = true;
                Press(hit, controller);
            }
        }

        private void Press(Button button, OVRInput.Controller controller)
        {
            _audio.PlayOneShot(_beep, 0.6f);
            Buzz(controller, 0.7f, 0.06f);
            button.OnPress();
        }

        private static void SetHover(Button button, bool hovered)
        {
            if (button.Back.Transform == null)
                return;
            button.Back.Apply(hovered ? UiStyle.Hovered(button.Style) : button.Style, button.Rect.size * (hovered ? 1.03f : 1f));
            if (!hovered && button.Dwell.Transform != null)
                button.Dwell.Transform.gameObject.SetActive(false);
        }

        private void Buzz(OVRInput.Controller controller, float amplitude, float seconds)
        {
            OVRInput.SetControllerVibration(1f, amplitude, controller);
            _hapticController = controller;
            _hapticStop = Time.time + seconds;
        }

        // ---------------------------------------------------------------- timer

        private void UpdateTimer()
        {
            var playing = _match.Phase == MatchPhase.Playing && Time.unscaledTime >= _timerAt;
            _timerBadge.gameObject.SetActive(playing);
            if (!playing)
                return;

            var target = Eye.position + FlatForward() * 1.4f + Vector3.up * 0.32f;
            var t = _timerPlaced ? 1f - Mathf.Exp(-2.5f * Time.deltaTime) : 1f;
            _timerPlaced = true;
            _timerBadge.position = Vector3.Lerp(_timerBadge.position, target, t);
            FaceViewer(_timerBadge);

            var left = Mathf.Max(0f, _match.TimeLeft);
            var urgent = _match.SuddenDeath || left <= 10f;
            var text = _match.SuddenDeath ? "SUDDEN DEATH" : $"{Mathf.FloorToInt(left / 60f)}:{Mathf.FloorToInt(left % 60f):00}";
            if (_timerText.text != text)
            {
                _timerText.text = text;
                _timerBack.Resize(new Vector2(Mathf.Max(0.2f, UiStyle.Width(_timerText) + 0.07f), _timerBack.Size.y));
            }
            var pulse = urgent ? 0.5f + 0.5f * Mathf.Sin(Time.time * 8f) : 0f;
            _timerBack.Apply(UiStyle.Pulsing(UiStyle.Hud, urgent ? 0.5f + 0.5f * pulse : 0f));
            _timerBadge.localScale = Vector3.one * (1f + 0.06f * pulse);
        }

        // ---------------------------------------------------------------- construction

        private void CreatePointer()
        {
            var ray = new GameObject("Menu Pointer");
            ray.transform.SetParent(transform, false);
            _pointer = ray.AddComponent<LineRenderer>();
            _pointer.sharedMaterial = Tinted(UiStyle.Pointer);
            _pointer.startWidth = 0.004f;
            _pointer.endWidth = 0.002f;
            _pointer.positionCount = 2;
            _pointer.useWorldSpace = true;
            _pointer.shadowCastingMode = ShadowCastingMode.Off;
            _pointer.enabled = false;
            _pointerDot = SpellVfx.CreateOrb("Pointer Dot", transform, _pointer.sharedMaterial, 0.015f);
            _pointerDot.gameObject.SetActive(false);
        }

        private void CreateTimerBadge()
        {
            _timerBadge = new GameObject("Match Timer").transform;
            _timerBadge.SetParent(transform, false);
            _timerBack = UiStyle.CreateCrystal("Back", _timerBadge, new Vector2(0.2f, 0.066f), UiStyle.Hud, Vector3.zero);
            _timerText = UiStyle.CreateText("Time", _timerBadge, "1:00", new Vector3(0f, 0.003f, -0.003f), 0.042f, UiStyle.Text,
                display: true, spacing: 2f);
            _timerBadge.gameObject.SetActive(false);
        }

        private Material Tinted(Color color)
        {
            var material = new Material(baseMaterial);
            material.SetColor("_BaseColor", color);
            return material;
        }

        private static AudioClip Tone(string name, float frequency, float seconds, float volume)
        {
            const int rate = 44100;
            var samples = Mathf.CeilToInt(rate * seconds);
            var data = new float[samples];
            for (var i = 0; i < samples; i++)
            {
                var envelope = Mathf.Min(1f, i / (rate * 0.005f)) * Mathf.Min(1f, (samples - i) / (rate * 0.04f));
                data[i] = Mathf.Sin(2f * Mathf.PI * frequency * i / rate) * volume * envelope;
            }
            var clip = AudioClip.Create(name, samples, 1, rate, false);
            clip.SetData(data, 0);
            return clip;
        }
    }
}
