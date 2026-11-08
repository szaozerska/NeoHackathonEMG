using UnityEngine;

namespace SpellGame.Game
{
    /// <summary>Holding B on the right Touch controller for <see cref="holdSeconds"/> expands this player's domain; once per hold.</summary>
    public sealed class DomainExpansionButton : MonoBehaviour
    {
        [SerializeField] private GameClient gameClient;
        [SerializeField] private float holdSeconds = 4f;

        private HoldTrigger _hold;

        private static bool BHeld => OVRInput.Get(OVRInput.Button.Two, OVRInput.Controller.RTouch);

        private void Awake()
        {
            _hold = new HoldTrigger(holdSeconds);
        }

        private void Update()
        {
            if (_hold.Update(BHeld, Time.unscaledDeltaTime))
                gameClient.ExpandDomain();
        }
    }
}
