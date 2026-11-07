// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "BandProbe",
    platforms: [.macOS(.v14)],
    dependencies: [
        // Local checkout of https://github.com/Axo-Neurotech/Kinesis-Axo next to this repo.
        .package(path: "../../../Kinesis-Axo"),
    ],
    targets: [
        .executableTarget(
            name: "BandProbe",
            dependencies: [.product(name: "KinesisCore", package: "Kinesis-Axo")],
            // CoreBluetooth needs NSBluetoothAlwaysUsageDescription, even in a command-line tool.
            linkerSettings: [.unsafeFlags(["-Xlinker", "-sectcreate", "-Xlinker", "__TEXT",
                                           "-Xlinker", "__info_plist", "-Xlinker", "Info.plist"])]
        ),
    ]
)
