import SwiftUI

enum AppAppearance: String, CaseIterable, Identifiable {
    case system, light, dark
    var id: String { rawValue }
    var colorScheme: ColorScheme? {
        switch self {
        case .system: nil
        case .light: .light
        case .dark: .dark
        }
    }
}

struct AppearanceMenu: View {
    var compact = false
    @AppStorage("appearance") private var appearance = AppAppearance.system
    var body: some View {
        if compact {
            menu.buttonStyle(KinesisIconStyle())
        } else {
            menu.buttonStyle(KinesisPressStyle())
        }
    }

    private var menu: some View {
        Menu {
            ForEach(AppAppearance.allCases) { option in
                Button { appearance = option } label: {
                    if appearance == option { Label(option.rawValue, systemImage: "checkmark") }
                    else { Text(option.rawValue) }
                }
            }
        } label: {
            if compact { Image(systemName: "circle.lefthalf.filled").font(.system(size: 15)) }
            else {
                HStack(spacing: 10) {
                    Image(systemName: "circle.lefthalf.filled").frame(width: 20)
                    Text("appearance")
                    Spacer(minLength: 0)
                    Image(systemName: "chevron.down").font(.system(size: 9))
                }.font(.system(size: 12))
            }
        }.menuStyle(.button).menuIndicator(.hidden)
            .fixedSize(horizontal: compact, vertical: true).accessibilityLabel("Appearance")
    }
}

/// Axo's public design tokens: teal fields, sage feedback, snow surfaces, and rose alerts.
/// Text accents differ by appearance so the same controls stay legible in both modes.
enum KinesisStyle {
    /// The window is one field of soft tone, lighter at the top. Sheets use `paper`, its middle.
    static let fieldTop = adaptive(light: rgb(0xF9F4F5), dark: rgb(0x0A4C52))
    static let fieldBottom = adaptive(light: rgb(0xF2EEEF), dark: rgb(0x16302F))
    static let paper = adaptive(light: rgb(0xF9F4F5), dark: rgb(0x0A4C52))
    static let sidebarTop = adaptive(light: rgb(0x73BA9B, alpha: 0.16), dark: rgb(0x9FD3BB, alpha: 0.035))
    static let sidebarBottom = adaptive(light: rgb(0x73BA9B, alpha: 0.28), dark: rgb(0x16302F, alpha: 0.3))
    /// The soft light an object sits in: the band, the hand.
    static let pool = adaptive(light: NSColor(white: 1, alpha: 0.78), dark: rgb(0x9FD3BB, alpha: 0.12))
    static let ink = adaptive(light: rgb(0x16302F), dark: rgb(0xEAF3F2))
    static let secondary = adaptive(light: rgb(0x4C5D5B), dark: rgb(0xB8DCD3))
    static let surface = adaptive(light: NSColor(white: 1, alpha: 0.68), dark: NSColor(white: 1, alpha: 0.045))
    static let line = adaptive(light: rgb(0x0D5C63, alpha: 0.15), dark: rgb(0x9FD3BB, alpha: 0.24))
    static let green = adaptive(light: rgb(0x2F6B52), dark: rgb(0x9FD3BB))
    private static let accentLight = rgb(0x0D5C63)
    private static let accentDark = rgb(0x9FD3BB)
    /// Teal on snow, mint on teal: selections and sensor feedback.
    static let accent = adaptive(light: accentLight, dark: accentDark)
    static let onAccent = adaptive(light: rgb(0xFFFFFF), dark: rgb(0x16302F))
    static let warning = adaptive(light: rgb(0xA34754), dark: rgb(0xEE9AA5))
    /// The tray that holds pills, and the chip that marks the chosen one.
    static let tray = adaptive(light: rgb(0x0D5C63, alpha: 0.07), dark: rgb(0x9FD3BB, alpha: 0.09))
    static let trayHover = adaptive(light: rgb(0x0D5C63, alpha: 0.12), dark: rgb(0x9FD3BB, alpha: 0.15))
    static let trayStrong = adaptive(light: rgb(0x0D5C63, alpha: 0.2), dark: rgb(0x9FD3BB, alpha: 0.23))
    static let chip = adaptive(light: rgb(0xFFFFFF), dark: rgb(0x9FD3BB, alpha: 0.19))

    /// The light on the hand's fingers, in linear light the way its shader mixes it into the
    /// skin. Sage keeps the feedback visible on the white hand.
    static func glow(dark: Bool) -> SIMD3<Float> {
        let color = dark ? accentDark : rgb(0x73BA9B)
        return SIMD3(Float(pow(color.redComponent, 2.2)), Float(pow(color.greenComponent, 2.2)), Float(pow(color.blueComponent, 2.2)))
    }

    private static func rgb(_ hex: UInt32, alpha: CGFloat = 1) -> NSColor {
        NSColor(red: CGFloat((hex >> 16) & 0xFF) / 255,
                green: CGFloat((hex >> 8) & 0xFF) / 255,
                blue: CGFloat(hex & 0xFF) / 255, alpha: alpha)
    }

    private static func adaptive(light: NSColor, dark: NSColor) -> Color {
        Color(nsColor: NSColor(name: nil) { appearance in
            appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua ? dark : light
        })
    }
}

/// The window's ground: one field of tone from edge to edge, with nothing boxed off.
struct Field: View {
    var body: some View {
        LinearGradient(colors: [KinesisStyle.fieldTop, KinesisStyle.fieldBottom], startPoint: .top, endPoint: .bottom)
            .ignoresSafeArea()
    }
}

/// A fine lit edge gives controls depth without changing their fill colour.
struct PillSurface: View {
    let fill: Color
    var raised = false
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        Capsule().fill(fill)
            .overlay {
                Capsule().strokeBorder(
                    LinearGradient(colors: [.white.opacity(scheme == .dark ? 0.15 : 0.7),
                                            KinesisStyle.line.opacity(0.25), KinesisStyle.line.opacity(0.7)],
                                   startPoint: .top, endPoint: .bottom), lineWidth: 0.75)
            }
            .shadow(color: .black.opacity(raised ? (scheme == .dark ? 0.18 : 0.07) : 0), radius: 3, y: 1.5)
    }
}

/// A pill. The key action is tinted with the accent. Everything else is a quiet tray.
struct KinesisButtonStyle: ButtonStyle {
    var prominent = false
    /// Fills the width it is given, as the band column's one button does.
    var wide = false
    @Environment(\.isEnabled) private var enabled
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var hovered = false
    func makeBody(configuration: Configuration) -> some View {
        let lifted = hovered && enabled
        return configuration.label
            .font(.system(size: 13, weight: .medium))
            .frame(maxWidth: wide ? .infinity : nil)
            .padding(.horizontal, 18).padding(.vertical, 12)
            .foregroundStyle(prominent ? KinesisStyle.accent : KinesisStyle.ink)
            .background {
                PillSurface(fill: prominent ? KinesisStyle.accent.opacity(lifted ? 0.2 : 0.13)
                            : (lifted ? KinesisStyle.trayHover : KinesisStyle.tray),
                            raised: enabled && !configuration.isPressed)
            }
            .overlay(Capsule().strokeBorder(prominent ? KinesisStyle.accent.opacity(0.2) : .clear, lineWidth: 0.75))
            .opacity(enabled ? (configuration.isPressed ? 0.82 : 1) : 0.45)
            .contentShape(Capsule())
            .scaleEffect(reduceMotion || !enabled ? 1 : configuration.isPressed ? 0.975 : 1)
            .animation(reduceMotion ? nil : KinesisMotion.press, value: configuration.isPressed)
            .animation(reduceMotion ? nil : KinesisMotion.settle, value: hovered)
            .onHover { hovered = $0 }
    }
}

struct KinesisPressStyle: ButtonStyle {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed && !reduceMotion ? 0.96 : 1)
            .opacity(configuration.isPressed ? 0.78 : 1)
            .animation(reduceMotion ? nil : KinesisMotion.press, value: configuration.isPressed)
    }
}

/// A bare icon in the top bar. Under the pointer it gets a soft round tray.
struct KinesisIconStyle: ButtonStyle {
    /// The quick setup arrow winds back a little under the pointer, the way it will wind setup back.
    var winds = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var hovered = false
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .rotationEffect(.degrees(winds && hovered && !reduceMotion ? -45 : 0))
            .frame(width: 30, height: 30)
            .background(Circle().fill(hovered ? KinesisStyle.tray : .clear))
            .contentShape(Circle())
            .scaleEffect(configuration.isPressed && !reduceMotion ? 0.94 : 1)
            .opacity(configuration.isPressed ? 0.78 : 1)
            .animation(reduceMotion ? nil : KinesisMotion.press, value: configuration.isPressed)
            .animation(reduceMotion ? nil : KinesisMotion.select, value: hovered)
            .onHover { hovered = $0 }
    }
}

struct BandArtwork: View {
    private static let image = Bundle.kinesis.url(forResource: "neural-band", withExtension: "png").flatMap(NSImage.init(contentsOf:))
    var body: some View {
        GeometryReader { geometry in
            if let image = Self.image {
                Image(nsImage: image).resizable().scaledToFill()
                    .frame(width: geometry.size.width, height: geometry.size.height).clipped()
            }
        }.accessibilityLabel("Meta Neural Band product image")
    }
}
