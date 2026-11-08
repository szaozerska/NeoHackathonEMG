using UnityEngine;

namespace SpellGame.Game
{
    /// <summary>
    /// Starts the server's pairing mode (architecture.md §5) when B or Y is pressed on either Touch controller.
    /// The server then prompts each headset without a band, in join order, to pinch.
    /// </summary>
    public sealed class PairingButton : MonoBehaviour
    {
        [SerializeField] private GameClient gameClient;

        private void Update()
        {
            if (OVRInput.GetDown(OVRInput.Button.Two, OVRInput.Controller.LTouch) ||
                OVRInput.GetDown(OVRInput.Button.Two, OVRInput.Controller.RTouch))
                gameClient.StartPairing();
        }
    }
}
