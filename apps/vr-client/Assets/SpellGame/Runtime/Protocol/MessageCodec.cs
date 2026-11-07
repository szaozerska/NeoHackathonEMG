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
            [PoseMessage.TypeName] = typeof(PoseMessage),
            [SignMessage.TypeName] = typeof(SignMessage),
            [SpellMessage.TypeName] = typeof(SpellMessage),
            [DamageMessage.TypeName] = typeof(DamageMessage),
        };

        public static string Encode(Message message) => JsonConvert.SerializeObject(message, Settings);

        public static Message Decode(string line)
        {
            var json = JObject.Parse(line);
            var typeName = json.Value<string>("type");
            return (Message)json.ToObject(InboundTypes[typeName], Serializer);
        }
    }
}
