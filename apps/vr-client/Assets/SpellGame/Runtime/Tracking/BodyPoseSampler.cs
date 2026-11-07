using System.Collections.Generic;
using System.Linq;
using SpellGame.Protocol;
using UnityEngine;
using BoneId = OVRSkeleton.BoneId;

namespace SpellGame.Tracking
{
    /// <summary>
    /// Reads the body joints the server needs (architecture.md §6 <c>pose</c>) from a Movement SDK
    /// body skeleton (<see cref="OVRBody"/> + <see cref="OVRSkeleton"/> of type FullBody; legs are estimated by the runtime).
    /// </summary>
    public sealed class BodyPoseSampler
    {
        private readonly OVRSkeleton _skeleton;
        private Dictionary<BoneId, Transform> _bones;

        public BodyPoseSampler(OVRSkeleton skeleton)
        {
            _skeleton = skeleton;
        }

        public bool IsTracking => _skeleton.IsInitialized && _skeleton.IsDataValid;

        public BodyJoints Sample()
        {
            _bones ??= _skeleton.Bones.ToDictionary(bone => bone.Id, bone => bone.Transform);

            return new BodyJoints
            {
                Head = Joint(BoneId.FullBody_Head),
                Chest = Joint(BoneId.FullBody_Chest),
                Hips = Joint(BoneId.FullBody_Hips),
                LShoulder = Joint(BoneId.FullBody_LeftArmUpper),
                RShoulder = Joint(BoneId.FullBody_RightArmUpper),
                LElbow = Joint(BoneId.FullBody_LeftArmLower),
                RElbow = Joint(BoneId.FullBody_RightArmLower),
                LWrist = Joint(BoneId.FullBody_LeftHandWrist),
                RWrist = Joint(BoneId.FullBody_RightHandWrist),
                LHand = Joint(BoneId.FullBody_LeftHandPalm),
                RHand = Joint(BoneId.FullBody_RightHandPalm),
                LKnee = Joint(BoneId.FullBody_LeftLowerLeg),
                RKnee = Joint(BoneId.FullBody_RightLowerLeg),
                LAnkle = Joint(BoneId.FullBody_LeftFootAnkle),
                RAnkle = Joint(BoneId.FullBody_RightFootAnkle),
                LFoot = Joint(BoneId.FullBody_LeftFootBall),
                RFoot = Joint(BoneId.FullBody_RightFootBall),
            };
        }

        private JointPose Joint(BoneId boneId) => JointPose.FromTransform(_bones[boneId]);
    }
}
