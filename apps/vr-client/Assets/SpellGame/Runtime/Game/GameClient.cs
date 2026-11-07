using System;
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

        public event Action<SignMessage> SignReceived;
        public event Action<SpellMessage> SpellReceived;
        public event Action<DamageMessage> DamageReceived;

        public string PlayerId => _playerId;

        private async void Start()
        {
            _poseSampler = new BodyPoseSampler(bodySkeleton);
            SetStatus("Searching for server…");
            var endpoint = await ResolveServerAsync();

            SetStatus($"Connecting to {endpoint}…");
            _connection = await ServerConnection.ConnectAsync(endpoint, destroyCancellationToken);
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
            }
        }

        private void DrawLocalSkeleton()
        {
            if (_poseSampler.IsTracking)
                debugSkeletons.Draw(LocalSkeletonId, _poseSampler.Sample());
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
                Joints = _poseSampler.Sample(),
            });
        }

        private void SetStatus(string text)
        {
            statusLabel.text = text;
        }
    }
}
