// Additive particle for sword sparks and flashes: a procedural soft dot (no texture) with a white-hot centre, tinted by
// the particle colour. On stretched billboards it becomes a streak.
Shader "SpellGame/Sword/Spark"
{
    Properties
    {
        _Color ("Tint", Color) = (1, 1, 1, 1)
        _CoreColor ("Hot Centre Color", Color) = (1, 1, 1, 1)
        _Intensity ("Intensity", Range(0, 4)) = 1.5
        _AlphaScale ("Passthrough Alpha Scale", Range(0, 2)) = 1
    }

    SubShader
    {
        Tags { "RenderPipeline" = "UniversalPipeline" "RenderType" = "Transparent" "Queue" = "Transparent" "IgnoreProjector" = "True" "PreviewType" = "Plane" }

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
            half _AlphaScale;
            CBUFFER_END

            half4 Frag(Varyings input) : SV_Target
            {
                float2 fromCentre = input.uv * 2.0 - 1.0;
                half dot01 = (half)saturate(1.0 - dot(fromCentre, fromCentre));
                half glow = dot01 * dot01;
                half hot = glow * glow;
                half3 color = (_Color.rgb * input.color.rgb * glow + _CoreColor.rgb * hot) * input.color.a * _Intensity;
                return GlowOutput(color, _AlphaScale);
            }
            ENDHLSL
        }
    }
}
