using System;
using UnityEngine;

namespace SpellGame.Networking
{
    /// <summary>
    /// Holds an Android <c>WifiManager.MulticastLock</c> so the Quest receives UDP broadcasts (architecture.md §4.1).
    /// Requires the CHANGE_WIFI_MULTICAST_STATE permission (added by QuestProjectConfigurator). No-op off-device.
    /// </summary>
    public sealed class AndroidMulticastLock : IDisposable
    {
        private readonly AndroidJavaObject _lock;

        private AndroidMulticastLock(AndroidJavaObject heldLock)
        {
            _lock = heldLock;
        }

        public static AndroidMulticastLock Acquire()
        {
            if (Application.platform != RuntimePlatform.Android)
                return new AndroidMulticastLock(null);

            using var unityPlayer = new AndroidJavaClass("com.unity3d.player.UnityPlayer");
            using var activity = unityPlayer.GetStatic<AndroidJavaObject>("currentActivity");
            using var wifiManager = activity.Call<AndroidJavaObject>("getSystemService", "wifi");
            var multicastLock = wifiManager.Call<AndroidJavaObject>("createMulticastLock", "spellgame-discovery");
            multicastLock.Call("acquire");
            return new AndroidMulticastLock(multicastLock);
        }

        public void Dispose()
        {
            if (_lock == null)
                return;

            _lock.Call("release");
            _lock.Dispose();
        }
    }
}
