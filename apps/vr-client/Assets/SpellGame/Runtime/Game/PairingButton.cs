using UnityEngine;

namespace SpellGame.Game
{
    /// <summary>
    /// Starts the server's pairing mode (architecture.md §5) when X and Y on the left Touch controller are held together
    /// for <see cref="holdSeconds"/>; once per hold. The server then prompts each headset without a band, in join order,
    /// to pinch.
    /// </summary>
    public sealed class PairingButton : MonoBehaviour
    {
        [SerializeField] private GameClient gameClient;
        [SerializeField] private float holdSeconds = 3f;

        private HoldTrigger _hold;

        private static bool XAndYHeld =>
            OVRInput.Get(OVRInput.Button.One, OVRInput.Controller.LTouch) &&
            OVRInput.Get(OVRInput.Button.Two, OVRInput.Controller.LTouch);

        private void Awake()
        {
            _hold = new HoldTrigger(holdSeconds);
        }

        private void Update()
        {
            if (_hold.Update(XAndYHeld, Time.unscaledDeltaTime))
                gameClient.StartPairing();
        }
    }
}
