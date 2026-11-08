using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using System.Threading;
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
        [Tooltip("Optional head-locked debug label; the match menu shows the same status under its panel.")]
        [SerializeField] private TextMesh statusLabel;

        [Header("Server")]
        [Tooltip("Leave empty to find the server through the UDP discovery beacon.")]
        [SerializeField] private string manualServerHost = "";
        [SerializeField] private int manualServerPort = 9100;
        [SerializeField] private int discoveryPort = 47777;
        [SerializeField, Min(1f)] private float connectTimeoutSeconds = 5f;

        [Header("Pose stream")]
        [SerializeField, Range(1f, 90f)] private float poseSendRateHz = 72f;

        private BodyPoseSampler _poseSampler;
        private ServerConnection _connection;
        private CancellationTokenSource _attempt;
        private string _playerId;
        private bool _bandPaired;
        private float _nextPoseSendTime;

        /// <summary>Sent in the next <c>hello</c>, so a reconnecting headset keeps its player ID and floor spot.</summary>
        private string _lastPlayerId;
        private BodyJoints _localJoints;
        private readonly Dictionary<string, BodyJoints> _remoteJoints = new();
        private string _status = "";
        private string _spaceStatus = "";
        private string _hpStatus = "";

        public event Action<SignMessage> SignReceived;
        public event Action<SpellMessage> SpellReceived;
        public event Action<DamageMessage> DamageReceived;
        public event Action<ImpactMessage> ImpactReceived;
        public event Action<StateMessage> StateReceived;
        public event Action<SpaceMessage> SpaceReceived;
        public event Action<DomainExpansionMessage> DomainExpansionReceived;
        public event Action<ConnectionState> ConnectionChanged;

        public string PlayerId => _playerId;
        public ConnectionState Connection { get; private set; } = ConnectionState.Searching;
        public TimeSpan ConnectTimeout => TimeSpan.FromSeconds(connectTimeoutSeconds);

        /// <summary>Stops finding or joining the server; leaves the client <see cref="ConnectionState.Cancelled"/>.</summary>
        public void CancelConnecting()
        {
            if (Connection is not (ConnectionState.Searching or ConnectionState.Connecting))
                return;

            _attempt?.Cancel();
            CloseConnection();
            SetConnection(ConnectionState.Cancelled, "Connection cancelled");
        }

        /// <summary>Looks for the server again after a cancel, a failed connect or a disconnect.</summary>
        public void Rescan()
        {
            if (Connection is ConnectionState.Searching or ConnectionState.Connecting or ConnectionState.Connected)
                return;

            ConnectAsync();
        }

        /// <summary>Connection, pairing, room-alignment and HP status lines.</summary>
        public string StatusText { get; private set; } = "";

        /// <summary>Asks the server to start pairing mode (architecture.md §5).</summary>
        public void StartPairing() => Send(new PairStartMessage());

        /// <summary>Asks the server to expand this player's domain (Infinite Void).</summary>
        public void ExpandDomain() => Send(new DomainExpandMessage());

        /// <summary>Sends a message to the server; dropped while not connected.</summary>
        public void Send(Message message)
        {
            if (_connection == null || !_connection.IsOpen)
                return;

            _connection.Send(message);
        }

        /// <summary>Second status line, for the shared room frame (architecture.md §5.1).</summary>
        public void SetSpaceStatus(string text)
        {
            _spaceStatus = text;
            RenderStatus();
        }

        /// <summary>The server this client is connecting or connected to, once discovery has found it.</summary>
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

        private void Start()
        {
            _poseSampler = new BodyPoseSampler(bodySkeleton);
            ConnectAsync();
        }

        /// <summary>Finds the server and opens the connection; <see cref="WelcomeMessage"/> then makes it Connected.</summary>
        private async void ConnectAsync()
        {
            using var attempt = CancellationTokenSource.CreateLinkedTokenSource(destroyCancellationToken);
            _attempt = attempt;
            ServerEndpoint = null;
            SetConnection(ConnectionState.Searching, "Searching for server…");
            ServerConnection connection;
            try
            {
                ServerEndpoint = await ResolveServerAsync(attempt.Token);
                SetConnection(ConnectionState.Connecting, $"Connecting to {ServerEndpoint}…");
                connection = await ServerConnection.ConnectAsync(ServerEndpoint, ConnectTimeout, attempt.Token);
            }
            catch (Exception) when (attempt.IsCancellationRequested)
            {
                return;
            }
            catch (Exception exception) when (exception is SocketException or ObjectDisposedException)
            {
                SetConnection(ConnectionState.Unreachable, $"Can't reach server at {ServerEndpoint}");
                return;
            }
            finally
            {
                if (_attempt == attempt)
                    _attempt = null;
            }

            if (attempt.IsCancellationRequested)
            {
                connection.Dispose();
                return;
            }

            _connection = connection;
            _connection.Send(new HelloMessage { Role = ClientRole.Vr, Device = DeviceInfo.ThisDevice(), PlayerId = _lastPlayerId });
        }

        private void CloseConnection()
        {
            _connection?.Dispose();
            _connection = null;
            _lastPlayerId = _playerId ?? _lastPlayerId;
            _playerId = null;
            _bandPaired = false;
            _remoteJoints.Clear();
        }

        private void SetConnection(ConnectionState state, string status)
        {
            Connection = state;
            SetStatus(status);
            ConnectionChanged?.Invoke(state);
        }

        private const string LocalSkeletonId = "local";

        private void Update()
        {
            DrawLocalSkeleton();

            if (_connection == null)
                return;

            if (!_connection.IsOpen)
            {
                CloseConnection();
                SetConnection(ConnectionState.Disconnected, "Disconnected from server");
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

        private Task<IPEndPoint> ResolveServerAsync(CancellationToken cancellationToken)
        {
            if (string.IsNullOrWhiteSpace(manualServerHost))
                return ServerDiscovery.FindServerAsync(discoveryPort, cancellationToken);

            return Task.FromResult(new IPEndPoint(IPAddress.Parse(manualServerHost), manualServerPort));
        }

        private void Handle(Message message)
        {
            switch (message)
            {
                case WelcomeMessage welcome:
                    _playerId = welcome.PlayerId;
                    SetConnection(ConnectionState.Connected, IdleStatus());
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
                case PairedMessage paired:
                    _bandPaired |= paired.PlayerId == _playerId;
                    SetStatus(IdleStatus());
                    break;
                case PoseMessage pose when pose.PlayerId != _playerId:
                    _remoteJoints[pose.PlayerId] = pose.Joints;
                    if (pose.PlayerId != MatchMode.AiPlayerId)
                        debugSkeletons.Draw(pose.PlayerId, pose.Joints, withBody: true);
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
                    UpdateHpStatus(state);
                    StateReceived?.Invoke(state);
                    break;
                case SpaceMessage space:
                    SpaceReceived?.Invoke(space);
                    break;
                case DomainExpansionMessage domain:
                    DomainExpansionReceived?.Invoke(domain);
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

        /// <summary>
        /// Shown outside pairing prompts. A <c>paired</c> for any player restores it, so the last pairing doesn't leave
        /// "Waiting for … to pinch" behind; a following <c>pair_prompt</c> replaces it straight away.
        /// </summary>
        private string IdleStatus() =>
            _bandPaired ? $"You are {_playerId} · band paired" : $"You are {_playerId} · hold X+Y to pair bands";

        private void SetStatus(string text)
        {
            _status = text;
            RenderStatus();
        }

        /// <summary>Own HP (or death) and every other player's HP, on a line under the status.</summary>
        private void UpdateHpStatus(StateMessage state)
        {
            var own = "";
            var others = new List<string>();
            foreach (var player in state.Players)
            {
                if (player.PlayerId == _playerId)
                    own = player.Hp > 0f ? $"HP {player.Hp:0}" : "YOU ARE DEAD";
                else
                    others.Add(player.Hp > 0f ? $"{player.PlayerId} {player.Hp:0}" : $"{player.PlayerId} dead");
            }

            var text = others.Count == 0 ? own : $"{own}   ·   {string.Join("  ", others)}";
            if (text == _hpStatus)
                return;
            _hpStatus = text;
            RenderStatus();
        }

        private void RenderStatus()
        {
            var lines = new List<string> { _status };
            if (!string.IsNullOrEmpty(_spaceStatus))
                lines.Add(_spaceStatus);
            if (!string.IsNullOrEmpty(_hpStatus))
                lines.Add(_hpStatus);
            StatusText = string.Join("\n", lines);
            if (statusLabel != null)
                statusLabel.text = StatusText;
        }
    }
}
