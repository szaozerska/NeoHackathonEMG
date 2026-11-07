# Unity workspace and local CLI guide

This is Codex's active workspace for Micah. Keep scripts, prototypes, notes, and generated builds here until Micah explicitly approves moving work into `Product/current`.

## Verified local installation

- Unity CLI: `unity`, version `1.0.0-beta.13`.
- CLI binary: `/Users/micahb/.unity/bin/unity` (also resolves as `Unity` on this Mac).
- Editor: `6000.6.8f1`, Apple Silicon (`arm64`).
- Editor binary: `/Applications/Unity/Hub/Editor/6000.6.8f1/Unity.app/Contents/MacOS/Unity`.
- The installed Editor reports the Web module.

The installed CLI help and official Unity 6.6 documentation were checked. Only CLI discovery and installation inventory were run; no Unity project has been created, opened, tested, or built yet.

## Start a project when implementation begins

Run from the repository root:

```sh
unity --help
unity editors --installed --format json
unity projects new HackathonEMG --path "$PWD/Product/Micah/Unity" --editor-version 6000.6.8f1
unity open "$PWD/Product/Micah/Unity/HackathonEMG"
```

A Unity project contains `Assets`, `Packages`, and `ProjectSettings`. The placeholder directories in this scaffold are not Unity projects yet. Choose a 2D/3D/rendering template when the product requirements are established. Keep all teammates on the version recorded in the project's `ProjectSettings/ProjectVersion.txt`.

## Work in Unity

Create scenes and GameObjects in the Editor; put C# MonoBehaviour scripts and assets under the project's `Assets` folder. Attach components to GameObjects, save scenes, and enter Play mode to check behavior. Add intended demo scenes to a build profile before building.

Commit `Assets` and their `.meta` files, `Packages` (including its lockfile), and `ProjectSettings`. Use Visible Meta Files and Force Text serialization for team version control. Coordinate edits to shared scenes and prefabs.

## CLI workflow after a project exists

```sh
# Run these from the repository root.
unity projects verify "$PWD/Product/Micah/Unity/HackathonEMG"
unity run "$PWD/Product/Micah/Unity/HackathonEMG" --timeout 300 -- -nographics

# Requires a configured Unity Test Framework and actual tests.
unity test "$PWD/Product/Micah/Unity/HackathonEMG" --mode EditMode --output "$PWD/Product/Micah/Codex/Unity/TestResults/editmode.xml" --timeout 300

# Requires configured build scenes/profile and platform support.
unity build "$PWD/Product/Micah/Unity/HackathonEMG" --target WebGL --output-path "$PWD/Product/Micah/Codex/Unity/Builds/WebGL" --timeout 600
```

Close the project in the Editor before starting another Editor process in batch mode for that same project. Create output directories as needed. Package downloads and license verification may need network access.

Live Editor automation uses the optional `com.unity.pipeline` package. Inspect `unity pipeline --help` before installing it into Micah's project. With that package installed and the project open, inspect commands with `unity list --project-path <absolute-project-path>` and target the same project explicitly in every command. Always verify Play mode actually advances and check the console for errors.

Direct Editor invocation, without the CLI wrapper:

```sh
"/Applications/Unity/Hub/Editor/6000.6.8f1/Unity.app/Contents/MacOS/Unity" \
  -batchmode -quit -nographics \
  -projectPath "$PWD/Product/Micah/Unity/HackathonEMG" \
  -logFile "$PWD/Product/Micah/Codex/Unity/editor.log"
```

For custom build scripts, use a public static Editor method with `-executeMethod Namespace.Class.Method` and inspect the Editor exit code and build report.

## Official references

- [Unity 6.6 manual](https://docs.unity.com/en-us/engine/6000.6/manual)
- [Editor command line arguments](https://docs.unity.com/en-us/engine/6000.6/manual/unity-editor/command-line-arguments/editor)
- [Command line builds](https://docs.unity.com/en-us/engine/6000.6/manual/building-and-publishing/build-command-line)
- Local CLI references: `unity skill show`, `unity open --help`, `unity run --help`, `unity build --help`, `unity test --help`.
