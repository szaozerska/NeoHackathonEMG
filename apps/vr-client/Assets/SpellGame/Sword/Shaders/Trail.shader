// Swept swing trail. The mesh is built by SwordView: uv.x = age (0 new .. 1 old), uv.y = 0 at the inner edge .. 1 at
// the blade tip, vertex alpha = swing strength. Bright white edge along the tip path, soft towards the hilt, fading with age.
Shader "SpellGame/Sword/Trail"
{
    Properties
    {
        _Color ("Trail Color", Color) = (0.3, 0.8, 1, 1)
        _CoreColor ("Tip Edge Color", Color) = (1, 1, 1, 1)
        _Intensity ("Intensity", Range(0, 4)) = 1.3
        _AgePower ("Age Falloff", Range(0.5, 4)) = 1.5
        _InnerSoftness ("Inner Edge Softness", Range(0.01, 1)) = 0.7
        _EdgeSharpness ("Tip Edge Sharpness", Range(1, 32)) = 8
        _AlphaScale ("Passthrough Alpha Scale", Range(0, 2)) = 1
    }

    SubShader
    {
        Tags { "RenderPipeline" = "UniversalPipeline" "RenderType" = "Transparent" "Queue" = "Transparent" "IgnoreProjector" = "True" }

        Pass
        {
            Name "Unlit"
            Blend One One, One OneMinusSrcAlpha
            Cull Off
            ZWrite Off

            HLSLPROGRAM
            #pragma vertex SwordVert
            #pragma fragment Frag
            #pragma multi_compile_instancing

            #include "SwordCommon.hlsl"

            CBUFFER_START(UnityPerMaterial)
            half4 _Color;
            half4 _CoreColor;
            half _Intensity;
            half _AgePower;
            half _InnerSoftness;
            half _EdgeSharpness;
            half _AlphaScale;
            CBUFFER_END

            half4 Frag(Varyings input) : SV_Target
            {
                half age = (half)saturate(input.uv.x);
                half across = (half)saturate(input.uv.y);
                half fade = pow(1.0h - age, _AgePower) * input.color.a;
                half body = smoothstep(0.0h, _InnerSoftness, across);
                half edge = pow(across, _EdgeSharpness) * (1.0h - age);
                half3 color = (_Color.rgb * input.color.rgb * body + _CoreColor.rgb * edge) * fade * _Intensity;
                return GlowOutput(color, _AlphaScale);
            }
            ENDHLSL
        }
    }
}
