using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Meta.XR.MRUtilityKit;
using SpellGame.Protocol;
using TMPro;
using UnityEngine;

namespace SpellGame.Game
{
    /// <summary>
    /// Moves this headset's tracking space into the shared room frame (architecture.md §5.1), so every pose it streams
    /// and every spell it draws uses the same origin as the other headset.
    /// <list type="bullet">
    /// <item>Default, floor marker: a printed QR code (<see cref="markerPayload"/>) lies flat in the middle of the room
    /// with its top pointing towards P2's side. Once this headset has tracked it for <see cref="markerLockSeconds"/>,
    /// its center becomes the origin and its top +z. Nothing to press.</item>
    /// <item>Fallback where QR tracking is unavailable, center calibration: both players meet in the middle facing each other, touch right controller
    /// tips together (each pointing at the other) and click the left thumbstick. The tip, on the floor, becomes the
    /// origin and the controller's pointing direction becomes this player's <c>spot_yaw</c>. No internet or measuring.</item>
    /// <item>With <see cref="useSharedAnchors"/>, host: creates an <see cref="OVRSpatialAnchor"/> at the frame's origin, saves it, shares it to the server's
    /// group UUID and sends <c>anchor_shared</c>.</item>
    /// <item>Everyone: loads that anchor, moves the camera rig so the anchor is the origin and sends <c>aligned</c>.</item>
    /// </list>
    /// Clicking the right thumbstick sends <c>space_reset</c>: the host places a fresh anchor and everyone re-aligns.
    /// </summary>
    public sealed class SharedSpaceAligner : MonoBehaviour
    {
        [SerializeField] private GameClient gameClient;
        [SerializeField] private OVRCameraRig cameraRig;

        [Tooltip("Also align through Meta Shared Spatial Anchors (needs internet). Center calibration always works.")]
        [SerializeField] private bool useSharedAnchors;

        [Tooltip("Text encoded in the floor marker's QR code (docs/center-marker.png); empty accepts any QR code.")]
        [SerializeField] private string markerPayload = "SPELLGAME-CENTER";

        [Tooltip("Seconds the marker must stay tracked; its pose is averaged over that time.")]
        [SerializeField] private float markerLockSeconds = 1.5f;

        [Tooltip("Seconds of calibrating without a marker lock before the screen switches to touching controller tips.")]
        [SerializeField] private float markerTimeoutSeconds = 12f;

        [Tooltip("Degrees added to the marker's direction, should its top not point the way the printed arrow does.")]
        [SerializeField] private float markerYawOffset;

        [Tooltip("A lock is rejected if any marker reading strays further than this from the average (metres).")]
        [SerializeField] private float maxMarkerSpread = 0.04f;

        [Tooltip("A lock is rejected if the marker's direction wobbles more than this (degrees).")]
        [SerializeField] private float maxMarkerWobbleDegrees = 6f;

        [Tooltip("Seconds the marker may drop out of view mid-reading without losing the progress so far.")]
        [SerializeField] private float markerGapSeconds = 1f;

        [Tooltip("Metres from the controller anchor forward to the tip that touches the other player's.")]
        [SerializeField] private float tipOffset = 0.06f;

        [Tooltip("Seconds the controller pose is averaged over after the click.")]
        [SerializeField] private float calibrationSeconds = 0.3f;

        [Tooltip("Time for the host to stand on their spot, facing the other player, before the anchor is placed.")]
        [SerializeField] private float placementDelaySeconds = 3f;

        [Tooltip("Unlit material for the ring and arrow drawn on the floor at the shared origin after calibrating.")]
        [SerializeField] private Material ringMaterial;
        [SerializeField] private float ringSeconds = 6f;
        [SerializeField] private float ringRadius = 0.25f;

        [SerializeField] private float localizeTimeoutSeconds = 10f;
        [SerializeField] private int loadAttempts = 5;

        private SpaceMessage _space;
        private OVRSpatialAnchor _anchor;
        private string _sharedInGroup;
        private string _alignedTo;
        private bool _busy;
        private bool _calibrating;
        private MRUKTrackable _marker;
        private float _markerSeenFor;
        private Vector3 _markerPositionSum;
        private Vector3 _markerForwardSum;
        private int _markerSamples;
        private readonly List<Vector3> _markerPositions = new();
        private readonly List<Vector3> _markerForwards = new();
        private float _markerLostAt = -1f;
        private bool? _markerWasAvailable;
        private string _status = "";
        private float _calibratedAt = float.NegativeInfinity;
        private TextMeshPro _hint;
        private string _phase = MatchPhase.Lobby;
        private string _mode;
        private float _trackerWaitSince = -1f;
        private bool _qrSeen;
        private float _lookingSince = -1f;
        private bool _readyToCalibrate;
        private bool _inSharedFrame;
        private bool _opponentTouched;
        private LineRenderer[] _ring;
        private int _ringShows;

        private const string TouchPrompt =
            "BOTH players: meet in the middle, touch RIGHT controller tips (each pointing at the other), then each click the LEFT stick";
        private const string MarkerPrompt = "Calibrate: stand next to the QR marker and look straight down at it";

        /// <summary>Whether this headset can calibrate on the floor marker (else players touch controller tips).</summary>
        public bool MarkerAvailable => MarkerProblem == null;

        /// <summary>Why the floor marker can't be used on this headset, or null if it can.</summary>
        public string MarkerProblem =>
            MRUK.Instance == null || !MRUK.Instance.QRCodeTrackingSupported ? "This headset can't track QR codes"
            : !HasScenePermission() ? "Spatial data permission is off (Settings > Apps > SpellGame > Permissions)"
            : _trackerWaitSince >= 0f && Time.time - _trackerWaitSince > 5f ? "The QR tracker didn't start: restart the app"
            : null;

        private string CalibratePrompt => UseTouch ? $"{TouchReason}\n{TouchPrompt}" : MarkerPrompt;

        /// <summary>
        /// Calibrate by touching controller tips instead of the marker: no QR tracking, no marker lock after
        /// <see cref="markerTimeoutSeconds"/> of trying, or the other player already calibrated that way (the two
        /// methods don't give exactly the same frame, so both must use the same one).
        /// </summary>
        public bool UseTouch =>
            !MarkerAvailable || _opponentTouched ||
            (_lookingSince >= 0f && Time.time - _lookingSince > markerTimeoutSeconds && _markerSamples == 0);

        /// <summary>Why <see cref="UseTouch"/>, for the prompts.</summary>
        public string TouchReason =>
            MarkerProblem != null ? $"{MarkerProblem}." :
            _opponentTouched ? "The other player calibrated with the controllers, so you do too." :
            "The QR code wasn't found: use the controllers instead.";

        /// <summary>Asks for the spatial data permission QR tracking needs, if it's missing (e.g. from I'm ready).</summary>
        public void RequestMarkerPermission()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            if (MRUK.Instance != null && MRUK.Instance.QRCodeTrackingSupported && !HasScenePermission())
                UnityEngine.Android.Permission.RequestUserPermission(OVRPermissionsRequester.ScenePermission);
#endif
        }

        private void OnEnable()
        {
            gameClient.SpaceReceived += OnSpace;
            gameClient.StateReceived += OnState;
        }

        private void OnDisable()
        {
            gameClient.SpaceReceived -= OnSpace;
            gameClient.StateReceived -= OnState;
        }

        private void OnState(StateMessage state)
        {
            _phase = state.Match?.Phase ?? MatchPhase.Lobby;
            _mode = state.Match?.Mode;
            var me = gameClient.PlayerId;
            _readyToCalibrate = _mode == MatchMode.Versus && _phase == MatchPhase.Ready &&
                                state.Match != null && state.Match.Ready.Contains(me);
            _inSharedFrame = false;
            _opponentTouched = false;
            foreach (var player in state.Players)
            {
                if (player.PlayerId == me)
                    _inSharedFrame = player.Aligned;
                else if (player.AlignMethod == AlignMethod.Center && state.Match != null && state.Match.Fighters.Contains(player.PlayerId))
                    _opponentTouched = true;
            }
        }

        // OVRManager.display is created in OVRManager.Awake, so subscribe once every Awake has run.
        private void Start()
        {
            OVRManager.display.RecenteredPose += OnRecentered;
            StartMarkerTracking();
        }

        private void OnDestroy()
        {
            OVRManager.display.RecenteredPose -= OnRecentered;
            if (MRUK.Instance != null)
            {
                MRUK.Instance.SceneSettings.TrackableAdded.RemoveListener(OnTrackableAdded);
                MRUK.Instance.SceneSettings.TrackableRemoved.RemoveListener(OnTrackableRemoved);
            }
        }

        /// <summary>QR codes are tracked through MRUK, which needs the spatial data (scene) permission.</summary>
        private void StartMarkerTracking()
        {
            var mruk = MRUK.Instance;
            if (mruk == null)
            {
                Debug.LogWarning("[SpellGame] No MRUK in the scene: floor marker calibration is off");
                return;
            }

            mruk.EnableWorldLock = false;
            var trackers = mruk.SceneSettings.TrackerConfiguration;
            trackers.QRCodeTrackingEnabled = true;
            mruk.SceneSettings.TrackerConfiguration = trackers;
            mruk.SceneSettings.TrackableAdded.AddListener(OnTrackableAdded);
            mruk.SceneSettings.TrackableRemoved.AddListener(OnTrackableRemoved);
#if UNITY_ANDROID && !UNITY_EDITOR
            if (!HasScenePermission())
                UnityEngine.Android.Permission.RequestUserPermission(OVRPermissionsRequester.ScenePermission);
#endif
        }

        private static bool HasScenePermission()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            return UnityEngine.Android.Permission.HasUserAuthorizedPermission(OVRPermissionsRequester.ScenePermission);
#else
            return true;
#endif
        }

        private void OnTrackableAdded(MRUKTrackable trackable)
        {
            if (trackable.TrackableType != OVRAnchor.TrackableType.QRCode)
                return;

            // Any QR code will do (the room shouldn't have others); the printed marker's text wins if several are seen.
            _qrSeen = true;
            var matches = string.IsNullOrEmpty(markerPayload) || trackable.MarkerPayloadString == markerPayload;
            Debug.Log($"[SpellGame] QR code seen: \"{trackable.MarkerPayloadString}\"{(matches ? "" : " (not the marker's text, used anyway)")}");
            if (matches || _marker == null)
                _marker = trackable;
        }

        private void OnTrackableRemoved(MRUKTrackable trackable)
        {
            if (trackable == _marker)
                _marker = null;
        }

        /// <summary>
        /// A recenter moves the headset's tracking origin, so the offset from the last alignment no longer lands on the
        /// shared frame: align again (to the anchor automatically; center calibration needs the tips touched again).
        /// </summary>
        private void OnRecentered()
        {
            if (_alignedTo == null)
                return;

            _alignedTo = null;
            Advance();
        }

        private void Update()
        {
            if (_space == null)
                return;

            if (OVRInput.GetDown(OVRInput.Button.PrimaryThumbstick, OVRInput.Controller.LTouch))
                CalibrateAtCenter();
            if (OVRInput.GetDown(OVRInput.Button.PrimaryThumbstick, OVRInput.Controller.RTouch))
                gameClient.Send(new SpaceResetMessage());

            var calibrating = _readyToCalibrate && !_inSharedFrame;
            if (!calibrating)
                _lookingSince = -1f;
            else if (_lookingSince < 0f)
                _lookingSince = Time.time;

            if (_markerWasAvailable != !UseTouch)
            {
                _markerWasAvailable = !UseTouch;
                if (!IsAligned(_space))
                    SetStatus(CalibratePrompt);
            }

            var mruk = MRUK.Instance;
            var trackerStarting = mruk != null && mruk.QRCodeTrackingSupported && HasScenePermission() &&
                                  !mruk.TrackerConfiguration.QRCodeTrackingEnabled;
            if (!trackerStarting)
                _trackerWaitSince = -1f;
            else if (_trackerWaitSince < 0f)
                _trackerWaitSince = Time.time;

            UpdateMarker();
            UpdateHint();
        }

        private void SetStatus(string text)
        {
            _status = text;
            gameClient.SetSpaceStatus(text);
        }

        /// <summary>
        /// The space status, also floating where the player looks while they look down (at the floor marker), since the
        /// menu panel is out of view then. Stays a few seconds after calibrating.
        /// </summary>
        private void UpdateHint()
        {
            var head = cameraRig.centerEyeAnchor;
            var calibrating = _readyToCalibrate && !_inSharedFrame;
            var text = _status;
            if (calibrating && UseTouch && !_calibrating)
                text = $"<b>CALIBRATE WITH THE CONTROLLERS</b>\n<size=70%>{TouchReason}\n" +
                       "Both players: meet in the middle, touch RIGHT controller tips,\neach pointing at the other, then each click the LEFT stick</size>";
            else if (calibrating && _markerSamples == 0 && (_marker == null || !_marker.IsTracked))
                text = _qrSeen
                    ? "QR code lost: keep it in view, about 1 m away"
                    : "Looking for the QR code…\n<size=70%>Stand next to it and look straight down; it needs good light</size>";
            var show = head.forward.y < -0.45f && !string.IsNullOrEmpty(text) &&
                       (calibrating || Time.time < _calibratedAt + 3f);
            if (_hint == null)
            {
                if (!show)
                    return;
                _hint = UiStyle.CreateText("Calibration Hint", null, "", Vector3.zero, 0.035f, UiStyle.Text,
                    display: true, look: UiStyle.Look.Title, width: 0.7f);
            }

            if (_hint.gameObject.activeSelf != show)
            {
                _hint.gameObject.SetActive(show);
                if (show)
                    _hint.transform.position = head.position + head.forward * 0.7f;
            }
            if (!show)
                return;

            if (_hint.text != text)
                _hint.text = text;
            var target = head.position + head.forward * 0.7f + Vector3.up * 0.12f;
            var hint = _hint.transform;
            hint.position = Vector3.Lerp(hint.position, target, 1f - Mathf.Exp(-6f * Time.deltaTime));
            hint.rotation = Quaternion.LookRotation(hint.position - head.position, Vector3.up);
        }

        /// <summary>
        /// While unaligned, averages the floor marker's pose over <see cref="markerLockSeconds"/> of tracking, then
        /// makes its center the origin (its height is the floor) and its top, flattened, the +z axis.
        /// </summary>
        private void UpdateMarker()
        {
            if (IsAligned(_space) || _calibrating || _opponentTouched)
            {
                if (_markerSamples > 0)
                    ResetMarkerSamples();
                return;
            }

            if (_marker == null || !_marker.IsTracked)
            {
                if (_markerSamples == 0)
                    return;
                if (_markerLostAt < 0f)
                    _markerLostAt = Time.time;
                if (Time.time - _markerLostAt <= markerGapSeconds)
                {
                    SetStatus($"Marker out of view: look back at it\n<size=70%>{Dots(MarkerProgress)}  progress kept</size>");
                    return;
                }
                SetStatus("Lost the marker: look straight down at it again");
                HideRing();
                ResetMarkerSamples();
                return;
            }
            _markerLostAt = -1f;

            // MRUK poses trackables in world space (it reads the tracking space's pose itself), alignment included.
            var rotation = _marker.transform.rotation;
            var normal = rotation * Vector3.forward;
            var top = rotation * Vector3.up;
            if (Mathf.Max(Mathf.Abs(normal.y), Mathf.Abs(top.y)) < 0.8f)
            {
                SetStatus("Lay the marker flat on the floor");
                HideRing();
                ResetMarkerSamples();
                return;
            }

            var along = Mathf.Abs(normal.y) > Mathf.Abs(top.y) ? top : normal;
            var position = _marker.transform.position;
            var forward = new Vector3(along.x, 0f, along.z).normalized;
            _markerPositions.Add(position);
            _markerForwards.Add(forward);
            _markerSamples++;
            _markerSeenFor += Time.deltaTime;
            var progress = MarkerProgress;
            var left = Mathf.Max(0f, markerLockSeconds - _markerSeenFor);
            SetStatus($"Marker found: hold still {left:0.0} s\n<size=70%>{Dots(progress)}</size>");
            PlaceRing(position, Mathf.Atan2(forward.x, forward.z) * Mathf.Rad2Deg + markerYawOffset, 0.006f + 0.01f * progress);
            if (_markerSeenFor < markerLockSeconds)
                return;

            if (!TryMarkerPose(out var center, out var yaw))
            {
                Debug.Log($"[SpellGame] Marker lock rejected: readings disagree ({_markerSamples} samples)");
                ResetMarkerSamples();
                HideRing();
                SetStatus("Shaky reading: hold still and keep looking at the marker");
                return;
            }

            AlignTo(new Pose(center, Quaternion.Euler(0f, yaw + markerYawOffset, 0f)));
            _alignedTo = MarkerKey(_space);
            gameClient.Send(new AlignedMessage { Method = AlignMethod.Marker });
            SetStatus("Room calibrated! The ring should sit on the marker.\n<size=70%>If it doesn't, click the right stick to redo it</size>");
            ShowOriginRing();
        }

        private float MarkerProgress => Mathf.Clamp01(_markerSeenFor / markerLockSeconds);

        /// <summary>
        /// Robust average of the marker readings: drops any further than <see cref="maxMarkerSpread"/> from the median
        /// position or more than <see cref="maxMarkerWobbleDegrees"/> off the mean direction; fails if under 60% remain.
        /// </summary>
        private bool TryMarkerPose(out Vector3 center, out float yaw)
        {
            center = Vector3.zero;
            yaw = 0f;
            if (_markerPositions.Count == 0)
                return false;
            var median = new Vector3(Median(_markerPositions.Select(p => p.x)), Median(_markerPositions.Select(p => p.y)),
                Median(_markerPositions.Select(p => p.z)));
            var direction = Vector3.zero;
            foreach (var forward in _markerForwards)
                direction += forward;
            direction.Normalize();
            var minDot = Mathf.Cos(maxMarkerWobbleDegrees * Mathf.Deg2Rad);
            var keptForward = Vector3.zero;
            var kept = 0;
            for (var i = 0; i < _markerPositions.Count; i++)
            {
                if (Vector3.Distance(_markerPositions[i], median) > maxMarkerSpread || Vector3.Dot(_markerForwards[i], direction) < minDot)
                    continue;
                center += _markerPositions[i];
                keptForward += _markerForwards[i];
                kept++;
            }
            if (kept == 0 || kept < 0.6f * _markerPositions.Count)
                return false;
            center /= kept;
            yaw = Mathf.Atan2(keptForward.x, keptForward.z) * Mathf.Rad2Deg;
            return true;
        }

        private static float Median(IEnumerable<float> values)
        {
            var sorted = values.OrderBy(v => v).ToList();
            return sorted[sorted.Count / 2];
        }

        private void ResetMarkerSamples()
        {
            _markerSeenFor = 0f;
            _markerSamples = 0;
            _markerPositions.Clear();
            _markerForwards.Clear();
            _markerLostAt = -1f;
            _markerPositionSum = _markerForwardSum = Vector3.zero;
        }

        private static string Dots(float progress)
        {
            const int count = 10;
            var filled = Mathf.Clamp(Mathf.RoundToInt(progress * count), 0, count);
            return new string('•', filled) + "<alpha=#40>" + new string('•', count - filled);
        }

        /// <summary>The ring, drawn on the marker while it's being read (its width grows with the progress).</summary>
        private void PlaceRing(Vector3 position, float yaw, float width)
        {
            if (ringMaterial == null)
                return;
            _ring ??= CreateOriginRing();
            _ringShows++;
            _ring[0].transform.parent.SetPositionAndRotation(position, Quaternion.Euler(0f, yaw, 0f));
            foreach (var line in _ring)
            {
                line.gameObject.SetActive(true);
                line.widthMultiplier = width;
            }
        }

        private void HideRing()
        {
            if (_ring == null)
                return;
            _ringShows++;
            foreach (var line in _ring)
                line.gameObject.SetActive(false);
        }

        private void OnSpace(SpaceMessage space)
        {
            if (_space != null && _space.GroupUuid != space.GroupUuid)
            {
                DestroyAnchor();
                _sharedInGroup = null;
                _alignedTo = null;
            }

            _space = space;
            Advance();
        }

        private async void Advance()
        {
            if (_busy || _space == null)
                return;

            var space = _space;
            if (!useSharedAnchors)
            {
                if (!IsAligned(space))
                    SetStatus(CalibratePrompt);
                return;
            }

            if (space.AnchorUuid == null)
            {
                if (space.HostId == gameClient.PlayerId && _sharedInGroup != space.GroupUuid)
                    await Run(() => ShareAnchorAsync(space), "Sharing the room anchor failed");
                else if (!IsAligned(space))
                    SetStatus($"Waiting for {space.HostId ?? "a host"} to share the room anchor…");
                return;
            }

            if (_alignedTo != space.AnchorUuid)
                await Run(() => AlignToAnchorAsync(space), "Loading the room anchor failed");
        }

        /// <summary>One anchor step at a time; afterwards, catch up with any <c>space</c> that arrived meanwhile.</summary>
        private async Task Run(Func<Task> step, string failure)
        {
            _busy = true;
            try
            {
                await step();
            }
            catch (Exception exception)
            {
                Debug.LogError($"[SpellGame] {failure}: {exception}");
                SetStatus($"{failure}. {CalibratePrompt}");
                return;
            }
            finally
            {
                _busy = false;
            }

            Advance();
        }

        private async Task ShareAnchorAsync(SpaceMessage space)
        {
            SetStatus("Placing the room anchor: stand on your spot, facing the other player");
            await Awaitable.WaitForSecondsAsync(placementDelaySeconds, destroyCancellationToken);

            var origin = OriginFromFloorSpot(space);
            var anchor = new GameObject("Shared Space Anchor").AddComponent<OVRSpatialAnchor>();
            anchor.transform.SetPositionAndRotation(origin.position, origin.rotation);
            try
            {
                if (!await anchor.WhenCreatedAsync())
                    throw new InvalidOperationException("the anchor could not be created");

                var saved = await anchor.SaveAnchorAsync();
                if (!saved.Success)
                    throw new InvalidOperationException($"save failed: {saved.Status}");

                var shared = await anchor.ShareAsync(Guid.Parse(space.GroupUuid));
                if (!shared.Success)
                    throw new InvalidOperationException($"share failed: {shared.Status}");
            }
            catch
            {
                Destroy(anchor.gameObject);
                throw;
            }

            if (_space.GroupUuid != space.GroupUuid)
            {
                Destroy(anchor.gameObject);
                return;
            }

            DestroyAnchor();
            _anchor = anchor;
            _sharedInGroup = space.GroupUuid;
            gameClient.Send(new AnchorSharedMessage { AnchorUuid = anchor.Uuid.ToString() });
            SetStatus("Room anchor shared, aligning…");
        }

        private async Task AlignToAnchorAsync(SpaceMessage space)
        {
            SetStatus("Aligning to the room anchor…");
            var uuid = Guid.Parse(space.AnchorUuid);
            if (_anchor == null || _anchor.Uuid != uuid)
            {
                DestroyAnchor();
                _anchor = await LoadSharedAnchorAsync(Guid.Parse(space.GroupUuid), uuid);
            }

            if (!await _anchor.WhenLocalizedAsync())
                throw new InvalidOperationException($"anchor {uuid} did not localize");

            // OVRSpatialAnchor updates its transform in Update; wait for a fresh pose after binding.
            await Awaitable.NextFrameAsync(destroyCancellationToken);
            if (_space.AnchorUuid != space.AnchorUuid)
                return;

            AlignTo(new Pose(_anchor.transform.position, _anchor.transform.rotation));
            _alignedTo = space.AnchorUuid;
            gameClient.Send(new AlignedMessage { Method = AlignMethod.Anchor, AnchorUuid = space.AnchorUuid });
            SetStatus("Aligned to the room anchor");
            ShowOriginRing();
        }

        private async Task<OVRSpatialAnchor> LoadSharedAnchorAsync(Guid groupUuid, Guid anchorUuid)
        {
            var unbound = new List<OVRSpatialAnchor.UnboundAnchor>();
            for (var attempt = 1; attempt <= loadAttempts; attempt++)
            {
                var loaded = await OVRSpatialAnchor.LoadUnboundSharedAnchorsAsync(groupUuid, unbound);
                if (loaded.Success)
                {
                    foreach (var candidate in unbound)
                    {
                        if (candidate.Uuid != anchorUuid)
                            continue;

                        if (!await candidate.LocalizeAsync(localizeTimeoutSeconds))
                            throw new InvalidOperationException($"anchor {anchorUuid} did not localize");

                        var anchor = new GameObject("Shared Space Anchor").AddComponent<OVRSpatialAnchor>();
                        candidate.BindTo(anchor);
                        return anchor;
                    }
                }
                else
                {
                    Debug.LogWarning($"[SpellGame] Loading shared anchors (attempt {attempt}) failed: {loaded.Status}");
                }

                await Awaitable.WaitForSecondsAsync(1f, destroyCancellationToken);
            }

            throw new InvalidOperationException($"anchor {anchorUuid} was not found in group {groupUuid}");
        }

        /// <summary>
        /// Center calibration: the right controller's tip touches the other player's at the room's center, pointing at
        /// them. Averages the tip and its horizontal pointing direction for <see cref="calibrationSeconds"/>, then makes
        /// the tip (on the floor) the origin and the pointing direction this player's <c>spot_yaw</c>.
        /// </summary>
        private async void CalibrateAtCenter()
        {
            if (_calibrating || _space == null)
                return;

            _calibrating = true;
            try
            {
                SetStatus("Hold still: calibrating…");
                var controller = cameraRig.rightControllerAnchor;
                var tip = Vector3.zero;
                var pointing = Vector3.zero;
                var samples = 0;
                var until = Time.time + calibrationSeconds;
                do
                {
                    var forward = controller.forward;
                    tip += controller.position + forward * tipOffset;
                    pointing += new Vector3(forward.x, 0f, forward.z).normalized;
                    samples++;
                    await Awaitable.NextFrameAsync(destroyCancellationToken);
                } while (Time.time < until);

                if (pointing.sqrMagnitude < 0.01f * samples * samples)
                {
                    SetStatus("Point the right controller at the other player, then click the left stick again");
                    return;
                }

                var space = _space;
                tip /= samples;
                var yaw = Mathf.Atan2(pointing.x, pointing.z) * Mathf.Rad2Deg;
                var floorY = cameraRig.trackingSpace.position.y;
                AlignTo(new Pose(new Vector3(tip.x, floorY, tip.z), Quaternion.Euler(0f, yaw - space.SpotYaw, 0f)));
                _alignedTo = CenterKey(space);
                gameClient.Send(new AlignedMessage { Method = AlignMethod.Center });
                SetStatus("Room calibrated: walk back to your side");
                ShowOriginRing();
                OVRInput.SetControllerVibration(1f, 0.6f, OVRInput.Controller.RTouch);
                await Awaitable.WaitForSecondsAsync(0.15f, destroyCancellationToken);
                OVRInput.SetControllerVibration(0f, 0f, OVRInput.Controller.RTouch);
            }
            finally
            {
                _calibrating = false;
            }
        }

        /// <summary>
        /// Where the shared frame's origin is in the world, given that the player stands on <c>spot_pos</c> facing
        /// <c>spot_yaw</c>: the head's floor point and heading, minus the spot's offset and yaw.
        /// </summary>
        private Pose OriginFromFloorSpot(SpaceMessage space)
        {
            var head = cameraRig.centerEyeAnchor;
            var floorY = cameraRig.trackingSpace.position.y;
            var headYaw = Mathf.Atan2(head.forward.x, head.forward.z) * Mathf.Rad2Deg;
            var rotation = Quaternion.Euler(0f, headYaw - space.SpotYaw, 0f);
            var spot = new Vector3(space.SpotPos[0], 0f, space.SpotPos[2]);
            var position = new Vector3(head.position.x, floorY, head.position.z) - rotation * spot;
            return new Pose(position, rotation);
        }

        /// <summary>
        /// Moves the camera rig so <paramref name="originInWorld"/> becomes the world origin, height included: the
        /// anchor on the host's floor becomes everyone's floor, whatever floor height each headset estimated. Only yaw
        /// is taken from the origin's rotation, so gravity stays straight down.
        /// </summary>
        private void AlignTo(Pose originInWorld)
        {
            var trackingSpace = cameraRig.trackingSpace;
            var position = trackingSpace.InverseTransformPoint(originInWorld.position);
            var yaw = (Quaternion.Inverse(trackingSpace.rotation) * originInWorld.rotation).eulerAngles.y;
            var rotation = Quaternion.Euler(0f, -yaw, 0f);
            cameraRig.transform.SetPositionAndRotation(rotation * -position, rotation);
        }

        /// <summary>
        /// A glowing ring with an arrow towards P2's side, on the floor at the shared origin (the world origin after
        /// <see cref="AlignTo"/>). It should sit on the printed marker, or where the tips touched, in both headsets.
        /// </summary>
        private async void ShowOriginRing()
        {
            if (ringMaterial == null)
                return;

            _ring ??= CreateOriginRing();
            _ring[0].transform.parent.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
            _calibratedAt = Time.time;
            var show = ++_ringShows;
            foreach (var line in _ring)
                line.gameObject.SetActive(true);
            try
            {
                for (var t = 0f; t < ringSeconds && show == _ringShows; t += Time.deltaTime)
                {
                    var fade = Mathf.Clamp01((ringSeconds - t) / 1f);
                    var width = (0.012f + 0.006f * Mathf.Sin(t * 6f)) * fade;
                    foreach (var line in _ring)
                        line.widthMultiplier = width;
                    await Awaitable.NextFrameAsync(destroyCancellationToken);
                }
            }
            catch (OperationCanceledException)
            {
                return;
            }

            if (show != _ringShows)
                return;
            foreach (var line in _ring)
                line.gameObject.SetActive(false);
        }

        private LineRenderer[] CreateOriginRing()
        {
            var root = new GameObject("Shared Origin Ring").transform;
            const int segments = 48;
            var circle = new Vector3[segments];
            for (var i = 0; i < segments; i++)
            {
                var angle = i * Mathf.PI * 2f / segments;
                circle[i] = new Vector3(Mathf.Sin(angle) * ringRadius, 0.01f, Mathf.Cos(angle) * ringRadius);
            }

            var tip = ringRadius * 1.8f;
            var arrow = new[]
            {
                new Vector3(0f, 0.01f, 0f), new Vector3(0f, 0.01f, tip),
                new Vector3(-0.08f, 0.01f, tip - 0.08f), new Vector3(0f, 0.01f, tip), new Vector3(0.08f, 0.01f, tip - 0.08f),
            };
            return new[] { CreateLine("Ring", root, circle, loop: true), CreateLine("Arrow", root, arrow, loop: false) };
        }

        private LineRenderer CreateLine(string name, Transform parent, Vector3[] points, bool loop)
        {
            var line = new GameObject(name).AddComponent<LineRenderer>();
            line.transform.SetParent(parent, false);
            line.useWorldSpace = false;
            line.loop = loop;
            line.positionCount = points.Length;
            line.SetPositions(points);
            line.sharedMaterial = ringMaterial;
            line.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            line.receiveShadows = false;
            line.gameObject.SetActive(false);
            return line;
        }

        private static string CenterKey(SpaceMessage space) => $"{AlignMethod.Center}:{space.GroupUuid}";

        private static string MarkerKey(SpaceMessage space) => $"{AlignMethod.Marker}:{space.GroupUuid}";

        private bool IsAligned(SpaceMessage space) =>
            space != null && (_alignedTo == CenterKey(space) || _alignedTo == MarkerKey(space));

        private void DestroyAnchor()
        {
            if (_anchor != null)
                Destroy(_anchor.gameObject);
            _anchor = null;
        }
    }
}
