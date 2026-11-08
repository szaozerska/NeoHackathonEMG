using System;
using System.Collections.Generic;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Newtonsoft.Json.Serialization;

namespace SpellGame.Protocol
{
    /// <summary>Newline-delimited JSON framing (architecture.md §4): one message per line.</summary>
    public static class MessageCodec
    {
        private static readonly JsonSerializerSettings Settings = new()
        {
            ContractResolver = new DefaultContractResolver { NamingStrategy = new SnakeCaseNamingStrategy() },
            NullValueHandling = NullValueHandling.Include,
            Formatting = Formatting.None,
        };

        private static readonly JsonSerializer Serializer = JsonSerializer.Create(Settings);

        private static readonly Dictionary<string, Type> InboundTypes = new()
        {
            [WelcomeMessage.TypeName] = typeof(WelcomeMessage),
            [ErrorMessage.TypeName] = typeof(ErrorMessage),
            [PairStartMessage.TypeName] = typeof(PairStartMessage),
            [PairPromptMessage.TypeName] = typeof(PairPromptMessage),
            [PairedMessage.TypeName] = typeof(PairedMessage),
            [SpaceMessage.TypeName] = typeof(SpaceMessage),
            [PoseMessage.TypeName] = typeof(PoseMessage),
            [SignMessage.TypeName] = typeof(SignMessage),
            [SpellMessage.TypeName] = typeof(SpellMessage),
            [DamageMessage.TypeName] = typeof(DamageMessage),
            [ImpactMessage.TypeName] = typeof(ImpactMessage),
            [StateMessage.TypeName] = typeof(StateMessage),
        };

        public static string Encode(Message message) => JsonConvert.SerializeObject(message, Settings);

        /// <summary>Returns null for message types this client doesn't know yet, so newer servers don't break it.</summary>
        public static Message Decode(string line)
        {
            var json = JObject.Parse(line);
            var typeName = json.Value<string>("type");
            return typeName != null && InboundTypes.TryGetValue(typeName, out var type)
                ? (Message)json.ToObject(type, Serializer)
                : null;
        }
    }
}
