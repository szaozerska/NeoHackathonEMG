// Solid, opaque core of the sword: white-hot in the middle, tinted towards the silhouette. Writes alpha 1, so the
// blade fully covers passthrough.
Shader "SpellGame/Sword/BladeCore"
{
    Properties
    {
        _Color ("Edge Color", Color) = (0.3, 0.8, 1, 1)
        _CoreColor ("Core Color", Color) = (1, 1, 1, 1)
        _CorePower ("Core Falloff (lower is a wider white core)", Range(0.1, 4)) = 0.6
        _Flicker ("Flicker", Range(0, 0.3)) = 0.05
    }

    SubShader
    {
        Tags { "RenderPipeline" = "UniversalPipeline" "RenderType" = "Opaque" "Queue" = "Geometry" }

        Pass
        {
            Name "Unlit"
            Cull Back
            ZWrite On

            HLSLPROGRAM
            #pragma vertex SwordVert
            #pragma fragment Frag
            #pragma multi_compile_instancing

            #include "SwordCommon.hlsl"

            CBUFFER_START(UnityPerMaterial)
            half4 _Color;
            half4 _CoreColor;
            half _CorePower;
            half _Flicker;
            CBUFFER_END

            half4 Frag(Varyings input) : SV_Target
            {
                half core = pow(FacingRatio(input), _CorePower);
                half3 color = lerp(_Color.rgb, _CoreColor.rgb, core) * Flicker(_Flicker);
                return half4(color, 1.0h);
            }
            ENDHLSL
        }
    }
}
