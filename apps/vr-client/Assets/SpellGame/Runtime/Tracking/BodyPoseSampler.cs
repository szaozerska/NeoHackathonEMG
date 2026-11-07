using System.Collections.Generic;
using System.Linq;
using SpellGame.Protocol;
using UnityEngine;
using BoneId = OVRSkeleton.BoneId;

namespace SpellGame.Tracking
{
    /// <summary>
    /// Reads the upper-body joints the server needs (architecture.md §6 <c>pose</c>) from a Movement SDK
    /// body skeleton (<see cref="OVRBody"/> + <see cref="OVRSkeleton"/> of type Body).
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
                Head = Joint(BoneId.Body_Head),
                Chest = Joint(BoneId.Body_Chest),
                LShoulder = Joint(BoneId.Body_LeftArmUpper),
                RShoulder = Joint(BoneId.Body_RightArmUpper),
                LElbow = Joint(BoneId.Body_LeftArmLower),
                RElbow = Joint(BoneId.Body_RightArmLower),
                LWrist = Joint(BoneId.Body_LeftHandWrist),
                RWrist = Joint(BoneId.Body_RightHandWrist),
                LHand = Joint(BoneId.Body_LeftHandPalm),
                RHand = Joint(BoneId.Body_RightHandPalm),
            };
        }

        private JointPose Joint(BoneId boneId) => JointPose.FromTransform(_bones[boneId]);
    }
}
