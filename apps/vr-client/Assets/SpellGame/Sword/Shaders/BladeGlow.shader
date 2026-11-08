// Soft additive halo around the core: brightest where it faces the eye, fading to nothing at the silhouette, so a wider
// capsule reads as a glow without post-processing bloom (HDR and bloom are off on Quest).
Shader "SpellGame/Sword/BladeGlow"
{
    Properties
    {
        _Color ("Glow Color", Color) = (0.3, 0.8, 1, 1)
        _Intensity ("Intensity", Range(0, 4)) = 1.4
        _Falloff ("Falloff (higher is a tighter glow)", Range(0.5, 8)) = 2.5
        _AlphaScale ("Passthrough Alpha Scale", Range(0, 2)) = 1
        _Flicker ("Flicker", Range(0, 0.3)) = 0.08
    }

    SubShader
    {
        Tags { "RenderPipeline" = "UniversalPipeline" "RenderType" = "Transparent" "Queue" = "Transparent" "IgnoreProjector" = "True" }

        Pass
        {
            Name "Unlit"
            Blend One One, One OneMinusSrcAlpha
            Cull Back
            ZWrite Off

            HLSLPROGRAM
            #pragma vertex SwordVert
            #pragma fragment Frag
            #pragma multi_compile_instancing

            #include "SwordCommon.hlsl"

            CBUFFER_START(UnityPerMaterial)
            half4 _Color;
            half _Intensity;
            half _Falloff;
            half _AlphaScale;
            half _Flicker;
            CBUFFER_END

            half4 Frag(Varyings input) : SV_Target
            {
                half glow = pow(FacingRatio(input), _Falloff) * _Intensity * Flicker(_Flicker);
                return GlowOutput(_Color.rgb * glow, _AlphaScale);
            }
            ENDHLSL
        }
    }
}
