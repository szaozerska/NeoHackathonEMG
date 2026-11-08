using SpellGame.Protocol;
using TMPro;
using UnityEngine;

namespace SpellGame.Game
{
    /// <summary>
    /// Prompts for the band's grip calibration (hand-client <c>tension.py</c>): "Relax your band hand", then "Squeeze as
    /// hard as is comfortable", with a progress row, then a short confirmation. It's placed in the room a metre ahead,
    /// just below eye level, when each step starts (not head-locked). It only shows the local player's calibration.
    /// <see cref="Recalibrate"/> asks the band to run it again (e.g. from a menu button).
    /// </summary>
    public sealed class GripCalibrationView : MonoBehaviour
    {
        [SerializeField] private GameClient gameClient;
        [SerializeField] private float distance = 1f;
        [SerializeField] private float drop = 0.15f;
        [SerializeField] private float doneSeconds = 1.5f;
        [SerializeField] private float failedSeconds = 3.5f;

        private const int ProgressDots = 10;

        private TextMeshPro _label;
        private string _phase;
        private float _hideAt = float.PositiveInfinity;

        public void Recalibrate() => gameClient.Send(new CalibrateMessage());

        private void OnEnable() => gameClient.CalibrationReceived += OnCalibration;

        private void OnDisable() => gameClient.CalibrationReceived -= OnCalibration;

        private void Update()
        {
            if (_label != null && _label.gameObject.activeSelf && Time.time >= _hideAt)
                _label.gameObject.SetActive(false);
        }

        private void OnCalibration(CalibrationStatusMessage status)
        {
            if (status.PlayerId != gameClient.PlayerId)
                return;
            _label ??= UiStyle.CreateText("Calibration Prompt", transform, "", Vector3.zero, 0.06f, UiStyle.Text,
                display: true, look: UiStyle.Look.Title, width: 1f);
            if (status.Phase != _phase)
                PlaceInFront();
            _phase = status.Phase;
            _label.gameObject.SetActive(true);
            _hideAt = float.PositiveInfinity;
            switch (status.Phase)
            {
                case CalibrationPhase.Rest:
                    _label.text = $"Relax your band hand\n<size=60%>{Dots(status.Progress)}</size>";
                    break;
                case CalibrationPhase.Squeeze:
                    _label.text = $"Squeeze as hard as is comfortable\n<size=60%>{Dots(status.Progress)}</size>";
                    break;
                case CalibrationPhase.Done:
                    _label.text = "Grip calibrated!";
                    _hideAt = Time.time + doneSeconds;
                    break;
                default:
                    _label.text = "Couldn't read your grip\n<size=60%>Playing at normal strength</size>";
                    _hideAt = Time.time + failedSeconds;
                    break;
            }
        }

        private static string Dots(float progress)
        {
            var filled = Mathf.Clamp(Mathf.RoundToInt(progress * ProgressDots), 0, ProgressDots);
            return new string('•', filled) + "<alpha=#40>" + new string('•', ProgressDots - filled);
        }

        private void PlaceInFront()
        {
            var head = Camera.main != null ? Camera.main.transform : null;
            if (head == null)
                return;
            var forward = Vector3.ProjectOnPlane(head.forward, Vector3.up);
            if (forward.sqrMagnitude < 1e-4f)
                forward = Vector3.forward;
            forward.Normalize();
            _label.transform.SetPositionAndRotation(head.position + forward * distance + Vector3.down * drop,
                Quaternion.LookRotation(forward, Vector3.up));
        }
    }
}
