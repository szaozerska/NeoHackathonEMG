using System;
using System.Collections.Generic;
using System.Net;
using System.Threading.Tasks;
using SpellGame.Networking;
using SpellGame.Protocol;
using SpellGame.Tracking;
using UnityEngine;

namespace SpellGame.Game
{
    /// <summary>
    /// Composition root for the VR client (architecture.md §2.1): finds the server, streams local pose,
    /// and dispatches server state. Runs no game mechanics; gameplay views subscribe to the events below.
    /// </summary>
    public sealed class GameClient : MonoBehaviour
    {
        [SerializeField] private OVRSkeleton bodySkeleton;
        [SerializeField] private DebugSkeletonsView debugSkeletons;
        [SerializeField] private TextMesh statusLabel;

        [Header("Server")]
        [Tooltip("Leave empty to find the server through the UDP discovery beacon.")]
        [SerializeField] private string manualServerHost = "";
        [SerializeField] private int manualServerPort = 9000;
        [SerializeField] private int discoveryPort = 47777;

        [Header("Pose stream")]
        [SerializeField, Range(1f, 90f)] private float poseSendRateHz = 30f;

        private BodyPoseSampler _poseSampler;
        private ServerConnection _connection;
        private string _playerId;
        private float _nextPoseSendTime;
        private BodyJoints _localJoints;
        private readonly Dictionary<string, BodyJoints> _remoteJoints = new();

        public event Action<SignMessage> SignReceived;
        public event Action<SpellMessage> SpellReceived;
        public event Action<DamageMessage> DamageReceived;
        public event Action<ImpactMessage> ImpactReceived;
        public event Action<StateMessage> StateReceived;

        public string PlayerId => _playerId;

        /// <summary>The server this client connected to, once resolved.</summary>
        public IPEndPoint ServerEndpoint { get; private set; }

        /// <summary>
        /// Latest joints for a player: the local player's come from local tracking (no network delay), others' from the server.
        /// </summary>
        public bool TryGetJoints(string playerId, out BodyJoints joints)
        {
            if (playerId != null && playerId == _playerId)
            {
                joints = _localJoints;
                return joints != null;
            }

            return _remoteJoints.TryGetValue(playerId ?? "", out joints);
        }

        private async void Start()
        {
            _poseSampler = new BodyPoseSampler(bodySkeleton);
            SetStatus("Searching for server…");
            var endpoint = await ResolveServerAsync();

            SetStatus($"Connecting to {endpoint}…");
            _connection = await ServerConnection.ConnectAsync(endpoint, destroyCancellationToken);
            ServerEndpoint = endpoint;
            _connection.Send(new HelloMessage { Role = ClientRole.Vr, Device = DeviceInfo.ThisDevice() });
        }

        private const string LocalSkeletonId = "local";

        private void Update()
        {
            DrawLocalSkeleton();

            if (_connection == null)
                return;

            if (!_connection.IsOpen)
            {
                SetStatus("Disconnected from server");
                return;
            }

            foreach (var message in _connection.DrainInbound())
                Handle(message);

            SendPoseWhenDue();
        }

        private void OnDestroy()
        {
            _connection?.Dispose();
        }

        private Task<IPEndPoint> ResolveServerAsync()
        {
            if (string.IsNullOrWhiteSpace(manualServerHost))
                return ServerDiscovery.FindServerAsync(discoveryPort, destroyCancellationToken);

            return Task.FromResult(new IPEndPoint(IPAddress.Parse(manualServerHost), manualServerPort));
        }

        private void Handle(Message message)
        {
            switch (message)
            {
                case WelcomeMessage welcome:
                    _playerId = welcome.PlayerId;
                    SetStatus($"You are {_playerId}");
                    break;
                case ErrorMessage error:
                    Debug.LogError($"Server error: {error.Message}");
                    break;
                case PairStartMessage:
                    SetStatus("Pairing Neural Bands…");
                    break;
                case PairPromptMessage prompt:
                    SetStatus(prompt.PlayerId == _playerId ? "Pinch your fingers to pair your band" : $"Waiting for {prompt.PlayerId} to pinch…");
                    break;
                case PairedMessage paired when paired.PlayerId == _playerId:
                    SetStatus($"You are {_playerId} · band paired");
                    break;
                case PoseMessage pose when pose.PlayerId != _playerId:
                    _remoteJoints[pose.PlayerId] = pose.Joints;
                    debugSkeletons.Draw(pose.PlayerId, pose.Joints);
                    break;
                case SignMessage sign:
                    SignReceived?.Invoke(sign);
                    break;
                case SpellMessage spell:
                    SpellReceived?.Invoke(spell);
                    break;
                case DamageMessage damage:
                    DamageReceived?.Invoke(damage);
                    break;
                case ImpactMessage impact:
                    ImpactReceived?.Invoke(impact);
                    break;
                case StateMessage state:
                    StateReceived?.Invoke(state);
                    break;
            }
        }

        private void DrawLocalSkeleton()
        {
            if (_poseSampler == null || !_poseSampler.IsTracking)
                return;

            _localJoints = _poseSampler.Sample();
            debugSkeletons.Draw(LocalSkeletonId, _localJoints);
        }

        private void SendPoseWhenDue()
        {
            if (_playerId == null || !_poseSampler.IsTracking || Time.unscaledTime < _nextPoseSendTime)
                return;

            _nextPoseSendTime = Time.unscaledTime + 1f / poseSendRateHz;
            _connection.Send(new PoseMessage
            {
                PlayerId = _playerId,
                T = Time.realtimeSinceStartupAsDouble,
                Joints = _localJoints,
            });
        }

        private void SetStatus(string text)
        {
            statusLabel.text = text;
        }
    }
}
