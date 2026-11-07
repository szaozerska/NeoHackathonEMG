using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace SpellGame.Networking
{
    /// <summary>Listens for the server's UDP beacon <c>SPELLGAME &lt;tcp_port&gt;</c> (architecture.md §4.1).</summary>
    public static class ServerDiscovery
    {
        private const string BeaconPrefix = "SPELLGAME ";

        public static async Task<IPEndPoint> FindServerAsync(int discoveryPort, CancellationToken cancellationToken)
        {
            using var multicastLock = AndroidMulticastLock.Acquire();
            using var udp = new UdpClient();
            udp.Client.SetSocketOption(SocketOptionLevel.Socket, SocketOptionName.ReuseAddress, true);
            udp.Client.Bind(new IPEndPoint(IPAddress.Any, discoveryPort));
            udp.EnableBroadcast = true;
            using var disposeOnCancel = cancellationToken.Register(udp.Dispose);

            while (true)
            {
                var packet = await udp.ReceiveAsync();
                if (TryParseTcpPort(packet.Buffer, out var tcpPort))
                    return new IPEndPoint(packet.RemoteEndPoint.Address, tcpPort);
            }
        }

        private static bool TryParseTcpPort(byte[] payload, out int tcpPort)
        {
            tcpPort = 0;
            var text = Encoding.ASCII.GetString(payload).Trim();
            return text.StartsWith(BeaconPrefix) && int.TryParse(text.Substring(BeaconPrefix.Length), out tcpPort);
        }
    }
}
