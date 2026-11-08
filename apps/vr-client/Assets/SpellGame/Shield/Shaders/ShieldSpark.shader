// Soft glowing particle for shield sparks and shock rings (Shuriken ParticleSystem; uses vertex colour and UV0).
// _Ring = 0: soft round dot (stretched billboards turn it into a streak). _Ring = 1: thin soft ring.
// Premultiplied-alpha blending like ForceFieldShield, with alpha raised by brightness so the particles show in
// passthrough instead of vanishing where the eye buffer alpha would otherwise stay 0.
Shader "SpellGame/Shield/Spark"
{
    Properties
    {
        _Intensity ("Intensity", Range(0, 4)) = 1.5
        _GlowAlpha ("Alpha From Glow", Range(0, 1)) = 0.7
        _Ring ("Ring (0 dot, 1 ring)", Range(0, 1)) = 0
        _RingWidth ("Ring Width", Range(0.02, 0.5)) = 0.12
    }

    SubShader
    {
        Tags
        {
            "RenderPipeline" = "UniversalPipeline"
            "RenderType" = "Transparent"
            "Queue" = "Transparent+10"
            "IgnoreProjector" = "True"
            "PreviewType" = "Plane"
        }

        Pass
        {
            Name "Spark"
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
                half _Intensity;
                half _GlowAlpha;
                half _Ring;
                half _RingWidth;
            CBUFFER_END

            struct Attributes
            {
                float4 positionOS : POSITION;
                half4 color : COLOR;
                float2 uv : TEXCOORD0;
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                half4 color : COLOR;
                float2 uv : TEXCOORD0;
                UNITY_VERTEX_OUTPUT_STEREO
            };

            Varyings vert(Attributes input)
            {
                Varyings output = (Varyings)0;
                UNITY_SETUP_INSTANCE_ID(input);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(output);
                output.positionCS = TransformObjectToHClip(input.positionOS.xyz);
                output.color = input.color;
                output.uv = input.uv;
                return output;
            }

            half4 frag(Varyings input) : SV_Target
            {
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(input);

                float d = length(input.uv * 2.0 - 1.0); // 0 centre, 1 quad edge
                float dot01 = saturate(1.0 - d);
                float dotMask = dot01 * dot01 * (1.0 + 2.0 * smoothstep(0.6, 1.0, dot01)); // soft halo + hot core
                float ringD = (d - (1.0 - _RingWidth)) / _RingWidth;
                float ringMask = exp(-ringD * ringD * 2.5) * (1.0 - smoothstep(0.98, 1.0, d));
                float mask = lerp(dotMask, ringMask, _Ring);

                half3 color = input.color.rgb * (mask * _Intensity * input.color.a);
                half alpha = saturate(mask * input.color.a);
                alpha = max(alpha * 0.6, saturate(dot(color, half3(0.2126, 0.7152, 0.0722))) * _GlowAlpha);
                return half4(min(color, 1.0), alpha);
            }
            ENDHLSL
        }
    }

    Fallback Off
}
