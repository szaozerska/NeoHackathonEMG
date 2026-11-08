// Opal crystal card on a plain quad (Smash Ultimate style): a milky, half-transparent white parallelogram slanted by
// _Rect.z (tan of the skew), cut by two flat facet planes (a lighter one top right, a pastel-shimmer one bottom left),
// with a bright white rim, an optional dark-ink outline outside the rim and an optional hard drop shadow below.
// No textures, no blur, one pass. Sizes are in metres; UiStyle scales the quad to the card plus the slant and margin
// and passes them in _Rect / _Facet.
// Passthrough: premultiplied-alpha "over" blending. The body writes its partial coverage into alpha, so the room shows
// through dimmed and milky rather than at full strength or not at all; outside the card alpha falls to 0.
Shader "SpellGame/UI/CrystalPanel"
{
    Properties
    {
        _FillColor ("Body (alpha = opacity)", Color) = (0.97, 0.97, 1, 0.7)
        _RimColor ("Rim (alpha = opacity)", Color) = (1, 1, 1, 1)
        _OutlineColor ("Outer Outline (alpha = opacity)", Color) = (0.165, 0.184, 0.271, 0)
        _ShimmerColor ("Lower Facet Shimmer (alpha = strength)", Color) = (0.86, 0.8, 1, 0.5)
        _ShadowColor ("Drop Shadow (alpha = opacity)", Color) = (0.165, 0.184, 0.271, 0.35)
        _Rect ("Rect: width, height, skew (tan), margin (m)", Vector) = (0.6, 0.2, 0.2126, 0.015)
        _Facet ("Rim width, outline width, facet strength, shadow drop (m)", Vector) = (0.003, 0, 1, 0.006)
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
                float4 _OutlineColor;
                float4 _ShimmerColor;
                float4 _ShadowColor;
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

            // Signed distance (negative inside) to a parallelogram centred on the origin: a box of halfSize whose top edge
            // is shifted right by skew * height. Exact along the edges that matter here.
            float Slanted(float2 p, float2 halfSize, float skew)
            {
                float c = rsqrt(1.0 + skew * skew);
                float2 q = abs(float2((p.x - skew * p.y) * c, p.y)) - float2(halfSize.x * c, halfSize.y);
                return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0);
            }

            float Fill(float d, float aa)
            {
                return saturate(0.5 - d / aa);
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
                float outline = _Facet.y;
                float facet = _Facet.z;
                float drop = _Facet.w;

                float2 quad = float2(size.x + abs(skew) * size.y, size.y) + 2.0 * margin;
                float2 p = (input.uv - 0.5) * quad;
                float d = Slanted(p, halfSize, skew);
                float aa = max(fwidth(d), 1e-5);
                float4 c = 0;

                // Hard drop shadow: the same card moved down, visible only below it.
                if (drop > 0.0)
                    Over(c, _ShadowColor.rgb, _ShadowColor.a * Fill(Slanted(p + float2(0.0, drop), halfSize, skew), aa));

                // Ink outline around the rim (selected cards).
                if (outline > 0.0)
                    Over(c, _OutlineColor.rgb, _OutlineColor.a * Fill(d - outline, aa));

                // Body: two flat facet planes on the milky base, split along diagonals (in metres, so they stay crisp).
                float inside = Fill(d, aa);
                float2 n = p / max(halfSize, 1e-4);
                float upper = Fill(-(n.y + 0.55 * n.x - 0.3) * halfSize.y, aa);
                float lower = Fill((n.y + 0.9 * n.x + 0.35) * halfSize.y, aa);
                float3 body = _FillColor.rgb;
                float alpha = _FillColor.a;
                body = lerp(body, 1.0, upper * 0.5 * facet);
                alpha = lerp(alpha, saturate(alpha + 0.12), upper * facet);
                body = lerp(body, _ShimmerColor.rgb, lower * _ShimmerColor.a * facet);
                alpha = lerp(alpha, saturate(alpha + 0.06), lower * facet);
                body *= 0.95 + 0.05 * saturate(0.5 + 0.5 * n.y);
                Over(c, body, alpha * inside);

                // Bright rim just inside the edge.
                if (rim > 0.0)
                    Over(c, _RimColor.rgb, _RimColor.a * saturate((0.5 * rim - abs(d + 0.5 * rim)) / aa + 0.5));

                return float4(min(c.rgb, 1.0), saturate(c.a));
            }
            ENDHLSL
        }
    }

    Fallback Off
}
