// Crystal UI panel on a plain quad: a translucent ice-tinted slab with cut (chamfered) corners, a bright rim, a faceted
// bevel just inside the rim, a slow diagonal highlight streak, a soft outer glow and an optional accent strip along the
// top edge. Sizes are in metres; UiStyle scales the quad to the rect plus the glow margin on every side and passes the
// rect in _Rect, so the cut corners keep their size whatever the panel's shape.
// Passthrough: premultiplied-alpha "over" blending. The slab writes its (partial) coverage into alpha, so the room
// shows through dimmed and tinted rather than at full strength or not at all; the glow fades to alpha 0 at the quad edge.
Shader "SpellGame/UI/CrystalPanel"
{
    Properties
    {
        _FillColor ("Crystal Tint (alpha = opacity)", Color) = (0.1, 0.26, 0.4, 0.5)
        _RimColor ("Rim (alpha = opacity)", Color) = (0.88, 0.97, 1, 1)
        _GlowColor ("Outer Glow (alpha = strength)", Color) = (0.55, 0.88, 1, 0.45)
        _StripColor ("Top Strip (alpha = opacity, 0 = off)", Color) = (0.55, 0.88, 1, 0)
        _Rect ("Rect: width, height, corner cut, glow margin (m)", Vector) = (0.6, 0.4, 0.02, 0.03)
        _Facet ("Rim width, bevel width (m), highlight strength, strip height (m)", Vector) = (0.0022, 0.012, 0.25, 0.004)
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
            Name "Crystal"
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
                float4 _GlowColor;
                float4 _StripColor;
                float4 _Rect;
                float4 _Facet;
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

            // Signed distance (negative inside) to a box centred on the origin with its corners cut off at 45°.
            float CutBox(float2 p, float2 halfSize, float cut)
            {
                p = abs(p);
                float2 q = p - halfSize;
                float box = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0);
                float corner = (p.x + p.y - (halfSize.x + halfSize.y - cut)) * 0.70710678;
                return max(box, corner);
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
                float cut = min(_Rect.z, 0.5 * min(size.x, size.y));
                float margin = max(_Rect.w, 1e-4);
                float rim = _Facet.x;
                float bevel = max(_Facet.y, 1e-4);

                float2 p = (input.uv - 0.5) * (size + 2.0 * margin);
                float d = CutBox(p, halfSize, cut);
                float aa = max(fwidth(d), 1e-5);
                float inside = saturate(0.5 - d / aa);

                // Outer glow, outside the slab only.
                float glow = pow(saturate(1.0 - d / margin), 2.2) * (1.0 - inside) * _GlowColor.a;
                float4 c = float4(_GlowColor.rgb * glow, glow);

                // Crystal slab: thicker (brighter, more opaque) in the bevel band along the rim, with the bevel facets lit
                // from the top left so the cut reads as 3D.
                float band = smoothstep(-bevel, 0.0, d);
                float2 n = normalize(p / max(halfSize, 1e-4) + 1e-5);
                float lit = 0.5 + 0.5 * dot(n, float2(-0.6, 0.8));
                float3 slab = lerp(_FillColor.rgb, _RimColor.rgb, band * (0.25 + 0.35 * lit));
                slab *= 1.0 + 0.25 * saturate(p.y / max(halfSize.y, 1e-4));
                float slabAlpha = lerp(_FillColor.a, saturate(_FillColor.a + 0.3), band);
                Over(c, slab, slabAlpha * inside);

                // Facet line where the bevel meets the flat face.
                float facet = saturate(1.0 - abs(d + bevel) / aa) * 0.35 * _RimColor.a;
                Over(c, _RimColor.rgb, facet * inside);

                // Highlight streak sweeping slowly across the face, diagonally.
                float s = (p.x + 0.6 * p.y) / max(size.x, 1e-4);
                float sweep = frac(_Time.y * 0.07) * 2.6 - 1.3;
                float streak = (exp(-pow((s - sweep) / 0.05, 2.0)) + 0.5 * exp(-pow((s - sweep + 0.09) / 0.018, 2.0)));
                streak *= _Facet.z * inside * (1.0 - band);
                c.rgb += _RimColor.rgb * streak;
                c.a = saturate(c.a + 0.4 * streak);

                // Bright rim.
                float rimMask = saturate((0.5 * rim - abs(d + 0.5 * rim)) / aa + 0.5);
                Over(c, _RimColor.rgb, _RimColor.a * rimMask);

                // Accent strip along the top edge, between the cut corners.
                float stripHeight = max(_Facet.w, 1e-4);
                float2 stripHalf = float2(max(halfSize.x - cut - rim, 1e-4), 0.5 * stripHeight);
                float2 stripCentre = float2(0.0, halfSize.y - rim - stripHalf.y - 0.5 * rim);
                float ds = CutBox(p - stripCentre, stripHalf, stripHalf.y);
                float strip = saturate(0.5 - ds / aa) * _StripColor.a;
                c.rgb += _StripColor.rgb * exp(-max(ds, 0.0) / (2.0 * stripHeight)) * inside * _StripColor.a * 0.35;
                Over(c, _StripColor.rgb, strip);

                return float4(min(c.rgb, 1.0), saturate(c.a));
            }
            ENDHLSL
        }
    }

    Fallback Off
}
