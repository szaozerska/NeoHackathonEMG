using UnityEngine;
using UnityEngine.Rendering;

namespace SpellGame.Game
{
    /// <summary>
    /// Procedural spell visuals built from primitives and particle systems, so spells need no art assets yet.
    /// Particles render as small opaque spheres: the unlit materials ignore vertex color, and opaque output keeps
    /// passthrough alpha correct.
    /// </summary>
    public static class SpellVfx
    {
        private static Mesh _sphereMesh;
        private static Mesh _capsuleMesh;

        private static Mesh SphereMesh => _sphereMesh ??= PrimitiveMesh(PrimitiveType.Sphere);

        /// <summary>Unity's capsule: 2 m tall along +y, 1 m wide.</summary>
        private static Mesh CapsuleMesh => _capsuleMesh ??= PrimitiveMesh(PrimitiveType.Capsule);

        private static Mesh PrimitiveMesh(PrimitiveType type)
        {
            var primitive = GameObject.CreatePrimitive(type);
            var mesh = primitive.GetComponent<MeshFilter>().sharedMesh;
            Object.Destroy(primitive);
            return mesh;
        }

        public static Transform CreateOrb(string name, Transform parent, Material material, float diameter)
        {
            var orb = CreateMesh(name, parent, material, SphereMesh);
            orb.localScale = Vector3.one * diameter;
            return orb;
        }

        /// <summary>A capsule to be placed with <see cref="PlaceBlade"/>.</summary>
        public static Transform CreateBlade(string name, Transform parent, Material material) =>
            CreateMesh(name, parent, material, CapsuleMesh);

        /// <summary>Stretch a <see cref="CreateBlade"/> capsule from <paramref name="hilt"/> to <paramref name="tip"/>.</summary>
        public static void PlaceBlade(Transform blade, Vector3 hilt, Vector3 tip, float width)
        {
            var along = tip - hilt;
            blade.position = (hilt + tip) * 0.5f;
            blade.rotation = Quaternion.FromToRotation(Vector3.up, along);
            blade.localScale = new Vector3(width, along.magnitude * 0.5f, width);
        }

        private static Transform CreateMesh(string name, Transform parent, Material material, Mesh mesh)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            go.AddComponent<MeshFilter>().sharedMesh = mesh;
            var renderer = go.AddComponent<MeshRenderer>();
            renderer.sharedMaterial = material;
            renderer.shadowCastingMode = ShadowCastingMode.Off;
            renderer.receiveShadows = false;
            return go.transform;
        }

        /// <summary>Continuous embers rising off an orb; parented so they follow it.</summary>
        public static ParticleSystem AddFlames(Transform orb, Material material, float rate)
        {
            var flames = CreateParticles("Flames", orb, material);
            var main = flames.main;
            main.loop = true;
            main.startLifetime = new ParticleSystem.MinMaxCurve(0.2f, 0.4f);
            main.startSpeed = new ParticleSystem.MinMaxCurve(0.2f, 0.6f);
            main.startSize = new ParticleSystem.MinMaxCurve(0.015f, 0.035f);
            main.gravityModifier = -0.3f;
            var emission = flames.emission;
            emission.rateOverTime = rate;
            var shape = flames.shape;
            shape.shapeType = ParticleSystemShapeType.Sphere;
            shape.radius = 0.5f;
            flames.Play();
            return flames;
        }

        /// <summary>One-shot burst at a world position that destroys itself when done.</summary>
        public static void Burst(Vector3 position, Material material, int count, float speed, float size, float lifetime)
        {
            var root = new GameObject("Burst");
            root.transform.position = position;
            var burst = CreateParticles("Particles", root.transform, material);
            var main = burst.main;
            main.loop = false;
            main.duration = lifetime;
            main.startLifetime = new ParticleSystem.MinMaxCurve(lifetime * 0.5f, lifetime);
            main.startSpeed = new ParticleSystem.MinMaxCurve(speed * 0.3f, speed);
            main.startSize = new ParticleSystem.MinMaxCurve(size * 0.5f, size);
            var emission = burst.emission;
            emission.rateOverTime = 0f;
            emission.SetBursts(new[] { new ParticleSystem.Burst(0f, (short)count) });
            var shape = burst.shape;
            shape.shapeType = ParticleSystemShapeType.Sphere;
            shape.radius = 0.02f;
            burst.Play();
            Object.Destroy(root, lifetime + 0.1f);
        }

        public static TrailRenderer AddTrail(Transform orb, Material material, float width, float time)
        {
            var trail = orb.gameObject.AddComponent<TrailRenderer>();
            trail.sharedMaterial = material;
            trail.time = time;
            trail.widthCurve = AnimationCurve.Linear(0f, width, 1f, 0f);
            trail.minVertexDistance = 0.02f;
            trail.shadowCastingMode = ShadowCastingMode.Off;
            trail.receiveShadows = false;
            return trail;
        }

        private static ParticleSystem CreateParticles(string name, Transform parent, Material material)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            var particles = go.AddComponent<ParticleSystem>();
            particles.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);

            var main = particles.main;
            main.playOnAwake = false;
            main.simulationSpace = ParticleSystemSimulationSpace.World;
            main.scalingMode = ParticleSystemScalingMode.Shape;
            main.maxParticles = 200;

            var sizeOverLifetime = particles.sizeOverLifetime;
            sizeOverLifetime.enabled = true;
            sizeOverLifetime.size = new ParticleSystem.MinMaxCurve(1f, AnimationCurve.Linear(0f, 1f, 1f, 0f));

            var renderer = go.GetComponent<ParticleSystemRenderer>();
            renderer.renderMode = ParticleSystemRenderMode.Mesh;
            renderer.mesh = SphereMesh;
            renderer.sharedMaterial = material;
            renderer.shadowCastingMode = ShadowCastingMode.Off;
            renderer.receiveShadows = false;
            return particles;
        }
    }
}
