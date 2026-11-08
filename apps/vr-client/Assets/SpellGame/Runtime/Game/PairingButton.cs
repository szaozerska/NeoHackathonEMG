using UnityEngine;

namespace SpellGame.Game
{
    /// <summary>
    /// Starts the server's pairing mode (architecture.md §5) when X on the left Touch controller is held for
    /// <see cref="holdSeconds"/>; once per hold. The server then prompts every headset, in join order, to pinch.
    /// </summary>
    public sealed class PairingButton : MonoBehaviour
    {
        [SerializeField] private GameClient gameClient;
        [SerializeField] private float holdSeconds = 3f;

        private HoldTrigger _hold;

        private static bool XHeld => OVRInput.Get(OVRInput.Button.One, OVRInput.Controller.LTouch);

        private void Awake()
        {
            _hold = new HoldTrigger(holdSeconds);
        }

        private void Update()
        {
            if (_hold.Update(XHeld, Time.unscaledDeltaTime))
                gameClient.StartPairing();
        }
    }
}
