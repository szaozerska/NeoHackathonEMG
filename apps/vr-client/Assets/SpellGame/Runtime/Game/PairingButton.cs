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

        private float _heldSeconds;
        private bool _firedThisHold;

        private static bool XAndYHeld =>
            OVRInput.Get(OVRInput.Button.One, OVRInput.Controller.LTouch) &&
            OVRInput.Get(OVRInput.Button.Two, OVRInput.Controller.LTouch);

        private void Update()
        {
            if (!XAndYHeld)
            {
                _heldSeconds = 0f;
                _firedThisHold = false;
                return;
            }

            _heldSeconds += Time.unscaledDeltaTime;
            if (_firedThisHold || _heldSeconds < holdSeconds)
                return;

            _firedThisHold = true;
            gameClient.StartPairing();
        }
    }
}
