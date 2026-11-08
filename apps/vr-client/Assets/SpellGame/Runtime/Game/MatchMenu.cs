using System;
using System.Collections.Generic;
using System.Linq;
using SpellGame.Protocol;
using UnityEngine;
using UnityEngine.Rendering;

namespace SpellGame.Game
{
    /// <summary>
    /// The match menus (architecture.md §5.2), all in passthrough: small panels placed in the room about a metre in
    /// front, a little below eye level, never a full-view or opaque screen. A panel stays put while you look around and
    /// glides back in front of you when it leaves your view (lazy follow), so nothing is glued to your head.
    /// <list type="bullet">
    /// <item>Point with the controller in the hand without the band and pull its trigger (the band hand's trigger is the
    /// snap stand-in); without controllers, look at a button for a moment to press it.</item>
    /// <item>Menu button (left controller): during a match, end it; otherwise bring the panel back in front of you.</item>
    /// </list>
    /// Screens: mode → length → how to cast (first time) → ready → 3-2-1-FIGHT → timer badge → results.
    /// The server owns the flow; this only sends intents and renders <see cref="MatchSnapshot"/>.
    /// </summary>
    public sealed class MatchMenu : MonoBehaviour
    {
        [SerializeField] private GameClient gameClient;
        [SerializeField] private OVRCameraRig cameraRig;
        [Tooltip("Unlit material the panel materials are copied from (only its colour is changed).")]
        [SerializeField] private Material baseMaterial;

        [Header("Placement")]
        [SerializeField] private float panelDistance = 1.1f;
        [SerializeField] private float panelDrop = 0.05f;
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

        private static readonly Color PanelColor = new(0.05f, 0.06f, 0.11f);
        private static readonly Color ButtonColor = new(0.15f, 0.19f, 0.32f);
        private static readonly Color PrimaryColor = new(0.12f, 0.45f, 0.3f);
        private static readonly Color DangerColor = new(0.55f, 0.14f, 0.14f);
        private static readonly Color HoverColor = new(0.3f, 0.5f, 0.95f);
        private static readonly Color AccentText = new(1f, 0.8f, 0.35f);

        private enum View { None, Connection, Mode, Duration, Controls, Ready, Pause, Results }

        private sealed class Button
        {
            public Rect Rect;
            public Transform Back;
            public Transform DwellFill;
            public Material Material;
            public Color Color;
            public Action OnPress;
        }

        private sealed class Panel
        {
            public Transform Root;
            public string Key;
            public readonly List<Button> Buttons = new();
            public Vector3 Target;
            public bool Placed;
        }

        private Panel _panel;
        private View _view = View.Mode;
        private View _controlsReturn = View.Mode;
        private bool _seenControls;
        private string _pendingMode = MatchMode.Solo;
        private MatchSnapshot _match = new();
        private StateMessage _state;
        private string _lastPhase;

        private Button _hovered;
        private float _hoverStart;
        private bool _dwellFired;
        private LineRenderer _pointer;
        private Transform _pointerDot;
        private float _hapticStop;
        private OVRInput.Controller _hapticController;

        private TextMesh _countdownText;
        private Vector3 _countdownTarget;
        private int _lastCount = -1;
        private float _fightShownAt = float.NegativeInfinity;
        private Transform _timerBadge;
        private TextMesh _timerText;
        private Material _timerMaterial;
        private bool _timerPlaced;

        private AudioSource _audio;
        private AudioClip _tick, _beep, _go, _end;
        private Material _panelMaterial;

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
        private bool IsFighter => Me != null && _match.Fighters.Contains(Me);

        /// <summary>The connection screen covers every other screen until the server has welcomed this headset.</summary>
        private View ShownView => gameClient.Connection == ConnectionState.Connected ? _view : View.Connection;

        private void Awake()
        {
            _panelMaterial = Tinted(PanelColor);
            _audio = gameObject.AddComponent<AudioSource>();
            _audio.playOnAwake = false;
            _audio.spatialBlend = 0f;
            _tick = Tone("Tick", 1400f, 0.03f, 0.15f);
            _beep = Tone("Beep", 660f, 0.18f, 0.35f);
            _go = Tone("Go", 990f, 0.45f, 0.4f);
            _end = Tone("End", 440f, 0.6f, 0.35f);
            CreatePointer();
            CreateCountdown();
            CreateTimerBadge();
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
                    if (_view is not (View.Duration or View.Controls))
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
                    _lastCount = -1;
                    _countdownTarget = InFront(2f, 0.05f);
                    _countdownText.transform.position = _countdownTarget;
                    break;
                case MatchPhase.Playing:
                    _view = View.None;
                    _fightShownAt = Time.time;
                    _timerPlaced = false;
                    _audio.PlayOneShot(_go);
                    break;
                case MatchPhase.Ended:
                    _view = View.Results;
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
            UpdateCountdown();
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
            var key = PanelKey(view);
            if (_panel != null && _panel.Key == key)
            {
                FollowView(_panel);
                return;
            }

            var keep = _panel is { Placed: true } ? _panel.Root.position : (Vector3?)null;
            if (_panel != null)
                Destroy(_panel.Root.gameObject);
            _panel = null;
            _hovered = null;
            if (view == View.None)
                return;

            _panel = BuildPanel(view, key);
            _panel.Target = keep ?? PanelSpot();
            _panel.Root.position = _panel.Target;
            _panel.Placed = true;
            FaceViewer(_panel.Root);
        }

        /// <summary>Changes whenever what the current screen shows changes, so the panel is rebuilt only then.</summary>
        private string PanelKey(View view)
        {
            var players = _state?.Players.Select(p => $"{p.PlayerId}:{p.Hp:0}") ?? Enumerable.Empty<string>();
            return view switch
            {
                View.Connection => $"connection|{gameClient.Connection}|{gameClient.ServerEndpoint}",
                View.Ready => $"ready|{Me}|{_match.Mode}|{_match.DurationS}|{string.Join(",", _match.Fighters)}|{string.Join(",", _match.Ready)}",
                View.Results => $"results|{Me}|{_match.Winner}|{_match.Reason}|{_match.EndedBy}|{string.Join(",", players)}",
                _ => view.ToString(),
            };
        }

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
                        ("1 Player  ·  vs AI", PrimaryColor, () => PickMode(MatchMode.Solo)),
                        ("2 Players", PrimaryColor, () => PickMode(MatchMode.Versus)),
                        ("How to cast", ButtonColor, () => ShowControls(View.Mode)));
                    break;
                case View.Duration:
                    Layout(panel, _pendingMode == MatchMode.Solo ? "1 PLAYER  ·  vs AI" : "2 PLAYERS", "How long?",
                        ("1 minute", PrimaryColor, () => PickDuration(Durations[0])),
                        ("2 minutes", PrimaryColor, () => PickDuration(Durations[1])),
                        ("5 minutes", PrimaryColor, () => PickDuration(Durations[2])),
                        ("Back", ButtonColor, () => _view = View.Mode));
                    break;
                case View.Controls:
                    Layout(panel, "HOW TO CAST", ControlsText(),
                        ("Got it", PrimaryColor, () => { _seenControls = true; _view = _controlsReturn; }));
                    break;
                case View.Ready:
                    BuildReady(panel);
                    break;
                case View.Pause:
                    Layout(panel, "END MATCH?", "Ends it for everyone, with no winner.",
                        ("End match", DangerColor, () => { gameClient.Send(new MatchQuitMessage()); _view = View.None; }),
                        ("Keep fighting", PrimaryColor, () => _view = View.None));
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
            (string Label, Color Color, Action OnPress) cancel = ("Cancel", ButtonColor, gameClient.CancelConnecting);
            (string Label, Color Color, Action OnPress) rescan = ("Rescan for servers", PrimaryColor, gameClient.Rescan);
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
                lines.Add($"{name}:  {(_match.Ready.Contains(fighter) ? "READY" : "not ready")}");
            }
            if (_match.Mode == MatchMode.Versus && _match.Fighters.Count < 2)
                lines.Add("Waiting for a second headset to join…");
            if (!IsFighter && _match.Fighters.Count > 0)
                lines.Insert(0, $"Watching {string.Join(" vs ", _match.Fighters)}");

            var buttons = new List<(string, Color, Action)>();
            if (IsFighter)
            {
                var ready = _match.Ready.Contains(Me);
                buttons.Add(ready
                    ? ("Not ready", ButtonColor, () => gameClient.Send(new ReadyMessage { Ready = false }))
                    : ("I'm ready!", PrimaryColor, () => gameClient.Send(new ReadyMessage { Ready = true })));
            }
            buttons.Add(("How to cast", ButtonColor, () => ShowControls(View.Ready)));
            buttons.Add(("Back to menu", ButtonColor, () => gameClient.Send(new MatchQuitMessage())));
            Layout(panel, title, string.Join("\n", lines), buttons.ToArray());
        }

        private void BuildResults(Panel panel)
        {
            string title;
            if (_match.Reason == MatchEndReason.Quit)
                title = "MATCH ENDED";
            else if (_match.Winner == null)
                title = "DRAW";
            else if (_match.Winner == Me)
                title = "VICTORY!";
            else if (IsFighter)
                title = "DEFEAT";
            else
                title = $"{_match.Winner} WINS";

            var reason = _match.Reason switch
            {
                MatchEndReason.Ko => "Knockout",
                MatchEndReason.Time => "Time's up: most HP wins",
                MatchEndReason.Quit => $"Ended by {(_match.EndedBy == Me ? "you" : _match.EndedBy)}",
                MatchEndReason.Disconnect => "Opponent disconnected",
                _ => "",
            };
            var lines = new List<string> { reason };
            foreach (var fighter in _match.Fighters)
            {
                var hp = _state?.Players.FirstOrDefault(p => p.PlayerId == fighter)?.Hp ?? 0f;
                var name = fighter == Me ? "You" : fighter == _match.AiId ? "AI mage" : fighter;
                lines.Add($"{name}:  {Mathf.Max(0f, hp):0} HP");
            }

            var buttons = new List<(string, Color, Action)>();
            if (IsFighter)
                buttons.Add(("Rematch", PrimaryColor, () => gameClient.Send(new RematchMessage())));
            buttons.Add(("Main menu", ButtonColor, () => gameClient.Send(new MatchQuitMessage())));
            Layout(panel, title, string.Join("\n", lines), buttons.ToArray());
        }

        private static string ControlsText() => string.Join("\n",
            "FIREBALL   snap your fingers (trigger), then throw overhand",
            "SWORD   make a fist (grip) at your opposite hip,",
            "              draw up and across, then slash",
            "SHIELD   open palm forward (A); push it to parry a sword",
            "",
            "Dodge! Fireballs fly straight, so step out of the way.",
            "Band: B / Y to pair   ·   Room: click left stick to align",
            "Menu button: end a match, or bring this panel back");

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

        /// <summary>Title, body text, then a column of buttons; the background is sized to fit.</summary>
        private void Layout(Panel panel, string title, string body, params (string Label, Color Color, Action OnPress)[] buttons)
        {
            const float pad = 0.035f;
            const float titleHeight = 0.07f;
            var bodyLines = string.IsNullOrEmpty(body) ? 0 : body.Split('\n').Length;
            var lineHeight = 0.034f * textScale;
            var bodyHeight = bodyLines * lineHeight;
            var buttonsHeight = buttons.Length * buttonHeight + Mathf.Max(0, buttons.Length - 1) * buttonGap;
            var height = pad + titleHeight + (bodyLines > 0 ? bodyHeight + pad * 0.6f : 0f) + buttonsHeight + pad;

            var back = CreateQuad("Panel", panel.Root, _panelMaterial);
            back.localScale = new Vector3(panelWidth, height, 1f);

            var y = height * 0.5f - pad;
            CreateText("Title", panel.Root, title, new Vector3(0f, y - titleHeight * 0.45f, -0.003f), 0.011f, AccentText, FontStyle.Bold);
            y -= titleHeight;
            if (bodyLines > 0)
            {
                CreateText("Body", panel.Root, body, new Vector3(0f, y - bodyHeight * 0.5f, -0.003f), 0.0068f, Color.white, FontStyle.Normal);
                y -= bodyHeight + pad * 0.6f;
            }

            var width = panelWidth - 2f * pad;
            foreach (var (label, color, onPress) in buttons)
            {
                var center = new Vector2(0f, y - buttonHeight * 0.5f);
                var material = Tinted(color);
                var quad = CreateQuad("Button", panel.Root, material);
                quad.localPosition = new Vector3(center.x, center.y, -0.002f);
                quad.localScale = new Vector3(width, buttonHeight, 1f);
                var fill = CreateQuad("Dwell", panel.Root, Tinted(HoverColor * 1.3f));
                fill.localPosition = new Vector3(-width * 0.5f, center.y - buttonHeight * 0.42f, -0.004f);
                fill.localScale = new Vector3(0f, buttonHeight * 0.12f, 1f);
                CreateText("Label", panel.Root, label, new Vector3(center.x, center.y, -0.005f), 0.0085f, Color.white, FontStyle.Bold);
                panel.Buttons.Add(new Button
                {
                    Rect = new Rect(center - new Vector2(width, buttonHeight) * 0.5f, new Vector2(width, buttonHeight)),
                    Back = quad,
                    DwellFill = fill,
                    Material = material,
                    Color = color,
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

        private Vector3 PanelSpot() => InFront(panelDistance, panelDrop);

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
            var width = hit.Rect.width;
            hit.DwellFill.localScale = new Vector3(width * progress, hit.DwellFill.localScale.y, 1f);
            hit.DwellFill.localPosition = new Vector3(hit.Rect.xMin + width * progress * 0.5f, hit.DwellFill.localPosition.y, hit.DwellFill.localPosition.z);
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
            if (button.Back == null)
                return;
            button.Material.SetColor("_BaseColor", hovered ? Color.Lerp(button.Color, HoverColor, 0.6f) : button.Color);
            button.Back.localScale = new Vector3(button.Rect.width * (hovered ? 1.03f : 1f), button.Rect.height * (hovered ? 1.08f : 1f), 1f);
        }

        private void Buzz(OVRInput.Controller controller, float amplitude, float seconds)
        {
            OVRInput.SetControllerVibration(1f, amplitude, controller);
            _hapticController = controller;
            _hapticStop = Time.time + seconds;
        }

        // ---------------------------------------------------------------- countdown and timer

        private void UpdateCountdown()
        {
            var counting = _match.Phase == MatchPhase.Countdown;
            var fight = _match.Phase == MatchPhase.Playing && Time.time - _fightShownAt < 1f;
            _countdownText.gameObject.SetActive(counting || fight);
            if (!counting && !fight)
                return;

            var t = 1f - Mathf.Exp(-2f * Time.deltaTime);
            var text = _countdownText.transform;
            text.position = Vector3.Lerp(text.position, _countdownTarget, t);
            FaceViewer(text);
            if (counting)
            {
                var count = Mathf.Max(1, Mathf.CeilToInt(_match.Countdown));
                if (count != _lastCount)
                {
                    _lastCount = count;
                    _audio.PlayOneShot(_beep);
                }
                var pop = 1f + 0.4f * Mathf.Clamp01(1f - (count - _match.Countdown) * 3f);
                _countdownText.text = count.ToString();
                _countdownText.color = Color.white;
                text.localScale = Vector3.one * pop;
            }
            else
            {
                _countdownText.text = "FIGHT!";
                _countdownText.color = AccentText;
                text.localScale = Vector3.one * (1f + 0.3f * (Time.time - _fightShownAt));
            }
        }

        private void UpdateTimer()
        {
            var playing = _match.Phase == MatchPhase.Playing;
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
            _timerText.text = _match.SuddenDeath ? "SUDDEN DEATH" : $"{Mathf.FloorToInt(left / 60f)}:{Mathf.FloorToInt(left % 60f):00}";
            var pulse = urgent ? 0.5f + 0.5f * Mathf.Sin(Time.time * 8f) : 0f;
            _timerMaterial.SetColor("_BaseColor", Color.Lerp(PanelColor, DangerColor, urgent ? 0.5f + 0.5f * pulse : 0f));
            _timerBadge.localScale = Vector3.one * (1f + 0.06f * pulse);
        }

        // ---------------------------------------------------------------- construction

        private void CreatePointer()
        {
            var ray = new GameObject("Menu Pointer");
            ray.transform.SetParent(transform, false);
            _pointer = ray.AddComponent<LineRenderer>();
            _pointer.sharedMaterial = Tinted(new Color(0.6f, 0.8f, 1f));
            _pointer.startWidth = 0.004f;
            _pointer.endWidth = 0.002f;
            _pointer.positionCount = 2;
            _pointer.useWorldSpace = true;
            _pointer.shadowCastingMode = ShadowCastingMode.Off;
            _pointer.enabled = false;
            _pointerDot = SpellVfx.CreateOrb("Pointer Dot", transform, _pointer.sharedMaterial, 0.015f);
            _pointerDot.gameObject.SetActive(false);
        }

        private void CreateCountdown()
        {
            _countdownText = CreateText("Countdown", transform, "3", Vector3.zero, 0.05f, Color.white, FontStyle.Bold);
            _countdownText.gameObject.SetActive(false);
        }

        private void CreateTimerBadge()
        {
            _timerBadge = new GameObject("Match Timer").transform;
            _timerBadge.SetParent(transform, false);
            _timerMaterial = Tinted(PanelColor);
            var back = CreateQuad("Back", _timerBadge, _timerMaterial);
            back.localScale = new Vector3(0.24f, 0.07f, 1f);
            _timerText = CreateText("Time", _timerBadge, "1:00", new Vector3(0f, 0f, -0.003f), 0.011f, Color.white, FontStyle.Bold);
            _timerBadge.gameObject.SetActive(false);
        }

        private TextMesh CreateText(string name, Transform parent, string text, Vector3 localPosition, float size, Color color, FontStyle style)
        {
            var label = new GameObject(name).AddComponent<TextMesh>();
            label.transform.SetParent(parent, false);
            label.transform.localPosition = localPosition;
            label.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            label.GetComponent<MeshRenderer>().sharedMaterial = label.font.material;
            label.anchor = TextAnchor.MiddleCenter;
            label.alignment = TextAlignment.Center;
            label.characterSize = size * textScale;
            label.fontSize = 64;
            label.fontStyle = style;
            label.color = color;
            label.text = text;
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
