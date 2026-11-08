// Unlit particle/trail shader for the fireball: alpha-mask texture x vertex color x tint, colour premultiplied by the mask.
// Colour and alpha blend separately so every effect writes coverage into the eye buffer's alpha, which is what the
// passthrough compositor uses (see README.md):
//   glow/flames: Blend One One, One OneMinusSrcAlpha  (additive colour, "over" alpha scaled by _AlphaWrite)
//   smoke:       Blend One OneMinusSrcAlpha, One OneMinusSrcAlpha  (premultiplied alpha)
Shader "SpellGame/Fireball/Particle"
{
    Properties
    {
        _MainTex("Mask (alpha)", 2D) = "white" {}
        _Color("Tint", Color) = (1, 1, 1, 1)
        _Intensity("Intensity", Range(0, 4)) = 1
        _AlphaWrite("Passthrough Coverage", Range(0, 1)) = 0.6
        [Enum(UnityEngine.Rendering.BlendMode)] _SrcBlend("Src Blend", Float) = 1
        [Enum(UnityEngine.Rendering.BlendMode)] _DstBlend("Dst Blend", Float) = 1
        [Enum(UnityEngine.Rendering.BlendMode)] _SrcBlendAlpha("Src Blend Alpha", Float) = 1
        [Enum(UnityEngine.Rendering.BlendMode)] _DstBlendAlpha("Dst Blend Alpha", Float) = 10
    }

    SubShader
    {
        Tags
        {
            "RenderType" = "Transparent"
            "Queue" = "Transparent"
            "RenderPipeline" = "UniversalPipeline"
            "IgnoreProjector" = "True"
            "PreviewType" = "Plane"
        }

        Pass
        {
            Name "FireballParticle"
            Tags { "LightMode" = "UniversalForward" }
            Blend [_SrcBlend] [_DstBlend], [_SrcBlendAlpha] [_DstBlendAlpha]
            ZWrite Off
            Cull Off

            HLSLPROGRAM
            #pragma vertex Vert
            #pragma fragment Frag
            #pragma multi_compile_instancing

            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            TEXTURE2D(_MainTex);
            SAMPLER(sampler_MainTex);

            CBUFFER_START(UnityPerMaterial)
                float4 _MainTex_ST;
                half4 _Color;
                half _Intensity;
                half _AlphaWrite;
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

            Varyings Vert(Attributes input)
            {
                Varyings output = (Varyings)0;
                UNITY_SETUP_INSTANCE_ID(input);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(output);

                output.positionCS = TransformObjectToHClip(input.positionOS.xyz);
                output.color = input.color;
                output.uv = TRANSFORM_TEX(input.uv, _MainTex);
                return output;
            }

            half4 Frag(Varyings input) : SV_Target
            {
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(input);

                half mask = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, input.uv).a * input.color.a * _Color.a;
                half3 color = input.color.rgb * _Color.rgb * (_Intensity * mask);
                return half4(color, saturate(mask * _AlphaWrite));
            }
            ENDHLSL
        }
    }

    Fallback Off
}
