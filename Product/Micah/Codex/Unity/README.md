# Unity CLI collaboration workspace

Micah's Unity project is `Product/Micah/Unity/HackathonEMG`. Codex tooling lives beside this guide. `Product/current` remains a placeholder until Micah approves a finalized build.

## Installation and project

- CLI: `unity` version `1.0.0-beta.13`, installed at `/Users/micahb/.unity/bin/unity` on Micah's Mac.
- Editor: `6000.6.8f1` (`237b6593792b`), arm64, with Web support installed.
- Editor binary on this Mac: `/Applications/Unity/Hub/Editor/6000.6.8f1/Unity.app/Contents/MacOS/Unity`.
- Project: local Unity 3D URP template `com.unity.template.urp-blank` version `17.2.6`.
- Included scene: `Assets/Scenes/SampleScene.unity`, enabled in build settings.
- Serialization: Force Text, as supplied by the template.

The project files were extracted by the Unity CLI. Initial Editor import failed because the agent sandbox denies Unity Package Manager's local socket (`listen EPERM`). ProjectVersion.txt was restored using the exact Editor version/revision reported in that run's log. This is a starter project, with no EMG integration or custom gameplay yet. An import, live Editor connection, and build are still required before calling it runtime-verified. The template includes a package lockfile; refresh and commit it after successful package resolution and Pipeline installation.

## Finish setup

From the repository root, with this project's Editor closed:

```sh
bash Product/Micah/Codex/Unity/workspace.sh setup
```

Setup imports the existing project, installs Unity's Pipeline package, opens the Editor, waits for this project to report ready, and discovers its commands. It stops on any error. It requires working Unity licensing, package network access, and local sockets. If Unity requests sign-in, use `unity auth login` in your Terminal and sign in to Unity Hub as needed; then rerun setup. Setup does not create a cloud project or change GitHub access.

## How Codex co-works with the Editor

```sh
bash Product/Micah/Codex/Unity/workspace.sh open
bash Product/Micah/Codex/Unity/workspace.sh status
bash Product/Micah/Codex/Unity/workspace.sh commands
bash Product/Micah/Codex/Unity/workspace.sh recompile
bash Product/Micah/Codex/Unity/workspace.sh verify
```

Every operation targets the absolute path of Micah's project. A connected Editor needs `com.unity.pipeline`; the standalone CLI alone cannot edit scenes. After command discovery, use `workspace.sh command <command> [arguments]` to run an available command. Use the discovered schemas before editing. Pipeline exposes scene/asset operations and C# evaluation so Codex can author GameObjects, attach components, inspect the hierarchy, save scenes, read errors, and drive Play mode. Availability depends on the installed package; do not assume a command name without discovery.

Codex writes C# source under this project's `Assets`, recompiles, inspects errors, and uses Editor commands to author scenes and assets. It must verify Play mode advances, inspect the console, and save the scene before claiming a working demo. If the Editor cannot connect or a command times out, report it and diagnose; do not silently target a teammate's Editor. Opening Unity from an unrestricted Terminal does not automatically grant the agent sandbox permission to connect to it.

Before a batch import/build, close this project's interactive Editor:

```sh
bash Product/Micah/Codex/Unity/workspace.sh import
bash Product/Micah/Codex/Unity/workspace.sh build
```

Build output goes to this folder's ignored `Builds/WebGL`, never to `Product/current`. No player build has been verified yet.

## Team Git workflow

Install the Editor version in `ProjectSettings/ProjectVersion.txt`. Pull before starting work; use a personal feature branch, coordinate scene/prefab edits, and include `.meta` files with assets. Commit `Assets`, `Packages` (including the generated lockfile), and `ProjectSettings`. Exclude `Library`, `Temp`, `Logs`, `UserSettings`, and local build output. Contributors can keep prototypes in their named folders; shared promotion requires Micah's approval.

The first scaffold is already on `main`. To publish this Unity setup from a normal Terminal if the agent remains restricted:

```sh
bash Product/Micah/Codex/Unity/publish-work.sh
```

That script verifies the expected origin/main branch, refuses pre-existing staged changes, stages only Micah's Unity project/tooling, commits, and pushes without force. Git hooks are disabled for its operations so unrelated hooks are not loaded. The old `push-scaffold.sh` was a one-time bootstrap for the initially empty folder; it intentionally refuses an existing checkout.

Pushing shares code with existing repository collaborators; it does not invite teammates or grant repository permissions.

## Verification and limits

The CLI's project integrity check passed with zero findings (missing/orphan metadata, duplicate GUIDs, conflict markers, and manifest validity). Shell scripts passed Bash syntax checks. Editor import, Pipeline connection, Play mode, and WebGL output remain unverified because the sandbox blocks required local IPC/network capabilities. Check current command output rather than interpreting file presence as a successful import.

## Official references

- [Unity CLI and Pipeline package](https://docs.unity.com/en-us/unity-cli/unity-pipeline/unity-pipeline-package)
- [Editor command line arguments](https://docs.unity.com/en-us/engine/6000.6/manual/unity-editor/command-line-arguments/editor)
- [Command line builds](https://docs.unity.com/en-us/engine/6000.6/manual/building-and-publishing/build-command-line)
- Local command help: `unity skill show`, `unity pipeline install --help`, `unity command --help`.
