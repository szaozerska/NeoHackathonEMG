using System;
using System.Collections.Generic;
using System.Linq;
using SpellGame.Protocol;
using UnityEngine;
using UnityEngine.Rendering;

namespace SpellGame.Game
{
    /// <summary>
    /// Debug view: draws each player's <see cref="BodyJoints"/> (local and remote) as unlit line segments, and gives
    /// remote players a solid stand-in body (head, torso, limbs, hands) with a floating player-ID label so they are
    /// easy to find in the room.
    /// </summary>
    public sealed class DebugSkeletonsView : MonoBehaviour
    {
        private const float BoneWidth = 0.005f;
        private const float HeadDiameter = 0.22f;
        private const float TorsoWidth = 0.3f;
        private const float LimbWidth = 0.08f;
        private const float HandDiameter = 0.1f;
        private const float LabelHeightAboveHead = 0.3f;

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

        private static readonly (Func<BodyJoints, JointPose> From, Func<BodyJoints, JointPose> To)[] Limbs =
        {
            (j => j.LShoulder, j => j.LElbow),
            (j => j.LElbow, j => j.LWrist),
            (j => j.RShoulder, j => j.RElbow),
            (j => j.RElbow, j => j.RWrist),
            (j => j.Hips, j => j.LKnee),
            (j => j.LKnee, j => j.LAnkle),
            (j => j.Hips, j => j.RKnee),
            (j => j.RKnee, j => j.RAnkle),
        };

        [SerializeField] private Material boneMaterial;
        [SerializeField] private Material bodyMaterial;

        private readonly Dictionary<string, LineRenderer[]> _bonesBySkeleton = new();
        private readonly Dictionary<string, Body> _bodiesBySkeleton = new();

        private sealed class Body
        {
            public Transform Head;
            public Transform Torso;
            public Transform LHand;
            public Transform RHand;
            public Transform[] Limbs;
            public TextMesh Label;
        }

        public void Draw(string skeletonId, BodyJoints joints, bool withBody = false)
        {
            var lines = BonesFor(skeletonId);
            for (var i = 0; i < Bones.Length; i++)
            {
                lines[i].SetPosition(0, Bones[i].From(joints).Position);
                lines[i].SetPosition(1, Bones[i].To(joints).Position);
            }

            if (withBody)
                PlaceBody(BodyFor(skeletonId), joints);
        }

        private static void PlaceBody(Body body, BodyJoints joints)
        {
            var head = joints.Head.Position;
            body.Head.SetPositionAndRotation(head, joints.Head.Rotation);
            SpellVfx.PlaceBlade(body.Torso, joints.Hips.Position, joints.Chest.Position, TorsoWidth);
            body.LHand.position = joints.LHand.Position;
            body.RHand.position = joints.RHand.Position;
            for (var i = 0; i < Limbs.Length; i++)
                SpellVfx.PlaceBlade(body.Limbs[i], Limbs[i].From(joints).Position, Limbs[i].To(joints).Position, LimbWidth);

            var label = body.Label.transform;
            label.position = head + Vector3.up * LabelHeightAboveHead;
            var viewer = Camera.main;
            if (viewer != null)
                label.rotation = Quaternion.LookRotation(label.position - viewer.transform.position);
        }

        private Body BodyFor(string skeletonId)
        {
            if (_bodiesBySkeleton.TryGetValue(skeletonId, out var existing))
                return existing;

            var root = new GameObject($"Body {skeletonId}").transform;
            root.SetParent(transform, false);
            var material = bodyMaterial != null ? bodyMaterial : boneMaterial;
            var body = new Body
            {
                Head = SpellVfx.CreateOrb("Head", root, material, HeadDiameter),
                Torso = SpellVfx.CreateBlade("Torso", root, material),
                LHand = SpellVfx.CreateOrb("LHand", root, material, HandDiameter),
                RHand = SpellVfx.CreateOrb("RHand", root, material, HandDiameter),
                Limbs = Limbs.Select(_ => SpellVfx.CreateBlade("Limb", root, material)).ToArray(),
                Label = CreateLabel(root, skeletonId),
            };
            _bodiesBySkeleton[skeletonId] = body;
            return body;
        }

        private static TextMesh CreateLabel(Transform root, string text)
        {
            var label = new GameObject("Label").AddComponent<TextMesh>();
            label.transform.SetParent(root, false);
            label.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            label.GetComponent<MeshRenderer>().sharedMaterial = label.font.material;
            label.anchor = TextAnchor.MiddleCenter;
            label.alignment = TextAlignment.Center;
            label.characterSize = 0.02f;
            label.fontSize = 64;
            label.text = text;
            return label;
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
