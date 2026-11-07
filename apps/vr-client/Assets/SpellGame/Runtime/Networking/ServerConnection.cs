using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.ExceptionServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using SpellGame.Protocol;

namespace SpellGame.Networking
{
    /// <summary>
    /// One TCP connection to the game server (architecture.md §4). Lines are read on a background thread and
    /// decoded on whichever thread calls <see cref="DrainInbound"/> (the Unity main thread).
    /// </summary>
    public sealed class ServerConnection : IDisposable
    {
        private readonly TcpClient _client;
        private readonly StreamWriter _writer;
        private readonly ConcurrentQueue<string> _inboundLines = new();
        private readonly Task _readLoop;

        private ServerConnection(TcpClient client, CancellationToken cancellationToken)
        {
            _client = client;
            var stream = client.GetStream();
            _writer = new StreamWriter(stream, new UTF8Encoding(false)) { NewLine = "\n" };
            _readLoop = Task.Run(() => ReadLinesAsync(new StreamReader(stream, Encoding.UTF8), cancellationToken), cancellationToken);
        }

        public bool IsOpen => !_readLoop.IsCompleted;

        public static async Task<ServerConnection> ConnectAsync(IPEndPoint endpoint, CancellationToken cancellationToken)
        {
            var client = new TcpClient { NoDelay = true };
            using var disposeOnCancel = cancellationToken.Register(client.Dispose);
            await client.ConnectAsync(endpoint.Address, endpoint.Port);
            return new ServerConnection(client, cancellationToken);
        }

        public void Send(Message message)
        {
            _writer.WriteLine(MessageCodec.Encode(message));
            _writer.Flush();
        }

        /// <summary>Decodes every line received since the last call. Rethrows if the read loop failed.</summary>
        public IEnumerable<Message> DrainInbound()
        {
            if (_readLoop.IsFaulted)
                ExceptionDispatchInfo.Capture(_readLoop.Exception.InnerException).Throw();

            while (_inboundLines.TryDequeue(out var line))
            {
                var message = MessageCodec.Decode(line);
                if (message != null)
                    yield return message;
            }
        }

        private async Task ReadLinesAsync(StreamReader reader, CancellationToken cancellationToken)
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                var line = await reader.ReadLineAsync();
                if (line == null)
                    return;

                _inboundLines.Enqueue(line);
            }
        }

        public void Dispose()
        {
            _writer.Dispose();
            _client.Dispose();
        }
    }
}
