using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using SpellGame.Protocol;
using UnityEngine;

namespace SpellGame.Game
{
    /// <summary>
    /// Moves this headset's tracking space into the shared room frame (architecture.md §5.1), so every pose it streams
    /// and every spell it draws uses the same origin as the other headset.
    /// <list type="bullet">
    /// <item>Host: creates an <see cref="OVRSpatialAnchor"/> at the frame's origin, saves it, shares it to the server's
    /// group UUID and sends <c>anchor_shared</c>.</item>
    /// <item>Everyone: loads that anchor, moves the camera rig so the anchor is the origin and sends <c>aligned</c>.</item>
    /// <item>Fallback: stand on your marked floor spot facing the other player and click the left thumbstick.</item>
    /// </list>
    /// Clicking the right thumbstick sends <c>space_reset</c>: the host places a fresh anchor and everyone re-aligns.
    /// </summary>
    public sealed class SharedSpaceAligner : MonoBehaviour
    {
        [SerializeField] private GameClient gameClient;
        [SerializeField] private OVRCameraRig cameraRig;

        [Tooltip("Skip Shared Spatial Anchors: only align with the floor-spot fallback.")]
        [SerializeField] private bool floorSpotsOnly;

        [Tooltip("Time for the host to stand on their spot, facing the other player, before the anchor is placed.")]
        [SerializeField] private float placementDelaySeconds = 3f;

        [SerializeField] private float localizeTimeoutSeconds = 10f;
        [SerializeField] private int loadAttempts = 5;

        private SpaceMessage _space;
        private OVRSpatialAnchor _anchor;
        private string _sharedInGroup;
        private string _alignedTo;
        private bool _busy;

        /// <summary>
        /// Called when the player says they're ready: they're standing on their spot facing the other player, so a
        /// headset that isn't aligned yet (anchor still loading, or sharing failed offline) aligns to its floor spot.
        /// </summary>
        public void AlignToFloorSpotIfUnaligned()
        {
            if (_space != null && _alignedTo == null)
                AlignToFloorSpot(force: true);
        }

        private void OnEnable() => gameClient.SpaceReceived += OnSpace;

        private void OnDisable() => gameClient.SpaceReceived -= OnSpace;

        // OVRManager.display is created in OVRManager.Awake, so subscribe once every Awake has run.
        private void Start() => OVRManager.display.RecenteredPose += OnRecentered;

        private void OnDestroy() => OVRManager.display.RecenteredPose -= OnRecentered;

        /// <summary>
        /// A recenter moves the headset's tracking origin, so the offset from the last alignment no longer lands on the
        /// shared frame: align again (to the anchor automatically; floor spots need the player back on their spot).
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
                AlignToFloorSpot();
            if (OVRInput.GetDown(OVRInput.Button.PrimaryThumbstick, OVRInput.Controller.RTouch))
                gameClient.Send(new SpaceResetMessage());
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
            if (floorSpotsOnly)
            {
                if (_alignedTo != FloorSpotKey(space))
                    gameClient.SetSpaceStatus("Stand on your spot facing the other player, then click the left thumbstick");
                return;
            }

            if (space.AnchorUuid == null)
            {
                if (space.HostId == gameClient.PlayerId && _sharedInGroup != space.GroupUuid)
                    await Run(() => ShareAnchorAsync(space), "Sharing the room anchor failed");
                else if (_alignedTo != FloorSpotKey(space))
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
                gameClient.SetSpaceStatus($"{failure}. Stand on your spot and click the left thumbstick");
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

        /// <summary>The floor-spot fallback: this player is standing on their spot, facing <c>spot_yaw</c>.</summary>
        private void AlignToFloorSpot(bool force = false)
        {
            if ((_busy && !force) || _space == null)
                return;

            AlignTo(OriginFromFloorSpot(_space));
            _alignedTo = FloorSpotKey(_space);
            gameClient.Send(new AlignedMessage { Method = AlignMethod.FloorSpots });
            gameClient.SetSpaceStatus("Aligned to your floor spot");
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

        private static string FloorSpotKey(SpaceMessage space) => $"{AlignMethod.FloorSpots}:{space.GroupUuid}";

        private void DestroyAnchor()
        {
            if (_anchor != null)
                Destroy(_anchor.gameObject);
            _anchor = null;
        }
    }
}
