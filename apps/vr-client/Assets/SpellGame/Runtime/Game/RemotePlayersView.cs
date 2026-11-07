using System.Collections.Generic;
using System.Linq;
using SpellGame.Protocol;
using UnityEngine;

namespace SpellGame.Game
{
    /// <summary>Renders other players from server <c>pose</c> packets as one marker per joint.</summary>
    public sealed class RemotePlayersView : MonoBehaviour
    {
        [SerializeField] private GameObject jointMarkerPrefab;

        private readonly Dictionary<string, Transform[]> _markersByPlayer = new();

        public void ApplyPose(PoseMessage pose)
        {
            var markers = MarkersFor(pose.PlayerId);
            var joints = pose.Joints.All.ToArray();
            for (var i = 0; i < joints.Length; i++)
                markers[i].SetPositionAndRotation(joints[i].Position, joints[i].Rotation);
        }

        private Transform[] MarkersFor(string playerId)
        {
            if (_markersByPlayer.TryGetValue(playerId, out var existing))
                return existing;

            var root = new GameObject($"Remote {playerId}").transform;
            root.SetParent(transform, false);
            var jointCount = new BodyJoints().All.Count();
            var markers = Enumerable.Range(0, jointCount)
                .Select(_ => Instantiate(jointMarkerPrefab, root).transform)
                .ToArray();
            _markersByPlayer[playerId] = markers;
            return markers;
        }
    }
}
