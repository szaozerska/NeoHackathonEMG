#ifndef SPELLGAME_SWORD_COMMON_INCLUDED
#define SPELLGAME_SWORD_COMMON_INCLUDED

// Shared vertex stage and helpers for the sword shaders. Structure follows Cyanilux's CC0 URP shader code templates
// (https://github.com/Cyanilux/URP_ShaderCodeTemplates), plus the stereo macros Quest's single-pass multiview needs.

#include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

struct Attributes
{
    float4 positionOS : POSITION;
    float3 normalOS : NORMAL;
    float2 uv : TEXCOORD0;
    half4 color : COLOR;
    UNITY_VERTEX_INPUT_INSTANCE_ID
};

struct Varyings
{
    float4 positionCS : SV_POSITION;
    float2 uv : TEXCOORD0;
    half4 color : COLOR;
    float3 normalWS : TEXCOORD1;
    float3 viewDirWS : TEXCOORD2;
    UNITY_VERTEX_OUTPUT_STEREO
};

Varyings SwordVert(Attributes input)
{
    Varyings output = (Varyings)0;
    UNITY_SETUP_INSTANCE_ID(input);
    UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(output);

    float3 positionWS = TransformObjectToWorld(input.positionOS.xyz);
    output.positionCS = TransformWorldToHClip(positionWS);
    output.uv = input.uv;
    output.color = input.color;
    output.normalWS = TransformObjectToWorldNormal(input.normalOS, false);
    output.viewDirWS = GetWorldSpaceViewDir(positionWS);
    return output;
}

// 1 where the surface faces the eye, 0 at the silhouette.
half FacingRatio(Varyings input)
{
    return (half)saturate(abs(dot(SafeNormalize(input.normalWS), SafeNormalize(input.viewDirWS))));
}

// A fast, uneven hum so the blade reads as energy rather than plastic.
half Flicker(half amount)
{
    return 1.0h + amount * (half)(sin(_Time.y * 61.0) * sin(_Time.y * 17.0));
}

// Passthrough is composited under the eye buffer using its alpha, so additive glow that left alpha at 0 would vanish.
// Glow therefore writes alpha = its brightness; with "Blend One One, One OneMinusSrcAlpha" alpha accumulates like
// premultiplied "over", so overlapping glow never lowers alpha and never punches holes in opaque content.
half4 GlowOutput(half3 color, half alphaScale)
{
    return half4(color, saturate(max(color.r, max(color.g, color.b)) * alphaScale));
}

#endif
