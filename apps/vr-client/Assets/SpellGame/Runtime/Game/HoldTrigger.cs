namespace SpellGame.Game
{
    /// <summary>Fires once each time a button is held for <c>holdSeconds</c>; releasing starts the count again.</summary>
    public sealed class HoldTrigger
    {
        private readonly float _holdSeconds;
        private float _heldSeconds;
        private bool _firedThisHold;

        public HoldTrigger(float holdSeconds)
        {
            _holdSeconds = holdSeconds;
        }

        /// <summary>0-1 progress of the current hold; 0 once it has fired.</summary>
        public float Progress => _firedThisHold ? 0f : _heldSeconds >= _holdSeconds ? 1f : _heldSeconds / _holdSeconds;

        /// <summary>True on the frame the hold reaches <c>holdSeconds</c>.</summary>
        public bool Update(bool held, float deltaTime)
        {
            if (!held)
            {
                _heldSeconds = 0f;
                _firedThisHold = false;
                return false;
            }

            _heldSeconds += deltaTime;
            if (_firedThisHold || _heldSeconds < _holdSeconds)
                return false;

            _firedThisHold = true;
            return true;
        }
    }
}
