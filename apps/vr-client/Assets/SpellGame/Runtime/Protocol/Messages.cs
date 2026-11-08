using System.Collections.Generic;
using Newtonsoft.Json;
using UnityEngine;

namespace SpellGame.Protocol
{
    /// <summary>Wire messages from architecture.md §4.2 and §6. Property names are snake_cased by <see cref="MessageCodec"/>.</summary>
    public abstract class Message
    {
        [JsonProperty(Order = -2)]
        public abstract string Type { get; }
    }

    public static class ClientRole
    {
        public const string Vr = "vr";
    }

    public static class HandSide
    {
        public const string Left = "left";
        public const string Right = "right";
    }

    public static class SpellState
    {
        public const string Charging = "charging";
        public const string Cast = "cast";
        public const string Cancelled = "cancelled";
    }

    public sealed class DeviceInfo
    {
        public string Name { get; set; }
        public string Model { get; set; }

        /// <summary>A stable unique identifier for this headset.</summary>
        public string Id { get; set; }

        public static DeviceInfo ThisDevice() => new()
        {
            Name = SystemInfo.deviceName,
            Model = SystemInfo.deviceModel,
            Id = SystemInfo.deviceUniqueIdentifier,
        };
    }

    public sealed class HelloMessage : Message
    {
        public const string TypeName = "hello";
        public override string Type => TypeName;
        public string Role { get; set; }
        public DeviceInfo Device { get; set; }
    }

    public sealed class WelcomeMessage : Message
    {
        public const string TypeName = "welcome";
        public override string Type => TypeName;
        public string PlayerId { get; set; }
    }

    public sealed class ErrorMessage : Message
    {
        public const string TypeName = "error";
        public override string Type => TypeName;
        public string Message { get; set; }
    }

    public sealed class PairStartMessage : Message
    {
        public const string TypeName = "pair_start";
        public override string Type => TypeName;
    }

    public sealed class PairPromptMessage : Message
    {
        public const string TypeName = "pair_prompt";
        public override string Type => TypeName;
        public string PlayerId { get; set; }
    }

    public sealed class PairedMessage : Message
    {
        public const string TypeName = "paired";
        public override string Type => TypeName;
        public string PlayerId { get; set; }
    }

    public sealed class JointPose
    {
        /// <summary>[x, y, z]</summary>
        public float[] Pos { get; set; }

        /// <summary>[w, x, y, z]</summary>
        public float[] Rot { get; set; }

        [JsonIgnore]
        public Vector3 Position => new(Pos[0], Pos[1], Pos[2]);

        [JsonIgnore]
        public Quaternion Rotation => new(Rot[1], Rot[2], Rot[3], Rot[0]);

        public static JointPose FromTransform(Transform transform)
        {
            var position = transform.position;
            var rotation = transform.rotation;
            return new JointPose
            {
                Pos = new[] { position.x, position.y, position.z },
                Rot = new[] { rotation.w, rotation.x, rotation.y, rotation.z },
            };
        }
    }

    public sealed class BodyJoints
    {
        public JointPose Head { get; set; }
        public JointPose Chest { get; set; }
        public JointPose Hips { get; set; }
        public JointPose LShoulder { get; set; }
        public JointPose RShoulder { get; set; }
        public JointPose LElbow { get; set; }
        public JointPose RElbow { get; set; }
        public JointPose LWrist { get; set; }
        public JointPose RWrist { get; set; }
        public JointPose LHand { get; set; }
        public JointPose RHand { get; set; }
        public JointPose LKnee { get; set; }
        public JointPose RKnee { get; set; }
        public JointPose LAnkle { get; set; }
        public JointPose RAnkle { get; set; }
        public JointPose LFoot { get; set; }
        public JointPose RFoot { get; set; }

        [JsonIgnore]
        public IEnumerable<JointPose> All => new[]
        {
            Head, Chest, Hips, LShoulder, RShoulder, LElbow, RElbow, LWrist, RWrist, LHand, RHand,
            LKnee, RKnee, LAnkle, RAnkle, LFoot, RFoot,
        };
    }

    public sealed class PoseMessage : Message
    {
        public const string TypeName = "pose";
        public override string Type => TypeName;
        public string PlayerId { get; set; }
        public double T { get; set; }
        public BodyJoints Joints { get; set; }
    }

    public sealed class SignMessage : Message
    {
        public const string TypeName = "sign";
        public override string Type => TypeName;
        public string PlayerId { get; set; }
        public double T { get; set; }
        public string Hand { get; set; }
        public string Sign { get; set; }
        public float Confidence { get; set; }
    }

    public sealed class SpellMessage : Message
    {
        public const string TypeName = "spell";
        public override string Type => TypeName;
        public string CasterId { get; set; }
        public string Spell { get; set; }
        public string State { get; set; }
        public float Charge { get; set; }
        public float[] Origin { get; set; }
        public float[] Direction { get; set; }
    }

    public sealed class DamageMessage : Message
    {
        public const string TypeName = "damage";
        public override string Type => TypeName;
        public string TargetId { get; set; }
        public string SourceId { get; set; }
        public float Amount { get; set; }
        public float HpAfter { get; set; }
    }

    public static class SpellKind
    {
        public const string Fireball = "fireball";
    }

    public static class ImpactReason
    {
        public const string Hit = "hit";
        public const string Expired = "expired";
    }

    public sealed class ImpactMessage : Message
    {
        public const string TypeName = "impact";
        public override string Type => TypeName;
        public int ProjectileId { get; set; }
        public string Kind { get; set; }
        public string OwnerId { get; set; }
        public float[] Pos { get; set; }
        public string Reason { get; set; }
        public string TargetId { get; set; }

        [JsonIgnore]
        public Vector3 Position => new(Pos[0], Pos[1], Pos[2]);
    }

    public sealed class PlayerSnapshot
    {
        public string PlayerId { get; set; }
        public float Hp { get; set; }
        public bool Connected { get; set; }
        public bool BandPaired { get; set; }
        public string Sign { get; set; }

        /// <summary>What the player currently holds, e.g. <see cref="SpellKind.Fireball"/> or "none".</summary>
        public string Item { get; set; }

        public string BandHand { get; set; } = HandSide.Right;

        /// <summary>Seconds until the player can conjure again.</summary>
        public float Cooldown { get; set; }
    }

    public sealed class ProjectileSnapshot
    {
        public int Id { get; set; }
        public string Kind { get; set; }
        public string OwnerId { get; set; }
        public float[] Pos { get; set; }
        public float[] Vel { get; set; }

        [JsonIgnore]
        public Vector3 Position => new(Pos[0], Pos[1], Pos[2]);

        [JsonIgnore]
        public Vector3 Velocity => new(Vel[0], Vel[1], Vel[2]);
    }

    /// <summary>Full game state, broadcast every server tick.</summary>
    public sealed class StateMessage : Message
    {
        public const string TypeName = "state";
        public override string Type => TypeName;
        public int Tick { get; set; }
        public List<PlayerSnapshot> Players { get; set; } = new();
        public List<ProjectileSnapshot> Projectiles { get; set; } = new();
    }
}
