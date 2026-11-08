using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using Meta.XR.MRUtilityKit;
using SpellGame.Protocol;
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

        [Tooltip("Degrees added to the marker's direction, should its top not point the way the printed arrow does.")]
        [SerializeField] private float markerYawOffset;

        [Tooltip("Metres from the controller anchor forward to the tip that touches the other player's.")]
        [SerializeField] private float tipOffset = 0.06f;

        [Tooltip("Seconds the controller pose is averaged over after the click.")]
        [SerializeField] private float calibrationSeconds = 0.3f;

        [Tooltip("Time for the host to stand on their spot, facing the other player, before the anchor is placed.")]
        [SerializeField] private float placementDelaySeconds = 3f;

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

        private const string TouchPrompt =
            "Calibrate: meet in the middle, touch right controller tips, click the left stick";
        private const string MarkerPrompt = "Calibrate: look down at the marker in the middle of the room";

        /// <summary>Whether this headset can calibrate on the floor marker (else players touch controller tips).</summary>
        public bool MarkerAvailable =>
            MRUK.Instance != null && MRUK.Instance.QRCodeTrackingSupported && HasScenePermission();

        private string CalibratePrompt => MarkerAvailable ? MarkerPrompt : TouchPrompt;

        private void OnEnable() => gameClient.SpaceReceived += OnSpace;

        private void OnDisable() => gameClient.SpaceReceived -= OnSpace;

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
                MRUK.Instance.SceneSettings.TrackableAdded.RemoveListener(OnTrackableAdded);
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

            if (!string.IsNullOrEmpty(markerPayload) && trackable.MarkerPayloadString != markerPayload)
            {
                Debug.Log($"[SpellGame] Ignoring QR code \"{trackable.MarkerPayloadString}\": not the floor marker");
                return;
            }

            _marker = trackable;
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

            UpdateMarker();
        }

        /// <summary>
        /// While unaligned, averages the floor marker's pose over <see cref="markerLockSeconds"/> of tracking, then
        /// makes its center the origin (its height is the floor) and its top, flattened, the +z axis.
        /// </summary>
        private void UpdateMarker()
        {
            if (IsAligned(_space) || _calibrating || _marker == null || !_marker.IsTracked)
            {
                _markerSeenFor = 0f;
                _markerSamples = 0;
                _markerPositionSum = _markerForwardSum = Vector3.zero;
                return;
            }

            // MRUK places trackables in tracking-space coordinates; the rig may already be moved by an alignment.
            var trackingSpace = cameraRig.trackingSpace;
            var rotation = trackingSpace.rotation * _marker.transform.rotation;
            var normal = rotation * Vector3.forward;
            var top = rotation * Vector3.up;
            if (Mathf.Max(Mathf.Abs(normal.y), Mathf.Abs(top.y)) < 0.8f)
            {
                gameClient.SetSpaceStatus("Lay the marker flat on the floor");
                return;
            }

            var along = Mathf.Abs(normal.y) > Mathf.Abs(top.y) ? top : normal;
            _markerPositionSum += trackingSpace.TransformPoint(_marker.transform.position);
            _markerForwardSum += new Vector3(along.x, 0f, along.z).normalized;
            _markerSamples++;
            _markerSeenFor += Time.deltaTime;
            gameClient.SetSpaceStatus("Marker found, hold still…");
            if (_markerSeenFor < markerLockSeconds)
                return;

            var yaw = Mathf.Atan2(_markerForwardSum.x, _markerForwardSum.z) * Mathf.Rad2Deg + markerYawOffset;
            AlignTo(new Pose(_markerPositionSum / _markerSamples, Quaternion.Euler(0f, yaw, 0f)));
            _alignedTo = MarkerKey(_space);
            gameClient.Send(new AlignedMessage { Method = AlignMethod.Marker });
            gameClient.SetSpaceStatus("Room calibrated on the marker");
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
                    gameClient.SetSpaceStatus(CalibratePrompt);
                return;
            }

            if (space.AnchorUuid == null)
            {
                if (space.HostId == gameClient.PlayerId && _sharedInGroup != space.GroupUuid)
                    await Run(() => ShareAnchorAsync(space), "Sharing the room anchor failed");
                else if (!IsAligned(space))
                    gameClient.SetSpaceStatus($"Waiting for {space.HostId ?? "a host"} to share the room anchor…");
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
                gameClient.SetSpaceStatus($"{failure}. {CalibratePrompt}");
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
            gameClient.SetSpaceStatus("Placing the room anchor: stand on your spot, facing the other player");
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
            gameClient.SetSpaceStatus("Room anchor shared, aligning…");
        }

        private async Task AlignToAnchorAsync(SpaceMessage space)
        {
            gameClient.SetSpaceStatus("Aligning to the room anchor…");
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
            gameClient.SetSpaceStatus("Aligned to the room anchor");
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
                gameClient.SetSpaceStatus("Hold still: calibrating…");
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
                    gameClient.SetSpaceStatus("Point the right controller at the other player, then click the left stick again");
                    return;
                }

                var space = _space;
                tip /= samples;
                var yaw = Mathf.Atan2(pointing.x, pointing.z) * Mathf.Rad2Deg;
                var floorY = cameraRig.trackingSpace.position.y;
                AlignTo(new Pose(new Vector3(tip.x, floorY, tip.z), Quaternion.Euler(0f, yaw - space.SpotYaw, 0f)));
                _alignedTo = CenterKey(space);
                gameClient.Send(new AlignedMessage { Method = AlignMethod.Center });
                gameClient.SetSpaceStatus("Room calibrated: walk back to your side");
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
