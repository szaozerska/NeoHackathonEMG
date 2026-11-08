namespace SpellGame.Game
{
    /// <summary>Where <see cref="GameClient"/> is in finding and joining the server.</summary>
    public enum ConnectionState
    {
        Searching,
        Connecting,
        Connected,
        Cancelled,
        Unreachable,
        Disconnected,
    }
}
