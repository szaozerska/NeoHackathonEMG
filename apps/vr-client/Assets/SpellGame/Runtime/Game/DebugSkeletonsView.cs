using System;
using System.Collections.Generic;
using System.Linq;
using SpellGame.Protocol;
using UnityEngine;
using UnityEngine.Rendering;

namespace SpellGame.Game
{
    /// <summary>Debug view: draws each player's <see cref="BodyJoints"/> (local and remote) as unlit line segments.</summary>
    public sealed class DebugSkeletonsView : MonoBehaviour
    {
        private const float BoneWidth = 0.005f;

        private static readonly (Func<BodyJoints, JointPose> From, Func<BodyJoints, JointPose> To)[] Bones =
        {
            (j => j.Head, j => j.Chest),
            (j => j.Chest, j => j.Hips),
            (j => j.Chest, j => j.LShoulder),
            (j => j.LShoulder, j => j.LElbow),
            (j => j.LElbow, j => j.LWrist),
            (j => j.LWrist, j => j.LHand),
            (j => j.Chest, j => j.RShoulder),
            (j => j.RShoulder, j => j.RElbow),
            (j => j.RElbow, j => j.RWrist),
            (j => j.RWrist, j => j.RHand),
            (j => j.Hips, j => j.LKnee),
            (j => j.LKnee, j => j.LAnkle),
            (j => j.LAnkle, j => j.LFoot),
            (j => j.Hips, j => j.RKnee),
            (j => j.RKnee, j => j.RAnkle),
            (j => j.RAnkle, j => j.RFoot),
        };

        [SerializeField] private Material boneMaterial;

        private readonly Dictionary<string, LineRenderer[]> _bonesBySkeleton = new();

        public void Draw(string skeletonId, BodyJoints joints)
        {
            var lines = BonesFor(skeletonId);
            for (var i = 0; i < Bones.Length; i++)
            {
                lines[i].SetPosition(0, Bones[i].From(joints).Position);
                lines[i].SetPosition(1, Bones[i].To(joints).Position);
            }
        }

        private LineRenderer[] BonesFor(string skeletonId)
        {
            if (_bonesBySkeleton.TryGetValue(skeletonId, out var existing))
                return existing;

            var root = new GameObject($"Skeleton {skeletonId}").transform;
            root.SetParent(transform, false);
            var lines = Bones.Select(_ => CreateBone(root)).ToArray();
            _bonesBySkeleton[skeletonId] = lines;
            return lines;
        }

        private LineRenderer CreateBone(Transform root)
        {
            var bone = new GameObject("Bone");
            bone.transform.SetParent(root, false);
            var line = bone.AddComponent<LineRenderer>();
            line.sharedMaterial = boneMaterial;
            line.startWidth = BoneWidth;
            line.endWidth = BoneWidth;
            line.positionCount = 2;
            line.useWorldSpace = true;
            line.shadowCastingMode = ShadowCastingMode.Off;
            return line;
        }
    }
}
