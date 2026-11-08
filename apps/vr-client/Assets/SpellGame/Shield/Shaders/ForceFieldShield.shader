// Energy force-field shield for the SpellGame shield disc (see ../README.md for sources and licences).
// Procedural only (no textures): hex grid, fresnel rim, edge ring, radial energy pulse, up to 4 hit ripples,
// radial spawn reveal and a boost tint. Drawn on a unit spherical cap: rim radius 0.5 on the object-space
// y = 0 plane, bulging towards +y.
//
// Passthrough: premultiplied-alpha "over" blending (Blend One OneMinusSrcAlpha) for colour and alpha, so the
// eye buffer's alpha is real coverage (the compositor shows passthrough where alpha < 1) and glow brighter than
// its coverage still adds light. Glow also raises alpha (_GlowAlpha) so bright lines dim the passthrough behind
// them and stay visible in bright rooms.
Shader "SpellGame/Shield/ForceField"
{
    Properties
    {
        [Header(Colors)]
        _Color ("Base Color", Color) = (0.25, 0.7, 1, 1)
        _RimColor ("Rim Color", Color) = (0.75, 0.95, 1, 1)
        _BoostColor ("Boost Color", Color) = (1, 0.88, 0.45, 1)
        _HitColor ("Hit Color", Color) = (1, 1, 1, 1)

        [Header(Coverage)]
        _Opacity ("Opacity", Range(0, 1)) = 1
        _FillAlpha ("Fill Alpha", Range(0, 1)) = 0.18
        _GlowAlpha ("Alpha From Glow", Range(0, 1)) = 0.6
        _BackFace ("Back Face Strength", Range(0, 1)) = 0.6

        [Header(Fresnel Rim)]
        _FresnelBias ("Fresnel Bias", Float) = 0.05
        _FresnelScale ("Fresnel Scale", Float) = 1.4
        _FresnelPower ("Fresnel Power", Range(0.5, 8)) = 2.5
        _EdgeWidth ("Edge Ring Width", Range(0.005, 0.2)) = 0.04

        [Header(Hex Grid)]
        _HexScale ("Hex Cells Across", Float) = 9
        _HexWidth ("Hex Line Width", Range(0.005, 0.25)) = 0.06
        _HexIntensity ("Hex Intensity", Range(0, 2)) = 0.9

        [Header(Energy)]
        _PulseSpeed ("Pulse Speed", Float) = 0.6
        _NoiseScale ("Noise Scale", Float) = 6
        _NoiseSpeed ("Noise Speed", Float) = 0.35

        [Header(Hit Ripples)]
        _RippleSpeed ("Ripple Speed (radii per s)", Float) = 2.4
        _RippleWidth ("Ripple Width", Range(0.01, 0.3)) = 0.06
        _RippleDuration ("Ripple Duration (s)", Float) = 0.55

        [Header(Driven per renderer)]
        _Boost ("Boost", Range(0, 1)) = 0
        _Spawn ("Spawn", Range(0, 1)) = 1
    }

    SubShader
    {
        Tags
        {
            "RenderPipeline" = "UniversalPipeline"
            "RenderType" = "Transparent"
            "Queue" = "Transparent"
            "IgnoreProjector" = "True"
        }

        Pass
        {
            Name "ForceField"
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

            #define MAX_HITS 4

            CBUFFER_START(UnityPerMaterial)
                half4 _Color;
                half4 _RimColor;
                half4 _BoostColor;
                half4 _HitColor;
                half _Opacity;
                half _FillAlpha;
                half _GlowAlpha;
                half _BackFace;
                float _FresnelBias;
                float _FresnelScale;
                float _FresnelPower;
                float _EdgeWidth;
                float _HexScale;
                float _HexWidth;
                half _HexIntensity;
                float _PulseSpeed;
                float _NoiseScale;
                float _NoiseSpeed;
                float _RippleSpeed;
                float _RippleWidth;
                float _RippleDuration;
                half _Boost;
                half _Spawn;
            CBUFFER_END

            // Set per renderer from a MaterialPropertyBlock: xyz = hit point in object space, w = _Time.y at the hit.
            float4 _HitPoints[MAX_HITS];

            struct Attributes
            {
                float4 positionOS : POSITION;
                float3 normalOS : NORMAL;
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float3 positionOS : TEXCOORD0;
                float3 positionWS : TEXCOORD1;
                float3 normalWS : TEXCOORD2;
                UNITY_VERTEX_OUTPUT_STEREO
            };

            float Hash21(float2 p)
            {
                p = frac(p * float2(123.34, 456.21));
                p += dot(p, p + 45.32);
                return frac(p.x * p.y);
            }

            float ValueNoise(float2 p)
            {
                float2 i = floor(p);
                float2 f = frac(p);
                float2 u = f * f * (3.0 - 2.0 * f);
                float a = Hash21(i);
                float b = Hash21(i + float2(1, 0));
                float c = Hash21(i + float2(0, 1));
                float d = Hash21(i + float2(1, 1));
                return lerp(lerp(a, b, u.x), lerp(c, d, u.x), u.y);
            }

            // Hex grid after K0chiko/EnergyShieldShader (MIT), with a floor-based modulo so negative
            // coordinates tile correctly. Returns distance to the cell centre (0 centre, 0.5 edge) and the cell id.
            float HexDist(float2 p)
            {
                p = abs(p);
                return max(dot(p, float2(0.5, 0.8660254)), p.x);
            }

            float2 PositiveMod(float2 x, float2 m)
            {
                return x - m * floor(x / m);
            }

            float HexCell(float2 uv, out float2 cellId)
            {
                const float2 r = float2(1.0, 1.7320508);
                const float2 h = r * 0.5;
                float2 a = PositiveMod(uv, r) - h;
                float2 b = PositiveMod(uv - h, r) - h;
                float2 g = dot(a, a) < dot(b, b) ? a : b;
                cellId = uv - g;
                return HexDist(g);
            }

            Varyings vert(Attributes input)
            {
                Varyings output = (Varyings)0;
                UNITY_SETUP_INSTANCE_ID(input);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(output);

                VertexPositionInputs positions = GetVertexPositionInputs(input.positionOS.xyz);
                output.positionCS = positions.positionCS;
                output.positionWS = positions.positionWS;
                output.positionOS = input.positionOS.xyz;
                output.normalWS = TransformObjectToWorldNormal(input.normalOS);
                return output;
            }

            half4 frag(Varyings input, FRONT_FACE_TYPE cullFace : FRONT_FACE_SEMANTIC) : SV_Target
            {
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(input);

                bool front = IS_FRONT_VFACE(cullFace, true, false);
                float t = _Time.y;
                float2 p = input.positionOS.xz;
                float r = length(p) * 2.0; // 0 centre, 1 rim

                // Fresnel rim (bias + scale * (1 - N.V)^power, after AdultLink/HoloShield, MIT).
                float3 normalWS = normalize(input.normalWS) * (front ? 1.0 : -1.0);
                float3 viewWS = GetWorldSpaceNormalizeViewDir(input.positionWS);
                float nDotV = saturate(dot(normalWS, viewWS));
                float fresnel = saturate(_FresnelBias + _FresnelScale * pow(1.0 - nDotV, _FresnelPower));

                // Bright ring along the disc edge, so the outline reads face-on too.
                float rAA = fwidth(r);
                float edge = 1.0 - smoothstep(0.0, _EdgeWidth + rAA, abs(r - (1.0 - _EdgeWidth)));
                float rimGlow = pow(saturate(r), 5.0);

                // Hex lines, anti-aliased with fwidth so they don't shimmer at a distance in VR.
                float2 cellId;
                float hexD = HexCell(p * _HexScale, cellId);
                float hexAA = fwidth(hexD);
                float hexLine = smoothstep(0.5 - _HexWidth - hexAA, 0.5 - _HexWidth + hexAA, hexD);

                float pulseSpeed = _PulseSpeed * (1.0 + 2.0 * _Boost);
                float cellFlicker = 0.55 + 0.45 * sin(t * (2.0 + 4.0 * _Boost) + Hash21(cellId) * 6.2831853);
                float band = frac(r - t * pulseSpeed);
                float pulse = smoothstep(0.0, 0.15, band) * (1.0 - smoothstep(0.15, 0.35, band));
                float noise = ValueNoise(p * _NoiseScale + float2(t * _NoiseSpeed, -t * _NoiseSpeed * 0.7));

                // Hit ripples: an expanding ring plus a flash at the hit point.
                float ripple = 0.0;
                [unroll]
                for (int i = 0; i < MAX_HITS; i++)
                {
                    float age = t - _HitPoints[i].w;
                    if (age >= 0.0 && age < _RippleDuration)
                    {
                        float fade = 1.0 - age / _RippleDuration;
                        float d = distance(p, _HitPoints[i].xz) * 2.0;
                        float ring = (d - age * _RippleSpeed) / _RippleWidth;
                        ripple += exp(-ring * ring) * fade;
                        ripple += exp(-d * d * 40.0) * fade * fade * 1.5;
                    }
                }
                ripple = saturate(ripple);

                // Spawn: reveal outward from the centre with a bright leading edge.
                float front01 = _Spawn * 1.1;
                float spawnMask = 1.0 - smoothstep(front01 - 0.1, front01, r);
                float spawnEdge = (1.0 - smoothstep(0.0, 0.08, abs(r - front01 + 0.05))) * (1.0 - _Spawn);

                half3 baseColor = lerp(_Color.rgb, _BoostColor.rgb, _Boost * 0.7);
                half3 rimColor = lerp(_RimColor.rgb, _BoostColor.rgb, _Boost * 0.5);
                half intensity = 1.0 + 0.8 * _Boost;

                half fill = _FillAlpha * (0.7 + 0.6 * noise);
                half hex = hexLine * _HexIntensity * cellFlicker * (0.35 + 0.65 * saturate(r + pulse));
                half rim = saturate(fresnel + edge + rimGlow * 0.5);

                half3 color = baseColor * (fill * 1.5 + hex + pulse * 0.35)
                            + rimColor * rim
                            + _HitColor.rgb * (ripple + spawnEdge);
                color *= intensity;

                half alpha = saturate(fill + hex * 0.45 + rim * 0.75 + pulse * 0.1 + ripple * 0.8 + spawnEdge);
                alpha = max(alpha, saturate(dot(color, half3(0.2126, 0.7152, 0.0722))) * _GlowAlpha);

                half visible = spawnMask * _Opacity * (front ? 1.0 : _BackFace);
                return half4(min(color, 1.0) * visible, alpha * visible);
            }
            ENDHLSL
        }
    }

    Fallback Off
}
