# Quest 3 recording app

The Unity project is `apps/vr-client`. It contains a local recorder package and a manifest pinned to **Meta XR Core 207.0.1 / Movement 207.0.0**, with verified registry/commit availability. The project targets the Unity editor installed on this Mac, 6000.6.8f1. Install Android Build Support, Android SDK/NDK and OpenJDK through Unity Hub if missing.

Official references:

- [Quest developer-mode and USB debugging setup](https://developers.meta.com/vr/documentation/native/android/mobile-device-setup/)
- [Meta XR Core SDK package](https://assetstore.unity.com/packages/tools/integration/meta-xr-core-sdk-269169)
- [Official Movement SDK source and setup](https://github.com/oculus-samples/Unity-Movement/tree/77274f138974087ba2909bab2723fc6ff851338b)
- [OVRHand v81 API](https://developers.meta.com/horizon/reference/unity/v81/class_o_v_r_hand)
- [OVRSkeleton v81 API](https://developers.meta.com/horizon/reference/unity/v81/class_o_v_r_skeleton)

## Create and install the scene

1. Enable developer mode on the Quest and authorize USB debugging from your Mac using a USB data cable. This is for installation/debugging; recording subsequently uses Wi-Fi.
2. In Unity Hub, add/open `apps/vr-client`. Wait for Package Manager to resolve the pinned SDKs. Do not copy vendor SDK code into our package.
3. Open the included **Assets/Scenes/SpellRecorder.unity** scene. To recreate it in a fresh project, choose **Spell Training → Create complete training scene**. The menu creates `Assets/Scenes/SpellRecorder.unity` without overwriting an existing scene. It adds an OVR camera rig, right-hand tracking prefab, upper-body tracking skeleton, a visible calibration target, and our sender with references assigned. The adapter auto-enables when the pinned Meta core package is present. Do not rerun scene creation over an existing scene.
4. Select **Spell Training Recorder** in the Hierarchy. Set its sender's **Mac Address** to your Mac's LAN IPv4 address. Leave empty only if UDP broadcast discovery works on your network. Keep TCP port 9000 and sample rate 60 initially.
5. Switch Build Profile to **Android**. In **Project Settings → XR Plug-in Management → Android**, confirm **Oculus** is enabled. The scene builder configures it; **Spell Training → Configure Android XR loader** can reapply this after installing Android support. Use Meta's **Project Setup Tool** to resolve required Android/Quest settings. The scene builder selects ARM64/IL2CPP, requests Internet permission and body tracking, and enables hands-only tracking. Confirm the tool reports no required issues before deploying.
6. Build and Run to the Quest. Accept the headset's body tracking permission prompt. The camera rig and SDK perform tracking; the sender does not access raw camera pixels.
7. Start the Mac recorder and put both devices on the same LAN. Allow the Python recorder through the Mac firewall. The dashboard should show Quest packets and clock RTT.
8. Face the open right palm directly toward the scene's calibration target, hold still, and have the operator click **Calibrate palm facing target** on the Mac. This measures the wrist-local anatomical palm normal. Until calibration, hand observations are marked invalid for spell recognition; packets still arrive.
9. Confirm hand/chest validity while moving, especially at the left hip. Capture the `hip_calibration` interval on the Mac. Test sharp pushes and throws before recording the full dataset.

The project includes a generated training scene and compiled SDK integration, not a prebuilt signed APK. Android Build Support is not installed in the Unity editor currently on this Mac; add that module in Unity Hub before building. Building and testing on the physical headset remains necessary. Optional Movement sample scenes may be imported from Package Manager for debugging, but the recorder's scene builder does not require rendering a full avatar.

## Coordinate and calibration behavior

The scene uses the rig origin as a meter-scale game frame (+X right, +Y up, +Z forward). The target at approximately `(0, 1.4, 3)` establishes the default opponent direction. In the real game, assign the actual opponent target/common world transform.

The hand adapter handles both OVR and OpenXR wrist bone conventions and upper/full-body chest bones. It reads `OVRHand` and `OVRSkeleton` validity/confidence. It does not substitute a head-fixed estimated chest when body tracking is unavailable. Palm calibration is repeated every app session; it is not a learned EMG label.

After recentering or moving the rig origin, use **Reset coordinate history** on the Mac, or call `SpellQuestSender.ResetCoordinateFrame()` from the game's recenter handler. That changes the frame ID and clears trajectory-based detection history on the Mac. Do not mix recordings from a coordinate jump into one motion.

## Reusing the package in another Unity project

Use **Package Manager → Add package from disk** and select:

`apps/vr-client/Packages/com.neohackathon.spell-recorder/package.json`

Import the pinned compatible Meta SDK packages first. The runtime adapter is in `SpellTraining.Meta`; the standalone transport/data contracts are in `SpellTraining.Core`. The provider API is `SpellTrackingSource.Read(PoseObservation)`, so another tracking stack can be adapted without changing the Mac recorder.

The Quest does not classify shield/sword/fireball, calculate damage, or decide launches. It serializes tracking observations and calibration status. Its worker thread handles TCP; Unity SDK reads stay on the main thread. Backlogs trigger reconnects instead of delivering an unbounded stale queue.

## Troubleshooting

- **Packets, but invalid hand:** confirm the right-hand prefab, tracking confidence, palm calibration, and camera visibility.
- **Invalid chest:** confirm body tracking permission, upper-body skeleton/provider, and Project Setup Tool settings. Do not train spatial rules from invalid tracking.
- **Cannot connect:** use the Mac LAN IP, verify the firewall and shared network, and avoid guest Wi-Fi/client isolation. `127.0.0.1` on the headset refers to the headset itself.
- **Missing setup menu:** wait for script compilation; inspect Console for package errors. The Meta-specific menu requires the pinned Core package and its matching compile-time version define.
- **No Android build target:** install Unity's Android support modules through Unity Hub.
- **Tracking discontinuity after recenter:** reset coordinate history and repeat calibration if the target or game origin changed.

The installed Unity 6000.6 editor cannot compile older Meta Core v81 because that SDK uses an XR namespace removed from newer Unity. The delivered manifest therefore pins the verified current Core 207.0.1 and Movement commit above. API v81 references explain the established hand/skeleton interfaces; the delivered adapter was checked by compiling the actual pinned project.
