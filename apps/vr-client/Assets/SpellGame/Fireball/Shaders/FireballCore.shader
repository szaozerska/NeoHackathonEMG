// Opaque, unlit, procedurally animated fire surface for the fireball's solid core.
// Opaque on purpose: it writes alpha = 1, so the core always fully covers passthrough (see README.md).
Shader "SpellGame/Fireball/Core"
{
    Properties
    {
        _HotColor("Hot Color", Color) = (1, 0.96, 0.78, 1)
        _MidColor("Mid Color", Color) = (1, 0.55, 0.08, 1)
        _EdgeColor("Edge Color", Color) = (0.8, 0.12, 0.02, 1)
        _NoiseScale("Noise Scale", Float) = 4
        _FlowSpeed("Flow Speed", Float) = 1.8
        _Turbulence("Turbulence", Range(0, 2)) = 1
        _RimPower("Rim Power", Range(0.25, 8)) = 1.2
    }

    SubShader
    {
        Tags { "RenderType" = "Opaque" "Queue" = "Geometry" "RenderPipeline" = "UniversalPipeline" }

        Pass
        {
            Name "FireballCore"
            Tags { "LightMode" = "UniversalForward" }
            ZWrite On
            Cull Back

            HLSLPROGRAM
            #pragma vertex Vert
            #pragma fragment Frag
            #pragma multi_compile_instancing

            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            CBUFFER_START(UnityPerMaterial)
                half4 _HotColor;
                half4 _MidColor;
                half4 _EdgeColor;
                float _NoiseScale;
                float _FlowSpeed;
                half _Turbulence;
                half _RimPower;
            CBUFFER_END

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
                float3 normalWS : TEXCOORD1;
                float3 viewDirWS : TEXCOORD2;
                UNITY_VERTEX_OUTPUT_STEREO
            };

            float Hash31(float3 p)
            {
                p = frac(p * 0.1031);
                p += dot(p, p.zyx + 31.32);
                return frac((p.x + p.y) * p.z);
            }

            float ValueNoise(float3 p)
            {
                float3 i = floor(p);
                float3 f = frac(p);
                f = f * f * (3.0 - 2.0 * f);
                float n000 = Hash31(i);
                float n100 = Hash31(i + float3(1, 0, 0));
                float n010 = Hash31(i + float3(0, 1, 0));
                float n110 = Hash31(i + float3(1, 1, 0));
                float n001 = Hash31(i + float3(0, 0, 1));
                float n101 = Hash31(i + float3(1, 0, 1));
                float n011 = Hash31(i + float3(0, 1, 1));
                float n111 = Hash31(i + float3(1, 1, 1));
                float nx00 = lerp(n000, n100, f.x);
                float nx10 = lerp(n010, n110, f.x);
                float nx01 = lerp(n001, n101, f.x);
                float nx11 = lerp(n011, n111, f.x);
                return lerp(lerp(nx00, nx10, f.y), lerp(nx01, nx11, f.y), f.z);
            }

            Varyings Vert(Attributes input)
            {
                Varyings output = (Varyings)0;
                UNITY_SETUP_INSTANCE_ID(input);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(output);

                VertexPositionInputs position = GetVertexPositionInputs(input.positionOS.xyz);
                output.positionCS = position.positionCS;
                output.positionOS = input.positionOS.xyz;
                output.normalWS = TransformObjectToWorldNormal(input.normalOS);
                output.viewDirWS = GetWorldSpaceViewDir(position.positionWS);
                return output;
            }

            half4 Frag(Varyings input) : SV_Target
            {
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(input);

                float facing = saturate(dot(normalize(input.normalWS), normalize(input.viewDirWS)));
                float t = _Time.y * _FlowSpeed;
                float3 p = input.positionOS * _NoiseScale;
                // Two octaves flowing upward at different speeds read as boiling flame.
                float noise = ValueNoise(p + float3(0.0, -t, 0.0)) * 0.65
                            + ValueNoise(p * 2.3 + float3(t * 0.4, -t * 1.7, 5.2)) * 0.35;

                half heat = saturate(pow(facing, _RimPower) + (noise - 0.5) * _Turbulence);
                half3 color = heat < 0.5
                    ? lerp(_EdgeColor.rgb, _MidColor.rgb, heat * 2.0)
                    : lerp(_MidColor.rgb, _HotColor.rgb, heat * 2.0 - 1.0);
                return half4(color, 1.0);
            }
            ENDHLSL
        }
    }

    Fallback Off
}
