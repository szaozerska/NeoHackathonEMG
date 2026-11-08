using System.Threading.Tasks;
using SpellGame.Networking;
using SpellGame.Protocol;
using UnityEngine;

namespace SpellGame.Game
{
    /// <summary>
    /// Debug stand-in for the Neural Band: Touch controller buttons on the band hand become <c>sign</c> messages, sent
    /// over a second connection that joins as this headset's classifier (architecture.md §5, direct pairing by player ID).
    /// The controller's tracked position is the hand position, exactly as body tracking reports it for the real band.
    /// <list type="bullet">
    /// <item>trigger: <c>snap</c> (conjure a fireball, then throw by arm motion)</item>
    /// <item>grip held: <c>fist</c> (start at the opposite pocket and pull up and across to draw the sword)</item>
    /// <item>A / X held: <c>open_palm</c> (shield; push forward sharply to boost)</item>
    /// </list>
    /// Disable this component when a real band is paired.
    /// </summary>
    public sealed class ControllerBand : MonoBehaviour
    {
        [SerializeField] private GameClient gameClient;
        [SerializeField] private string bandHand = HandSide.Right;
        [SerializeField, Range(0.1f, 0.9f)] private float pressThreshold = 0.5f;

        private ServerConnection _connection;
        private bool _connecting;
        private string _sentSign;

        private OVRInput.Controller Controller =>
            bandHand == HandSide.Left ? OVRInput.Controller.LTouch : OVRInput.Controller.RTouch;

        private void Update()
        {
            if (_connection == null)
            {
                if (!_connecting && gameClient.PlayerId != null && gameClient.ServerEndpoint != null)
                    _ = ConnectAsync();
                return;
            }

            if (!_connection.IsOpen)
            {
                _connection.Dispose();
                _connection = null;
                _sentSign = null;
                return;
            }

            foreach (var _ in _connection.DrainInbound())
            {
            }

            var sign = CurrentSign();
            if (sign == _sentSign)
                return;

            _sentSign = sign;
            _connection.Send(new SignMessage
            {
                PlayerId = gameClient.PlayerId,
                T = Time.realtimeSinceStartupAsDouble,
                Hand = bandHand,
                Sign = sign,
                Confidence = 1f,
            });
        }

        private void OnDestroy()
        {
            _connection?.Dispose();
        }

        private async Task ConnectAsync()
        {
            _connecting = true;
            try
            {
                var connection = await ServerConnection.ConnectAsync(gameClient.ServerEndpoint, destroyCancellationToken);
                connection.Send(new HelloMessage { Role = ClientRole.Classifier, PlayerId = gameClient.PlayerId });
                _connection = connection;
            }
            catch (System.Exception exception) when (exception is not System.OperationCanceledException)
            {
                Debug.LogWarning($"[ControllerBand] Could not connect: {exception.Message}");
            }
            finally
            {
                _connecting = false;
            }
        }

        private string CurrentSign()
        {
            if (OVRInput.Get(OVRInput.Axis1D.PrimaryHandTrigger, Controller) > pressThreshold)
                return BandSign.Fist;
            if (OVRInput.Get(OVRInput.Button.One, Controller))
                return BandSign.OpenPalm;
            if (OVRInput.Get(OVRInput.Axis1D.PrimaryIndexTrigger, Controller) > pressThreshold)
                return BandSign.Snap;
            return BandSign.None;
        }
    }
}
