using System.Collections.Generic;
using System.Linq;
using SpellGame.Protocol;
using UnityEngine;

namespace SpellGame.Game
{
    /// <summary>
    /// The solo-match AI opponent as an animated wizard (Quaternius "Animated Wizard", Characters/Wizard). It stands where
    /// the AI's joints say, faces the way its shoulders face, is scaled to its height, and plays the model's own
    /// animations from what the server reports rather than bending bones to the joints:
    /// idle / walk while strafing, a spell cast on its fireball wind-up, a guard pose while its shield is up, a flinch
    /// (and red tint) when hit, death on a KO and a victory cast when it wins. Unlit, like the rest of the game, with a
    /// glowing orb on its staff.
    /// </summary>
    public sealed class AiWizardView : MonoBehaviour
    {
        public const string Idle = "Idle";
        public const string Walk = "Walk";
        public const string Cast = "Spell1";
        public const string Victory = "Spell2";
        public const string Guard = "Idle_Attacking";
        public const string Hit = "RecieveHit";
        public const string Death = "Death";

        /// <summary>Animator states <see cref="MainSceneBuilder"/> creates, named after the model's clips.</summary>
        public static readonly string[] States = { Idle, Walk, Cast, Victory, Guard, Hit, Death };

        /// <summary>Clips that loop; the rest play once.</summary>
        public static readonly string[] LoopingStates = { Idle, Walk, Victory, Guard };

        [SerializeField] private GameClient gameClient;
        [SerializeField] private GameObject wizardModel;
        [SerializeField] private RuntimeAnimatorController animatorController;
        [Tooltip("Unlit material with the wizard texture; each renderer gets an instance so hits can tint it.")]
        [SerializeField] private Material bodyMaterial;
        [SerializeField] private Material glowMaterial;

        [Tooltip("Model yaw relative to the AI's facing, if the model's front isn't +z.")]
        [SerializeField] private float yawOffset;
        [Tooltip("Head top above the AI's head joint, in metres.")]
        [SerializeField] private float headroom = 0.15f;
        [SerializeField] private float crossFade = 0.15f;
        [Tooltip("Hip speed (m/s) above which it walks.")]
        [SerializeField] private float walkSpeed = 0.3f;
        [SerializeField] private float hitFlashSeconds = 0.25f;

        private static readonly Dictionary<string, float> OneShotSeconds = new()
        {
            [Cast] = 1.2f,
            [Hit] = 0.6f,
        };

        private static readonly Color HitTint = new(1f, 0.35f, 0.3f);

        private string _aiId;
        private bool _present;
        private float _hp = 1f;
        private string _item;
        private bool _won;

        private Transform _root;
        private Transform _model;
        private Animator _animator;
        private Material[] _materials;
        private Renderer _staff;
        private Transform _staffOrb;
        private float _modelHeight = 1f;

        private string _state;
        private float _oneShotUntil;
        private float _hitAt = float.NegativeInfinity;
        private Vector3 _lastHips;
        private float _speed;

        private void Awake()
        {
            _root = new GameObject("AI Wizard").transform;
            _root.SetParent(transform, false);
            _model = Instantiate(wizardModel, _root).transform;
            _model.localPosition = Vector3.zero;
            _model.localRotation = Quaternion.Euler(0f, yawOffset, 0f);

            _animator = _model.GetComponentInChildren<Animator>() ?? _model.gameObject.AddComponent<Animator>();
            _animator.runtimeAnimatorController = animatorController;
            _animator.applyRootMotion = false;
            _animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;

            var renderers = _model.GetComponentsInChildren<Renderer>();
            _materials = new Material[renderers.Length];
            for (var i = 0; i < renderers.Length; i++)
            {
                _materials[i] = new Material(bodyMaterial);
                renderers[i].sharedMaterial = _materials[i];
                renderers[i].shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
                renderers[i].receiveShadows = false;
                if (renderers[i] is SkinnedMeshRenderer skinned)
                    skinned.updateWhenOffscreen = true;
            }
            _staff = renderers.FirstOrDefault(r => r.name.Contains("Staff"));
            _staffOrb = SpellVfx.CreateOrb("Staff Orb", _root, glowMaterial, 0.07f);
            SpellVfx.AddFlames(_staffOrb, glowMaterial, 15f);

            var bounds = new Bounds(_model.position, Vector3.zero);
            foreach (var renderer in renderers)
                bounds.Encapsulate(renderer.bounds);
            _modelHeight = Mathf.Max(0.1f, bounds.max.y - _model.position.y);
            _root.gameObject.SetActive(false);
        }

        private void OnEnable()
        {
            gameClient.StateReceived += OnState;
            gameClient.SpellReceived += OnSpell;
            gameClient.DamageReceived += OnDamage;
        }

        private void OnDisable()
        {
            gameClient.StateReceived -= OnState;
            gameClient.SpellReceived -= OnSpell;
            gameClient.DamageReceived -= OnDamage;
        }

        private void OnState(StateMessage state)
        {
            _aiId = state.Match?.AiId;
            var ai = _aiId == null ? null : state.Players.FirstOrDefault(p => p.PlayerId == _aiId);
            _present = ai != null;
            _hp = ai?.Hp ?? 1f;
            _item = ai?.Item;
            _won = state.Match?.Phase == MatchPhase.Ended && state.Match.Winner == _aiId;
        }

        private void OnSpell(SpellMessage spell)
        {
            if (spell.CasterId == _aiId && spell.Spell == SpellKind.Fireball && spell.State == SpellState.Charging)
                PlayOnce(Cast);
        }

        private void OnDamage(DamageMessage damage)
        {
            if (damage.TargetId == null || damage.TargetId != _aiId)
                return;
            _hitAt = Time.time;
            if (damage.HpAfter > 0f)
                PlayOnce(Hit);
        }

        private void Update()
        {
            BodyJoints joints = null;
            var visible = _present && gameClient.TryGetJoints(_aiId, out joints) && joints?.Head != null && joints.Hips != null;
            if (_root.gameObject.activeSelf != visible)
            {
                _root.gameObject.SetActive(visible);
                _state = null;
            }
            if (!visible)
                return;

            Place(joints);
            Animate();

            var hit = Mathf.Clamp01(1f - (Time.time - _hitAt) / hitFlashSeconds);
            var tint = Color.Lerp(Color.white, HitTint, hit);
            foreach (var material in _materials)
                material.SetColor("_BaseColor", tint);
            if (_staff != null)
                _staffOrb.position = new Vector3(_staff.bounds.center.x, _staff.bounds.max.y, _staff.bounds.center.z);
        }

        private void Place(BodyJoints j)
        {
            var hips = j.Hips.Position;
            var right = j.LShoulder != null && j.RShoulder != null ? j.RShoulder.Position - j.LShoulder.Position : Vector3.right;
            right.y = 0f;
            if (right.sqrMagnitude < 1e-4f)
                right = Vector3.right;
            var forward = Vector3.Cross(right.normalized, Vector3.up);
            _root.SetPositionAndRotation(new Vector3(hips.x, 0f, hips.z), Quaternion.LookRotation(forward, Vector3.up));
            _root.localScale = Vector3.one * ((j.Head.Position.y + headroom) / _modelHeight);

            var flat = new Vector3(hips.x, 0f, hips.z);
            if (Time.deltaTime > 0f)
                _speed = Mathf.Lerp(_speed, (flat - _lastHips).magnitude / Time.deltaTime, 0.2f);
            _lastHips = flat;
        }

        private void Animate()
        {
            if (_hp <= 0f)
            {
                CrossFade(Death);
                return;
            }
            if (Time.time < _oneShotUntil)
                return;

            var loop = _won ? Victory
                : _item == SpellKind.Shield ? Guard
                : _speed > walkSpeed ? Walk
                : Idle;
            CrossFade(loop);
        }

        private void PlayOnce(string state)
        {
            if (_hp <= 0f || !_root.gameObject.activeInHierarchy)
                return;
            _animator.CrossFadeInFixedTime(state, crossFade, 0, 0f);
            _state = state;
            _oneShotUntil = Time.time + OneShotSeconds[state];
        }

        private void CrossFade(string state)
        {
            if (_state == state)
                return;
            _state = state;
            _animator.CrossFadeInFixedTime(state, crossFade);
        }
    }
}
