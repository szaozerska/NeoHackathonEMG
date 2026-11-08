# vr-client: Meta Quest 3 (Unity)

The VR client from [architecture.md](../../architecture.md) §2.1. It finds the server on the LAN, streams the local
upper-body pose, and renders the state the server sends back. It runs no game mechanics.

## Requirements

- Unity **6000.6.8f1** (see `ProjectSettings/ProjectVersion.txt`) with **Android Build Support**, including the
  OpenJDK and Android SDK & NDK Tools. Add them in Unity Hub → Installs → ⋯ → Add modules, or from the CLI:
  ```bash
  "/Applications/Unity Hub.app/Contents/MacOS/Unity Hub" -- --headless install-modules --version 6000.6.8f1 -m android android-sdk-ndk-tools android-open-jdk
  ```
- A Quest 3 in developer mode, connected over USB or Air Link.

## Packages

| Package | Why |
|---|---|
| `com.meta.xr.sdk.core` 207.0.1 (Meta scoped registry `npm.developer.oculus.com`) | OVRCameraRig, OVRManager, OVRBody/OVRSkeleton body tracking, OpenXR Meta features, Project Setup Tool |
| `com.meta.xr.sdk.movement` (git, pinned commit) | Movement SDK: retargeting and body-tracking samples for when we put avatars on the joints |
| `com.unity.xr.openxr` 1.19.0 | Meta's recommended XR provider (the Oculus XR plugin is deprecated) |
| `com.unity.render-pipelines.universal` 17.6.0 | URP, the recommended pipeline for Quest |
| `com.unity.inputsystem` 1.20.0 | Controller and debug input |
| `com.unity.nuget.newtonsoft-json` 3.2.2 | NDJSON wire protocol (`JsonUtility` can't do polymorphic messages) |

## Layout

```
Assets/SpellGame/
  Runtime/                     SpellGame.Runtime assembly
    Protocol/Messages.cs       §4.2 + §6 message classes (snake_case on the wire)
    Protocol/MessageCodec.cs   NDJSON encode / decode by "type"
    Networking/ServerDiscovery.cs      UDP beacon "SPELLGAME <port>" on 47777 (§4.1)
    Networking/AndroidMulticastLock.cs WifiManager.MulticastLock so the Quest receives broadcasts
    Networking/ServerConnection.cs     TCP (NoDelay), background line reader, main-thread decode
    Tracking/BodyPoseSampler.cs        OVRSkeleton (FullBody) → head/chest/hips/arms/hands/legs/feet
    Game/GameClient.cs         Composition root: discover → connect → hello → stream pose, dispatch state
    Game/DebugSkeletonsView.cs Draws local and remote skeletons as debug line segments
    Game/ControllerBand.cs     Debug band: Touch trigger = snap, grip = fist, A/X = open palm, sent as this headset's classifier
    Game/PairingButton.cs      holding X+Y on the left controller for 3 s sends pair_start: the server starts pairing mode (§5)
    Game/SharedSpaceAligner.cs Shared room frame (§5.1): host shares an OVRSpatialAnchor, everyone aligns the rig to it; floor-spot fallback
    Game/FireballView.cs       Fireball visuals: snap burst, held orb on the band hand, projectile + trail, impact, cooldown ember
    Game/SwordView.cs          Sword visuals: draw/sheathe flash, glowing blade along the forearm, speed-scaled swing trail, hit sparks
    Game/ShieldView.cs         Shield visuals: disc in front of the band hand, swells with push boost, block/parry flashes
    Game/SpellVfx.cs           Procedural orbs, blades, trails and particle bursts (no art assets yet)
  Editor/                      SpellGame.Editor assembly
    QuestProjectConfigurator.cs  Menu "SpellGame/Configure Project for Quest 3"
    MainSceneBuilder.cs          Menu "SpellGame/Rebuild Main Scene"
    QuestBuild.cs                Menus "SpellGame/Build APK", "Build And Run On Headset"; headless QuestBuild.BuildBatch
  Scenes/Main.unity            OVRCameraRig with passthrough + body tracking + debug skeletons + GameClient + pairing button + shared-space aligner + status label + Fireball View + Sword View + Shield View
```

`GameClient` raises `SignReceived`, `SpellReceived`, `DamageReceived`, `ImpactReceived` and `StateReceived`, and
`TryGetJoints(playerId)` gives the latest joints (local tracking for the local player). Gameplay views (spell VFX, HP bars)
subscribe to these events and never touch the network. The local player's body is rendered from local tracking.
The client ignores its own pose when the server echoes it back.

## One-time setup

1. Open `apps/vr-client` in Unity 6000.6.8f1, then switch the platform to **Android** (File → Build Profiles).
2. Run **SpellGame → Configure Project for Quest 3**. This sets IL2CPP/ARM64, API 32+, Vulkan and Linear color.
   It also sets up URP, the OpenXR loader with Meta XR, Meta Quest Support and the Touch controller profiles,
   requires body tracking and passthrough in the OVR project config, and generates `Assets/Plugins/Android/AndroidManifest.xml`
   with the LAN multicast permissions. Headless version:
   ```bash
   Unity -batchmode -quit -projectPath . -buildTarget Android -executeMethod SpellGame.Editor.QuestProjectConfigurator.Configure
   ```
3. Open **Window → Meta → Tools → Project Setup Tool** and click **Fix All** on the Android and Standalone tabs.
4. Use **SpellGame → Rebuild Main Scene** to regenerate `Scenes/Main.unity` at any time.

## Running

- **Server address:** leave `Game Client → Manual Server Host` empty to use the UDP discovery beacon. Set an IP to skip
  discovery (the manual fallback from §4.1).
- **On device (the only headset path on macOS):** File → Build Profiles → Android → Build And Run, with the Quest
  connected over USB. Quest Link and Air Link are Windows-only, so on a Mac every headset test is an APK build.
- **In the Editor without a headset:** turn on the Meta XR Simulator from the Meta toolbar button (or Window → Meta →
  Meta XR Simulator → Activate). The editor offers to download it the first time. Then press Play. It simulates body tracking, which is enough to
  exercise discovery, the pose stream and server state against a local server.
- **Windows teammates** can instead connect the Quest with Quest Link or Air Link and press Play. The Standalone target
  uses the same OpenXR and Meta setup.
- On first launch the headset asks for body-tracking permission. Grant it, or no pose packets are sent.
- **Pairing a Neural Band:** hold **X+Y** on the left controller for 3 seconds (or `p` in the server's monitor) to start pairing mode.
  The status label tells the prompted player to pinch and everyone else whose turn it is, then shows "band paired".
- **No Guardian boundary:** the app asks the OS to hide the boundary while passthrough is on
  (`OVRManager.shouldBoundaryVisibilityBeSuppressed`, Boundary Visibility Support in **Configure Quest Project**), so
  players can move around the whole room. The OS may still ask for a boundary at launch and can refuse to hide it;
  the boundary size you set doesn't matter then.
- **Shared room frame (§5.1):** both headsets have to be in one coordinate frame before hits between players mean anything.
  - The anchor host (the first headset to join) should stand on their spot facing the other player when the app starts.
    About 3 s after joining it places a Shared Spatial Anchor there, shares it, and every headset aligns to it.
    The second status line shows progress.
  - Anchor sharing needs internet, a Meta account on each headset, and **Settings → Privacy → Enhanced Spatial Services**
    turned on.
  - **Fallback:** if sharing fails, each player stands on their marked floor spot (`--spot-distance` apart, default
    3 m), faces the other player and **clicks the left thumbstick**. In a 2-player match, pressing **I'm ready!** does
    the same for a headset that isn't aligned yet, and the server holds the countdown until both headsets are aligned. Tick `Floor Spots Only` on the Shared Space Aligner to
    skip anchors entirely.
  - **Re-anchor:** **click the right thumbstick** (or press `a` in the server monitor) after tracking was lost or the
    anchor drifted.
