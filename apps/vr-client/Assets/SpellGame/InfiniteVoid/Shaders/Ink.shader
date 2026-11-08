// The Infinite Void: slowly swirling black ink with faint violet veins, under a field of small twinkling stars.
// Drawn on a sphere around the caster; the pattern follows the direction from the sphere's centre, so it keeps the same
// angular size however large the sphere grows. _Color.a fades the whole layer (InfiniteVoidView); depth test per material.
Shader "SpellGame/InfiniteVoid/Ink"
{
    Properties
    {
        _Color ("Fade (alpha)", Color) = (1, 1, 1, 1)
        _DeepColor ("Deep Ink", Color) = (0.004, 0.002, 0.01, 1)
        _InkColor ("Ink Swirl", Color) = (0.05, 0.02, 0.09, 1)
        _VeinColor ("Vein", Color) = (0.25, 0.12, 0.45, 1)
        _InkScale ("Ink Scale", Range(0.5, 10)) = 3
        _InkSpeed ("Ink Speed", Range(0, 1)) = 0.08
        _StarDensity ("Star Density", Range(10, 300)) = 90
        _StarChance ("Star Chance", Range(0, 1)) = 0.25
        _StarSize ("Star Size", Range(0.01, 0.4)) = 0.12
        _StarBrightness ("Star Brightness", Range(0, 2)) = 1
        [Enum(UnityEngine.Rendering.CompareFunction)] _ZTest ("Depth Test", Float) = 4
    }

    SubShader
    {
        Tags { "RenderPipeline" = "UniversalPipeline" "RenderType" = "Transparent" "Queue" = "Transparent" "IgnoreProjector" = "True" }

        Pass
        {
            Name "Unlit"
            Blend SrcAlpha OneMinusSrcAlpha, One OneMinusSrcAlpha
            Cull Off
            ZWrite Off
            ZTest [_ZTest]

            HLSLPROGRAM
            #pragma vertex Vert
            #pragma fragment Frag
            #pragma multi_compile_instancing

            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            CBUFFER_START(UnityPerMaterial)
            half4 _Color;
            half4 _DeepColor;
            half4 _InkColor;
            half4 _VeinColor;
            float _InkScale;
            float _InkSpeed;
            float _StarDensity;
            float _StarChance;
            float _StarSize;
            half _StarBrightness;
            CBUFFER_END

            struct Attributes
            {
                float4 positionOS : POSITION;
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float3 direction : TEXCOORD0;
                UNITY_VERTEX_OUTPUT_STEREO
            };

            Varyings Vert(Attributes input)
            {
                Varyings output = (Varyings)0;
                UNITY_SETUP_INSTANCE_ID(input);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(output);
                output.positionCS = TransformObjectToHClip(input.positionOS.xyz);
                output.direction = input.positionOS.xyz;
                return output;
            }

            // Dave Hoskins' hash without sine (MIT): stable on mobile GPUs.
            float3 Hash33(float3 p)
            {
                p = frac(p * float3(0.1031, 0.1030, 0.0973));
                p += dot(p, p.yxz + 33.33);
                return frac((p.xxy + p.yxx) * p.zyx);
            }

            float Hash13(float3 p)
            {
                p = frac(p * 0.1031);
                p += dot(p, p.zyx + 31.32);
                return frac((p.x + p.y) * p.z);
            }

            float ValueNoise(float3 p)
            {
                float3 cell = floor(p);
                float3 f = frac(p);
                f = f * f * (3.0 - 2.0 * f);
                return lerp(
                    lerp(lerp(Hash13(cell), Hash13(cell + float3(1, 0, 0)), f.x),
                         lerp(Hash13(cell + float3(0, 1, 0)), Hash13(cell + float3(1, 1, 0)), f.x), f.y),
                    lerp(lerp(Hash13(cell + float3(0, 0, 1)), Hash13(cell + float3(1, 0, 1)), f.x),
                         lerp(Hash13(cell + float3(0, 1, 1)), Hash13(cell + float3(1, 1, 1)), f.x), f.y),
                    f.z);
            }

            float Fbm(float3 p)
            {
                return 0.5 * ValueNoise(p) + 0.3 * ValueNoise(p * 2.03 + 7.1) + 0.2 * ValueNoise(p * 4.01 + 13.7);
            }

            // One layer of stars: at most one per cell of a grid over directions, twinkling at its own rate.
            half Stars(float3 direction, float density, float salt)
            {
                float3 p = direction * density + salt;
                float3 cell = floor(p);
                float3 random = Hash33(cell);
                if (Hash13(cell + 17.0) > _StarChance)
                    return 0.0h;
                float distanceToStar = length(frac(p) - (0.2 + 0.6 * random));
                float glow = saturate(1.0 - distanceToStar / (_StarSize * (0.5 + random.x)));
                float twinkle = 0.65 + 0.35 * sin(_Time.y * (1.5 + 3.0 * random.y) + random.z * 6.2832);
                return (half)(glow * glow * twinkle);
            }

            half4 Frag(Varyings input) : SV_Target
            {
                float3 direction = normalize(input.direction);
                float t = _Time.y * _InkSpeed;
                float3 p = direction * _InkScale;
                float3 warp = float3(ValueNoise(p + t), ValueNoise(p + 5.2 - t), ValueNoise(p + 9.1 + t * 0.5));
                float ink = Fbm(p + 1.8 * warp + float3(0, t, 0));
                float vein = pow(1.0 - abs(2.0 * ink - 1.0), 10.0);

                half3 color = lerp(_DeepColor.rgb, _InkColor.rgb, (half)smoothstep(0.35, 0.8, ink));
                color += _VeinColor.rgb * (half)vein * 0.35h;
                half stars = Stars(direction, _StarDensity, 0.0) + 0.6h * Stars(direction, _StarDensity * 2.3, 41.0);
                color += stars * _StarBrightness;
                return half4(color, _Color.a);
            }
            ENDHLSL
        }
    }
}
