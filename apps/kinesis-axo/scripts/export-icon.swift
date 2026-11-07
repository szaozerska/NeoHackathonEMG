import AppKit
import SwiftUI

@main
struct ExportIcon {
    @MainActor static func main() throws {
        guard CommandLine.arguments.count == 3 else {
            throw CocoaError(.fileWriteInvalidFileName)
        }
        let destination = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
        guard let mark = NSImage(contentsOfFile: CommandLine.arguments[2]) else {
            throw CocoaError(.fileReadCorruptFile)
        }
        try FileManager.default.createDirectory(at: destination, withIntermediateDirectories: true)
        // Keep the published Axo artwork and colors intact; only add the macOS icon inset and shadow.
        let artwork = Image(nsImage: mark)
            .resizable()
            .interpolation(.high)
            .scaledToFit()
            .frame(width: 844, height: 844)
            .shadow(color: .black.opacity(0.24), radius: 18, y: 12)
            .frame(width: 1024, height: 1024)
        for size in [16, 32, 128, 256, 512] {
            for scale in [1, 2] {
                let renderer = ImageRenderer(content: artwork)
                renderer.scale = Double(size * scale) / 1024
                guard let image = renderer.cgImage,
                      let png = NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:]) else {
                    throw CocoaError(.fileWriteUnknown)
                }
                let name = "icon_\(size)x\(size)\(scale == 2 ? "@2x" : "").png"
                try png.write(to: destination.appendingPathComponent(name))
            }
        }
    }
}
