using System;
using UnityEngine;
using UnityEngine.Rendering;
using Object = UnityEngine.Object;

namespace SpellGame.Game
{
    /// <summary>Fireball materials, created by <c>MainSceneBuilder</c> from <c>Assets/SpellGame/Fireball</c>.</summary>
    [Serializable]
    public sealed class FireballMaterials
    {
        [Tooltip("Opaque animated fire surface (SpellGame/Fireball/Core).")]
        public Material core;
        [Tooltip("Soft radial glow, also used for sparks and the trail ribbon (additive).")]
        public Material glow;
        [Tooltip("Billowing fire puffs for the trail and explosion (additive).")]
        public Material flame;
        [Tooltip("Rising flame tongues around the orb (additive).")]
        public Material tongue;
        [Tooltip("Dark smoke (premultiplied alpha).")]
        public Material smoke;
        [Tooltip("Expanding shockwave ring of the explosion (additive).")]
        public Material shockwave;
    }

    /// <summary>A fireball orb: an unscaled root carrying the particles, and the opaque core sphere under it.</summary>
    public sealed class FireballOrb
    {
        public Transform Root;
        public Transform Core;
    }

    /// <summary>
    /// Fireball effects: an opaque procedural-fire core sphere plus Shuriken particle layers (glow, flame tongues, embers,
    /// a flame and smoke trail, explosions). Particle textures are Kenney's CC0 Particle Pack (see Fireball/README.md).
    /// Everything is built in code, so effects need no prefabs; sizes are metres at a root scale of 1.
    /// </summary>
    public static class FireballVfx
    {
        private static readonly Color White = new(1f, 0.97f, 0.86f);
        private static readonly Color Yellow = new(1f, 0.8f, 0.28f);
        private static readonly Color Orange = new(1f, 0.45f, 0.06f);
        private static readonly Color Red = new(0.78f, 0.1f, 0.02f);
        private static readonly Color Soot = new(0.1f, 0.08f, 0.07f);

        private static readonly Gradient FireLife = MakeGradient(
            new[] { (0f, White), (0.15f, Yellow), (0.4f, Orange), (0.8f, Red) },
            new[] { (0f, 0f), (0.08f, 1f), (0.55f, 0.8f), (1f, 0f) });

        private static readonly Gradient GlowLife = MakeGradient(
            new[] { (0f, Yellow), (1f, Orange) },
            new[] { (0f, 0f), (0.35f, 0.7f), (1f, 0f) });

        private static readonly Gradient SparkLife = MakeGradient(
            new[] { (0f, White), (0.3f, Yellow), (0.7f, Orange), (1f, Red) },
            new[] { (0f, 1f), (0.6f, 1f), (1f, 0f) });

        private static readonly Gradient SmokeLife = MakeGradient(
            new[] { (0f, Soot), (1f, Soot) },
            new[] { (0f, 0f), (0.2f, 0.5f), (1f, 0f) });

        private static readonly Gradient FlashLife = MakeGradient(
            new[] { (0f, White), (1f, Yellow) },
            new[] { (0f, 1f), (1f, 0f) });

        private static readonly Gradient RingLife = MakeGradient(
            new[] { (0f, Yellow), (1f, Orange) },
            new[] { (0f, 0.9f), (1f, 0f) });

        private static readonly Gradient TrailLife = MakeGradient(
            new[] { (0f, Yellow), (0.4f, Orange), (1f, Red) },
            new[] { (0f, 0.9f), (1f, 0f) });

        private static readonly AnimationCurve FlickerSize = Curve(0f, 0.5f, 0.25f, 1f, 1f, 0.15f);
        private static readonly AnimationCurve PuffSize = Curve(0f, 0.4f, 0.3f, 1f, 1f, 0.8f);
        private static readonly AnimationCurve GrowSize = Curve(0f, 0.35f, 1f, 1f);
        private static readonly AnimationCurve RingSize = new(new Keyframe(0f, 0.15f, 3f, 3f), new Keyframe(1f, 1f, 0f, 0f));

        // ---- Persistent orbs -------------------------------------------------------------------------------------

        /// <summary>The fireball held on the caster's hand: core, glow, rising flame tongues and a few embers.</summary>
        public static FireballOrb CreateHeldOrb(string name, Transform parent, FireballMaterials materials, float diameter)
        {
            var orb = CreateOrbRoot(name, parent, materials, diameter, parent.position);
            AddGlow(orb.Root, materials.glow, diameter * 2.6f, rate: 14f);
            AddTongues(orb.Root, materials.tongue, diameter, rate: 40f);
            AddEmbers(orb.Root, materials.glow, diameter, rate: 10f);
            return orb;
        }

        /// <summary>A thrown fireball: core and glow plus a flame/smoke trail and a glowing ribbon behind it.</summary>
        public static FireballOrb CreateProjectile(string name, Transform parent, FireballMaterials materials, float diameter, Vector3 position)
        {
            // The root starts at its spawn position so distance-based trail emission doesn't streak from the origin.
            var orb = CreateOrbRoot(name, parent, materials, diameter, position);
            AddGlow(orb.Root, materials.glow, diameter * 2.8f, rate: 20f);
            AddFlameTrail(orb.Root, materials.flame, diameter);
            AddSmokeTrail(orb.Root, materials.smoke, diameter);
            AddEmbers(orb.Root, materials.glow, diameter, rate: 25f);
            AddRibbon(orb.Root, materials.glow, diameter);
            return orb;
        }

        /// <summary>A glowing coal for the cooldown. Scale the returned root to its diameter; all layers scale with it.</summary>
        public static Transform CreateEmber(string name, Transform parent, FireballMaterials materials)
        {
            var root = new GameObject(name).transform;
            root.SetParent(parent, false);
            SpellVfx.CreateOrb("Core", root, materials.core, 1f);
            AddGlow(root, materials.glow, 3.5f, rate: 10f);
            return root;
        }

        /// <summary>
        /// Destroy an orb, letting its world-space particles (the trail) finish their lifetime instead of vanishing.
        /// </summary>
        public static void Release(FireballOrb orb)
        {
            foreach (var particles in orb.Root.GetComponentsInChildren<ParticleSystem>())
            {
                var main = particles.main;
                if (main.simulationSpace != ParticleSystemSimulationSpace.World)
                    continue;
                particles.transform.SetParent(null, true);
                particles.Stop(true, ParticleSystemStopBehavior.StopEmitting);
                Object.Destroy(particles.gameObject, main.startLifetime.constantMax + 0.1f);
            }
            Object.Destroy(orb.Root.gameObject);
        }

        // ---- One-shot effects ------------------------------------------------------------------------------------

        /// <summary>Snap: a flash, a spark burst and a lick of flame where the fireball appears.</summary>
        public static void Ignite(Vector3 at, FireballMaterials materials)
        {
            var root = OneShotRoot("Fireball Ignite", at);
            Emit(root, "Flash", materials.glow, count: 1, lifetime: (0.12f, 0.15f), speed: (0f, 0f), size: (0.35f, 0.35f), color: FlashLife);
            Emit(root, "Ring", materials.shockwave, count: 1, lifetime: (0.2f, 0.2f), speed: (0f, 0f), size: (0.4f, 0.4f), color: RingLife, sizeCurve: RingSize);
            var sparks = Emit(root, "Sparks", materials.glow, count: 20, lifetime: (0.2f, 0.4f), speed: (1.2f, 2.8f), size: (0.008f, 0.014f), color: SparkLife);
            Stretch(sparks, 0.04f);
            Emit(root, "Flames", materials.flame, count: 8, lifetime: (0.25f, 0.4f), speed: (0.3f, 0.8f), size: (0.06f, 0.12f), color: FireLife, sizeCurve: PuffSize, drag: 3f);
            Finish(root, 0.5f);
        }

        /// <summary>Throw: a puff of flame and sparks left behind at the release point.</summary>
        public static void Launch(Vector3 at, FireballMaterials materials)
        {
            var root = OneShotRoot("Fireball Launch", at);
            Emit(root, "Flash", materials.glow, count: 1, lifetime: (0.1f, 0.12f), speed: (0f, 0f), size: (0.3f, 0.3f), color: FlashLife);
            Emit(root, "Flames", materials.flame, count: 10, lifetime: (0.25f, 0.4f), speed: (0.4f, 1.2f), size: (0.08f, 0.16f), color: FireLife, sizeCurve: PuffSize, drag: 3f);
            var sparks = Emit(root, "Sparks", materials.glow, count: 14, lifetime: (0.2f, 0.4f), speed: (1f, 2.5f), size: (0.008f, 0.014f), color: SparkLife);
            Stretch(sparks, 0.04f);
            Finish(root, 0.5f);
        }

        /// <summary>Hit: white flash, shockwave ring, billowing fire, flying sparks and a lingering smoke cloud.</summary>
        public static void Explosion(Vector3 at, FireballMaterials materials, float scale)
        {
            var root = OneShotRoot("Fireball Explosion", at);
            Emit(root, "Flash", materials.glow, count: 2, lifetime: (0.12f, 0.16f), speed: (0f, 0f), size: (0.9f * scale, 0.9f * scale), color: FlashLife, sizeCurve: Curve(0f, 0.6f, 0.3f, 1f, 1f, 0.9f));
            Emit(root, "Ring", materials.shockwave, count: 1, lifetime: (0.3f, 0.3f), speed: (0f, 0f), size: (1.4f * scale, 1.4f * scale), color: RingLife, sizeCurve: RingSize);
            var fire = Emit(root, "Fire", materials.flame, count: 22, lifetime: (0.35f, 0.6f), speed: (1f * scale, 3f * scale), size: (0.15f * scale, 0.3f * scale), color: FireLife, sizeCurve: PuffSize, drag: 4f, radius: 0.05f * scale);
            Spin(fire);
            var sparks = Emit(root, "Sparks", materials.glow, count: 36, lifetime: (0.3f, 0.7f), speed: (3f * scale, 7f * scale), size: (0.012f * scale, 0.025f * scale), color: SparkLife, drag: 1f, gravity: 0.5f);
            Stretch(sparks, 0.035f);
            var smoke = Emit(root, "Smoke", materials.smoke, count: 10, lifetime: (0.8f, 1.3f), speed: (0.3f * scale, 1f * scale), size: (0.35f * scale, 0.6f * scale), color: SmokeLife, sizeCurve: GrowSize, drag: 2f, gravity: -0.08f, delay: 0.08f, radius: 0.08f * scale);
            BehindFire(smoke);
            Spin(smoke);
            Finish(root, 1.5f);
        }

        /// <summary>Fizzle (held fireball timed out, or a projectile expired): smoke, dying embers and a last lick of flame.</summary>
        public static void Fizzle(Vector3 at, FireballMaterials materials, float scale)
        {
            var root = OneShotRoot("Fireball Fizzle", at);
            Emit(root, "Flames", materials.flame, count: 5, lifetime: (0.2f, 0.35f), speed: (0.1f, 0.4f), size: (0.08f * scale, 0.14f * scale), color: FireLife, sizeCurve: FlickerSize);
            var embers = Emit(root, "Embers", materials.glow, count: 14, lifetime: (0.3f, 0.6f), speed: (0.5f, 1.5f), size: (0.008f, 0.014f), color: SparkLife, gravity: 0.4f);
            Stretch(embers, 0.04f);
            var smoke = Emit(root, "Smoke", materials.smoke, count: 8, lifetime: (0.7f, 1.1f), speed: (0.2f, 0.5f), size: (0.12f * scale, 0.22f * scale), color: SmokeLife, sizeCurve: GrowSize, drag: 1.5f, gravity: -0.1f);
            BehindFire(smoke);
            Spin(smoke);
            Finish(root, 1.2f);
        }

        // ---- Orb layers ------------------------------------------------------------------------------------------

        private static FireballOrb CreateOrbRoot(string name, Transform parent, FireballMaterials materials, float diameter, Vector3 position)
        {
            var root = new GameObject(name).transform;
            root.SetParent(parent, false);
            root.position = position;
            var core = SpellVfx.CreateOrb("Core", root, materials.core, diameter);
            return new FireballOrb { Root = root, Core = core };
        }

        /// <summary>Flickering halo that follows the orb (local space), so it reads from across the room.</summary>
        private static void AddGlow(Transform root, Material material, float size, float rate)
        {
            var glow = CreateSystem("Glow", root, material, loop: true, ParticleSystemSimulationSpace.Local, maxParticles: 10);
            var main = glow.main;
            main.startLifetime = new ParticleSystem.MinMaxCurve(0.2f, 0.3f);
            main.startSpeed = 0f;
            main.startSize = new ParticleSystem.MinMaxCurve(size * 0.85f, size * 1.1f);
            var emission = glow.emission;
            emission.rateOverTime = rate;
            ColorOverLife(glow, GlowLife);
            glow.Play();
        }

        /// <summary>Flame tongues licking upward off the orb's surface (world space, so they stream as the hand moves).</summary>
        private static void AddTongues(Transform root, Material material, float diameter, float rate)
        {
            var tongues = CreateSystem("Flame Tongues", root, material, loop: true, ParticleSystemSimulationSpace.World, maxParticles: 64);
            var main = tongues.main;
            main.startLifetime = new ParticleSystem.MinMaxCurve(0.25f, 0.45f);
            main.startSpeed = new ParticleSystem.MinMaxCurve(0.05f, 0.15f);
            main.startSize = new ParticleSystem.MinMaxCurve(diameter * 0.55f, diameter * 0.9f);
            main.startRotation = new ParticleSystem.MinMaxCurve(-0.25f, 0.25f);
            main.gravityModifier = -0.35f;
            var emission = tongues.emission;
            emission.rateOverTime = rate;
            var shape = tongues.shape;
            shape.radius = diameter * 0.35f;
            ColorOverLife(tongues, FireLife);
            SizeOverLife(tongues, FlickerSize);
            tongues.Play();
        }

        private static void AddEmbers(Transform root, Material material, float diameter, float rate)
        {
            var embers = CreateSystem("Embers", root, material, loop: true, ParticleSystemSimulationSpace.World, maxParticles: 32);
            var main = embers.main;
            main.startLifetime = new ParticleSystem.MinMaxCurve(0.4f, 0.8f);
            main.startSpeed = new ParticleSystem.MinMaxCurve(0.2f, 0.6f);
            main.startSize = new ParticleSystem.MinMaxCurve(0.008f, 0.016f);
            main.gravityModifier = -0.15f;
            var emission = embers.emission;
            emission.rateOverTime = rate;
            var shape = embers.shape;
            shape.radius = diameter * 0.45f;
            ColorOverLife(embers, SparkLife);
            Stretch(embers, 0.05f);
            embers.Play();
        }

        /// <summary>Fire puffs dropped along the flight path (per metre, so the trail stays dense at any speed).</summary>
        private static void AddFlameTrail(Transform root, Material material, float diameter)
        {
            var trail = CreateSystem("Flame Trail", root, material, loop: true, ParticleSystemSimulationSpace.World, maxParticles: 160);
            var main = trail.main;
            main.startLifetime = new ParticleSystem.MinMaxCurve(0.22f, 0.38f);
            main.startSpeed = new ParticleSystem.MinMaxCurve(0f, 0.2f);
            main.startSize = new ParticleSystem.MinMaxCurve(diameter * 0.9f, diameter * 1.5f);
            main.startRotation = new ParticleSystem.MinMaxCurve(-Mathf.PI, Mathf.PI);
            main.gravityModifier = -0.1f;
            var emission = trail.emission;
            emission.rateOverTime = 30f;
            emission.rateOverDistance = 45f;
            var shape = trail.shape;
            shape.radius = diameter * 0.3f;
            ColorOverLife(trail, FireLife);
            SizeOverLife(trail, Curve(0f, 0.6f, 0.2f, 1f, 1f, 0.35f));
            Spin(trail);
            trail.Play();
        }

        private static void AddSmokeTrail(Transform root, Material material, float diameter)
        {
            var smoke = CreateSystem("Smoke Trail", root, material, loop: true, ParticleSystemSimulationSpace.World, maxParticles: 48);
            var main = smoke.main;
            main.startLifetime = new ParticleSystem.MinMaxCurve(0.5f, 0.8f);
            main.startSpeed = new ParticleSystem.MinMaxCurve(0f, 0.1f);
            main.startSize = new ParticleSystem.MinMaxCurve(diameter * 1.2f, diameter * 1.8f);
            main.startRotation = new ParticleSystem.MinMaxCurve(-Mathf.PI, Mathf.PI);
            main.gravityModifier = -0.05f;
            var emission = smoke.emission;
            emission.rateOverTime = 0f;
            emission.rateOverDistance = 8f;
            var shape = smoke.shape;
            shape.radius = diameter * 0.3f;
            ColorOverLife(smoke, SmokeLife);
            SizeOverLife(smoke, GrowSize, 1.6f);
            BehindFire(smoke);
            Spin(smoke);
            smoke.Play();
        }

        /// <summary>A short glowing ribbon behind the projectile: the brightest, most continuous cue of its path.</summary>
        private static void AddRibbon(Transform root, Material material, float diameter)
        {
            var ribbon = root.gameObject.AddComponent<TrailRenderer>();
            ribbon.sharedMaterial = material;
            ribbon.time = 0.12f;
            ribbon.widthMultiplier = diameter * 1.1f;
            ribbon.widthCurve = AnimationCurve.Linear(0f, 1f, 1f, 0f);
            ribbon.colorGradient = TrailLife;
            ribbon.minVertexDistance = 0.03f;
            ribbon.numCapVertices = 2;
            ribbon.alignment = LineAlignment.View;
            ribbon.textureMode = LineTextureMode.Stretch;
            ribbon.shadowCastingMode = ShadowCastingMode.Off;
            ribbon.receiveShadows = false;
        }

        // ---- Particle helpers ------------------------------------------------------------------------------------

        private static Transform OneShotRoot(string name, Vector3 at)
        {
            var root = new GameObject(name).transform;
            root.position = at;
            return root;
        }

        private static void Finish(Transform root, float lifetime)
        {
            foreach (var particles in root.GetComponentsInChildren<ParticleSystem>())
                particles.Play(false);
            Object.Destroy(root.gameObject, lifetime);
        }

        private static ParticleSystem Emit(
            Transform root,
            string name,
            Material material,
            int count,
            (float min, float max) lifetime,
            (float min, float max) speed,
            (float min, float max) size,
            Gradient color,
            AnimationCurve sizeCurve = null,
            float drag = 0f,
            float gravity = 0f,
            float delay = 0f,
            float radius = 0.02f)
        {
            var particles = CreateSystem(name, root, material, loop: false, ParticleSystemSimulationSpace.World, maxParticles: count);
            var main = particles.main;
            main.duration = delay + lifetime.max;
            main.startLifetime = new ParticleSystem.MinMaxCurve(lifetime.min, lifetime.max);
            main.startSpeed = new ParticleSystem.MinMaxCurve(speed.min, speed.max);
            main.startSize = new ParticleSystem.MinMaxCurve(size.min, size.max);
            main.startRotation = new ParticleSystem.MinMaxCurve(-Mathf.PI, Mathf.PI);
            main.gravityModifier = gravity;

            var emission = particles.emission;
            emission.rateOverTime = 0f;
            emission.SetBursts(new[] { new ParticleSystem.Burst(delay, (short)count) });

            var shape = particles.shape;
            shape.radius = radius;

            ColorOverLife(particles, color);
            if (sizeCurve != null)
                SizeOverLife(particles, sizeCurve);

            if (drag > 0f)
            {
                var limit = particles.limitVelocityOverLifetime;
                limit.enabled = true;
                limit.limit = 100f;
                limit.drag = drag;
                limit.multiplyDragByParticleSize = false;
                limit.multiplyDragByParticleVelocity = false;
            }
            return particles;
        }

        private static ParticleSystem CreateSystem(string name, Transform parent, Material material, bool loop, ParticleSystemSimulationSpace space, int maxParticles)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            var particles = go.AddComponent<ParticleSystem>();
            particles.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);

            var main = particles.main;
            main.loop = loop;
            // Looping layers restart by themselves when a pooled orb is re-activated.
            main.playOnAwake = loop;
            main.simulationSpace = space;
            main.scalingMode = ParticleSystemScalingMode.Hierarchy;
            main.maxParticles = maxParticles;
            main.startColor = Color.white;

            var shape = particles.shape;
            shape.enabled = true;
            shape.shapeType = ParticleSystemShapeType.Sphere;
            shape.radius = 0.01f;
            shape.radiusThickness = 1f;

            var renderer = go.GetComponent<ParticleSystemRenderer>();
            renderer.renderMode = ParticleSystemRenderMode.Billboard;
            renderer.sharedMaterial = material;
            renderer.maxParticleSize = 1f;
            renderer.shadowCastingMode = ShadowCastingMode.Off;
            renderer.receiveShadows = false;
            renderer.lightProbeUsage = LightProbeUsage.Off;
            renderer.reflectionProbeUsage = ReflectionProbeUsage.Off;
            return particles;
        }

        private static void ColorOverLife(ParticleSystem particles, Gradient gradient)
        {
            var color = particles.colorOverLifetime;
            color.enabled = true;
            color.color = new ParticleSystem.MinMaxGradient(gradient);
        }

        private static void SizeOverLife(ParticleSystem particles, AnimationCurve curve, float multiplier = 1f)
        {
            var size = particles.sizeOverLifetime;
            size.enabled = true;
            size.size = new ParticleSystem.MinMaxCurve(multiplier, curve);
        }

        private static void Spin(ParticleSystem particles)
        {
            var rotation = particles.rotationOverLifetime;
            rotation.enabled = true;
            rotation.z = new ParticleSystem.MinMaxCurve(-2.5f, 2.5f);
        }

        /// <summary>Velocity-stretched billboards, for sparks and embers.</summary>
        private static void Stretch(ParticleSystem particles, float velocityScale)
        {
            var renderer = particles.GetComponent<ParticleSystemRenderer>();
            renderer.renderMode = ParticleSystemRenderMode.Stretch;
            renderer.velocityScale = velocityScale;
            renderer.lengthScale = 1.5f;
        }

        /// <summary>Smoke is alpha-blended, so draw it before (behind) the additive fire layers.</summary>
        private static void BehindFire(ParticleSystem particles) =>
            particles.GetComponent<ParticleSystemRenderer>().sortingFudge = 20f;

        private static Gradient MakeGradient((float time, Color color)[] colors, (float time, float alpha)[] alphas)
        {
            var gradient = new Gradient();
            gradient.SetKeys(
                Array.ConvertAll(colors, key => new GradientColorKey(key.color, key.time)),
                Array.ConvertAll(alphas, key => new GradientAlphaKey(key.alpha, key.time)));
            return gradient;
        }

        /// <summary>Curve from (time, value) pairs.</summary>
        private static AnimationCurve Curve(params float[] timeValuePairs)
        {
            var keys = new Keyframe[timeValuePairs.Length / 2];
            for (var i = 0; i < keys.Length; i++)
                keys[i] = new Keyframe(timeValuePairs[2 * i], timeValuePairs[2 * i + 1]);
            return new AnimationCurve(keys);
        }
    }
}
