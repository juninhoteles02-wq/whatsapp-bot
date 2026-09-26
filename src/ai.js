// Ponte entre as ferramentas (tools.js / ownerTools.js) e o modelo de IA.
// Hoje usa a OpenAI (chat.completions com "tools"), porque foi o crédito
// disponível no começo do projeto. Para trocar para o Claude depois, troque
// só este arquivo: a Anthropic tem o mesmo conceito de "tools" na Messages
// API, só muda o formato da chamada e da resposta.

const OpenAI = require("openai");
const { env } = require("./config");

const client = new OpenAI({ apiKey: env.openaiKey });

function toOpenAiTools(tools) {
  return tools.map((t) => ({
    type: "function",
    function: { name: t.name, description: t.description, parameters: t.parameters || { type: "object", properties: {} } },
  }));
}

// history: [{role: "user"|"assistant", content: "..."}]  (sem o system prompt)
// tools: array vindo de buildTools()/buildOwnerTools(), cada um com .execute(args)
async function runConversation({ systemPrompt, history, tools, maxRounds = 6 }) {
  const toolByName = new Map(tools.map((t) => [t.name, t]));
  const messages = [{ role: "system", content: systemPrompt }, ...history];

  for (let round = 0; round < maxRounds; round++) {
    const res = await client.chat.completions.create({
      model: env.openaiModel,
      messages,
      tools: toOpenAiTools(tools),
    });
    const msg = res.choices[0].message;
    messages.push(msg);

    if (!msg.tool_calls || msg.tool_calls.length === 0) {
      return { text: (msg.content || "").trim(), messages: messages.slice(1) };
    }

    for (const call of msg.tool_calls) {
      const tool = toolByName.get(call.function.name);
      let result;
      if (!tool) {
        result = { error: `Ferramenta desconhecida: ${call.function.name}` };
      } else {
        try {
          const args = call.function.arguments ? JSON.parse(call.function.arguments) : {};
          result = await tool.execute(args);
        } catch (err) {
          result = { error: err.message || String(err) };
        }
      }
      messages.push({ role: "tool", tool_call_id: call.id, content: JSON.stringify(result) });
    }
  }
  return { text: "Desculpa, não consegui terminar agora. Pode repetir sua última mensagem?", messages: messages.slice(1) };
}

module.exports = { runConversation };
