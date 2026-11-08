using SpellGame.Protocol;
using TMPro;
using UnityEngine;

namespace SpellGame.Game
{
    /// <summary>
    /// While pairing mode (architecture.md §5) prompts the local player, shows "Pinch to pair your band" a metre ahead,
    /// just below eye level (not head-locked). It goes away when anyone is paired or another player is prompted, or the
    /// headset loses the server. A pairing is followed straight away by the grip calibration's own prompt
    /// (<see cref="GripCalibrationView"/>), so there's no separate confirmation here.
    /// </summary>
    public sealed class PairingPromptView : MonoBehaviour
    {
        [SerializeField] private GameClient gameClient;
        [SerializeField] private float distance = 1f;
        [SerializeField] private float drop = 0.15f;

        private TextMeshPro _label;

        private void OnEnable()
        {
            gameClient.PairPromptReceived += OnPairPrompt;
            gameClient.PairedReceived += OnPaired;
            gameClient.ConnectionChanged += OnConnectionChanged;
        }

        private void OnDisable()
        {
            gameClient.PairPromptReceived -= OnPairPrompt;
            gameClient.PairedReceived -= OnPaired;
            gameClient.ConnectionChanged -= OnConnectionChanged;
        }

        private void OnPairPrompt(PairPromptMessage prompt)
        {
            if (prompt.PlayerId != gameClient.PlayerId)
            {
                Hide();
                return;
            }
            _label ??= UiStyle.CreateText("Pairing Prompt", transform,
                "Pinch to pair your band\n<size=60%>Tap your index finger to your thumb</size>", Vector3.zero, 0.06f,
                UiStyle.Text, display: true, look: UiStyle.Look.Title, width: 1f);
            UiStyle.PlaceAhead(_label.transform, distance, drop);
            _label.gameObject.SetActive(true);
        }

        private void OnPaired(PairedMessage _) => Hide();

        private void OnConnectionChanged(ConnectionState state)
        {
            if (state != ConnectionState.Connected)
                Hide();
        }

        private void Hide()
        {
            if (_label != null)
                _label.gameObject.SetActive(false);
        }
    }
}
