import SwiftUI

/// The original Axo mark keeps its published colors; the surrounding typography follows the app theme.
struct AxoBrandLockup: View {
    private static let image = Bundle.kinesis.url(forResource: "axo-mark", withExtension: "png")
        .flatMap(NSImage.init(contentsOf:))

    var body: some View {
        HStack(spacing: 11) {
            if let image = Self.image {
                Image(nsImage: image)
                    .resizable()
                    .interpolation(.high)
                    .scaledToFit()
                    .frame(width: 36, height: 36)
                    .accessibilityHidden(true)
            }
            VStack(alignment: .leading, spacing: 3) {
                Text("AXO NEUROTECH")
                    .font(.system(size: 9, weight: .medium, design: .monospaced))
                    .tracking(1.25)
                    .foregroundStyle(KinesisStyle.accent)
                Text("Kinesis")
                    .font(.system(size: 18, weight: .medium))
                    .tracking(-0.35)
                    .foregroundStyle(KinesisStyle.ink)
            }
            .fixedSize(horizontal: true, vertical: true)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Axo Neurotech, Kinesis")
    }
}

/// A static signal motif. It has no clock and never competes with the live sensor views for redraws.
struct AxoSignalField: View {
    private static let nodes: [CGPoint] = [
        CGPoint(x: 0.06, y: 0.23), CGPoint(x: 0.30, y: 0.31),
        CGPoint(x: 0.53, y: 0.20), CGPoint(x: 0.79, y: 0.29),
        CGPoint(x: 0.96, y: 0.17), CGPoint(x: 0.12, y: 0.63),
        CGPoint(x: 0.39, y: 0.57), CGPoint(x: 0.64, y: 0.69),
        CGPoint(x: 0.91, y: 0.58), CGPoint(x: 0.27, y: 0.90),
        CGPoint(x: 0.76, y: 0.93),
    ]
    private static let connections: [(Int, Int)] = [
        (0, 1), (1, 2), (2, 3), (3, 4), (1, 6),
        (5, 6), (6, 7), (7, 8), (6, 9), (7, 10),
    ]

    var body: some View {
        Canvas { context, size in
            let points = Self.nodes.map { CGPoint(x: $0.x * size.width, y: $0.y * size.height) }
            var branches = Path()
            for (start, end) in Self.connections {
                let a = points[start], b = points[end]
                branches.move(to: a)
                branches.addCurve(to: b,
                                  control1: CGPoint(x: a.x + (b.x - a.x) * 0.55, y: a.y),
                                  control2: CGPoint(x: b.x - (b.x - a.x) * 0.55, y: b.y))
            }
            context.stroke(branches, with: .color(KinesisStyle.accent.opacity(0.075)),
                           style: StrokeStyle(lineWidth: 0.75, lineCap: .round))
            for (index, point) in points.enumerated() {
                let radius: CGFloat = index == 1 || index == 6 || index == 7 ? 2.2 : 1.4
                let dot = CGRect(x: point.x - radius, y: point.y - radius,
                                 width: radius * 2, height: radius * 2)
                context.fill(Path(ellipseIn: dot), with: .color(KinesisStyle.accent.opacity(0.18)))
            }
        }
        .accessibilityHidden(true)
        .allowsHitTesting(false)
    }
}
