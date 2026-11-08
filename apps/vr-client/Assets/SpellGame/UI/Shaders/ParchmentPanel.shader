// Aged-parchment card on a plain quad for the wizard theme: a near-opaque paper body with a lighter centre, darker
// aged edges and procedural mottling, a bevelled gold border, a thin inner gold line and gold corner stars on big cards,
// an optional soft glow outside the edge (hovered / selected) and a soft drop shadow below.
// Same properties as SpellGame/UI/CrystalPanel, so UiStyle drives both: _FillColor = paper, _FacetLightColor = centre,
// _FacetDarkColor = aged edges, _RimColor = gold, _OutlineColor = glow, _Facet.z = age / grain strength,
// _CornerCut = corner radius. No textures, no blur, one pass.
// Passthrough: premultiplied-alpha "over" blending; the paper writes ~96 % alpha so text stays readable in a bright
// room, and alpha falls to 0 outside the card and its glow / shadow.
Shader "SpellGame/UI/ParchmentPanel"
{
    Properties
    {
        _FillColor ("Paper (alpha = opacity)", Color) = (0.953, 0.886, 0.722, 0.96)
        _FacetLightColor ("Centre", Color) = (0.988, 0.953, 0.847, 0.97)
        _FacetDarkColor ("Aged Edges", Color) = (0.769, 0.588, 0.329, 0.97)
        _RimColor ("Gold Border (alpha = opacity)", Color) = (0.847, 0.706, 0.353, 1)
        _OutlineColor ("Glow (alpha = opacity)", Color) = (0.588, 0.353, 0.824, 0)
        _ShadowColor ("Drop Shadow (alpha = opacity)", Color) = (0.227, 0.141, 0.071, 0.35)
        _Rect ("Rect: width, height, skew (tan), margin (m)", Vector) = (0.6, 0.2, 0, 0.015)
        _Facet ("Border width, glow width, age strength, shadow drop (m)", Vector) = (0.0035, 0, 1, 0.006)
        _CornerCut ("Corner Radius (m)", Float) = 0.004
    }
    SubShader
    {
        Tags
        {
            "RenderPipeline" = "UniversalPipeline"
            "RenderType" = "Transparent"
            "Queue" = "Transparent"
            "IgnoreProjector" = "True"
            "PreviewType" = "Plane"
        }

        Pass
        {
            Name "Parchment"
            Tags { "LightMode" = "UniversalForward" }

            Blend One OneMinusSrcAlpha, One OneMinusSrcAlpha
            ZWrite Off
            ZTest LEqual
            Cull Off

            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_instancing

            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            CBUFFER_START(UnityPerMaterial)
                float4 _FillColor;
                float4 _RimColor;
                float4 _FacetLightColor;
                float4 _FacetDarkColor;
                float4 _OutlineColor;
                float4 _ShadowColor;
                float4 _Rect;
                float4 _Facet;
                float _CornerCut;
            CBUFFER_END

            struct Attributes
            {
                float4 positionOS : POSITION;
                float2 uv : TEXCOORD0;
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float2 uv : TEXCOORD0;
                UNITY_VERTEX_OUTPUT_STEREO
            };

            Varyings vert(Attributes input)
            {
                Varyings output = (Varyings)0;
                UNITY_SETUP_INSTANCE_ID(input);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(output);
                output.positionCS = TransformObjectToHClip(input.positionOS.xyz);
                output.uv = input.uv;
                return output;
            }

            // Signed distance (negative inside) to a rounded box of halfSize, its top edge shifted right by skew * height.
            float Card(float2 p, float2 halfSize, float skew, float radius)
            {
                p.x -= skew * p.y;
                float2 q = abs(p) - halfSize + radius;
                return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - radius;
            }

            float Hash(float2 p)
            {
                p = frac(p * float2(123.34, 456.21));
                p += dot(p, p + 45.32);
                return frac(p.x * p.y);
            }

            float Noise(float2 p)
            {
                float2 i = floor(p);
                float2 f = frac(p);
                f = f * f * (3.0 - 2.0 * f);
                float a = Hash(i);
                float b = Hash(i + float2(1.0, 0.0));
                float c = Hash(i + float2(0.0, 1.0));
                float d = Hash(i + float2(1.0, 1.0));
                return lerp(lerp(a, b, f.x), lerp(c, d, f.x), f.y);
            }

            float Fill(float d, float aa)
            {
                return saturate(0.5 - d / aa);
            }

            // A line of the given width centred on the contour d = -inset.
            float Line(float d, float inset, float width, float aa)
            {
                return saturate((0.5 * width - abs(d + inset)) / aa + 0.5);
            }

            // Premultiplied "over".
            void Over(inout float4 dst, float3 rgb, float a)
            {
                dst.rgb = rgb * a + dst.rgb * (1.0 - a);
                dst.a = a + dst.a * (1.0 - a);
            }

            float4 frag(Varyings input) : SV_Target
            {
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(input);

                float2 size = _Rect.xy;
                float2 halfSize = 0.5 * size;
                float skew = _Rect.z;
                float margin = max(_Rect.w, 1e-4);
                float rim = _Facet.x;
                float glow = _Facet.y;
                float age = _Facet.z;
                float drop = _Facet.w;
                float radius = min(_CornerCut, 0.5 * min(size.x, size.y));
                float shortSide = min(size.x, size.y);

                float2 quad = float2(size.x + abs(skew) * size.y, size.y) + 2.0 * margin;
                float2 p = (input.uv - 0.5) * quad;
                float d = Card(p, halfSize, skew, radius);
                float aa = max(fwidth(d), 1e-5);
                float4 c = 0;

                // Soft drop shadow below the card.
                if (drop > 0.0)
                {
                    float ds = Card(p + float2(0.0, drop), halfSize, skew, radius);
                    Over(c, _ShadowColor.rgb, _ShadowColor.a * (1.0 - smoothstep(-drop, drop, ds)));
                }

                // Soft glow outside the edge (hovered / selected).
                if (glow > 0.0)
                    Over(c, _OutlineColor.rgb, _OutlineColor.a * (1.0 - smoothstep(0.0, glow, d)));

                // Paper: lighter centre, darker mottled edges, fine grain. Noise runs in metres, so it doesn't stretch.
                float inside = Fill(d, aa);
                float2 n = p / max(halfSize, 1e-4);
                float blot = Noise(p * 40.0) * 0.65 + Noise(p * 115.0) * 0.35;
                float edge = 1.0 - smoothstep(0.0, max(0.18 * shortSide, 1e-4), -d);
                float4 body = lerp(_FillColor, _FacetLightColor, saturate(1.0 - dot(n, n) * 0.6) * 0.7 * age);
                body = lerp(body, _FacetDarkColor, saturate(edge * 0.8 + (blot - 0.5) * 0.45) * age);
                body.rgb *= 1.0 - 0.06 * age * (Noise(p * 300.0) - 0.5);
                Over(c, body.rgb, body.a * inside);

                if (rim > 0.0)
                {
                    // Bevelled gold border: dark outer edge, bright middle.
                    float t = saturate(-d / rim);
                    float3 gold = _RimColor.rgb * lerp(0.6, 1.15, sin(t * 3.14159));
                    Over(c, min(gold, 1.0), _RimColor.a * inside * Fill(-(d + rim), aa));

                    // Big cards: a thin inner gold line and a four-point star in each inner corner.
                    if (shortSide > 0.1)
                    {
                        Over(c, _RimColor.rgb * 0.85, _RimColor.a * Line(d, 2.6 * rim, 0.45 * rim, aa));
                        float2 q = abs(abs(p) - (halfSize - 5.5 * rim)) / (2.2 * rim);
                        float star = sqrt(q.x) + sqrt(q.y) - 1.0;
                        Over(c, _RimColor.rgb, _RimColor.a * saturate(0.5 - star / max(fwidth(star), 1e-4)));
                    }
                }

                return float4(min(c.rgb, 1.0), saturate(c.a));
            }
            ENDHLSL
        }
    }

    Fallback Off
}
