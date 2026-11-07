// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "BandProbe",
    platforms: [.macOS(.v14)],
    dependencies: [
        // The patched Kinesis-Axo in this repo.
        .package(path: "../kinesis-axo"),
    ],
    targets: [
        .executableTarget(
            name: "BandProbe",
            dependencies: [.product(name: "KinesisCore", package: "kinesis-axo")],
            // CoreBluetooth needs NSBluetoothAlwaysUsageDescription, even in a command-line tool.
            linkerSettings: [.unsafeFlags(["-Xlinker", "-sectcreate", "-Xlinker", "__TEXT",
                                           "-Xlinker", "__info_plist", "-Xlinker", "Info.plist"])]
        ),
    ]
)
