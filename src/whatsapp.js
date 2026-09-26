const { env } = require("./config");

async function sendText(phoneNumberId, to, body) {
  const url = `https://graph.facebook.com/${env.graphVersion}/${phoneNumberId}/messages`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.whatsappToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      messaging_product: "whatsapp",
      to,
      type: "text",
      text: { body },
    }),
  });
  if (!res.ok) {
    const errText = await res.text();
    console.error("Falha ao enviar WhatsApp:", res.status, errText);
  }
  return res.ok;
}

// Envia um template aprovado (necessário para o lembrete da véspera, que é
// mensagem iniciada pela empresa, fora da janela de 24h de conversa aberta).
async function sendTemplate(phoneNumberId, to, templateName, languageCode, components) {
  const url = `https://graph.facebook.com/${env.graphVersion}/${phoneNumberId}/messages`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.whatsappToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      messaging_product: "whatsapp",
      to,
      type: "template",
      template: { name: templateName, language: { code: languageCode || "pt_BR" }, components: components || [] },
    }),
  });
  if (!res.ok) {
    const errText = await res.text();
    console.error("Falha ao enviar template WhatsApp:", res.status, errText);
  }
  return res.ok;
}

// Extrai as mensagens de texto de um payload de webhook da Meta.
// Devolve uma lista de { phoneNumberId, from, text, waMessageId } (pode vir vazia:
// por ex. quando o webhook é só uma atualização de status "entregue/lido").
function parseIncoming(body) {
  const out = [];
  for (const entry of body.entry || []) {
    for (const change of entry.changes || []) {
      const value = change.value || {};
      const phoneNumberId = value.metadata && value.metadata.phone_number_id;
      for (const m of value.messages || []) {
        if (m.type === "text" && m.text) {
          out.push({ phoneNumberId, from: m.from, text: m.text.body, waMessageId: m.id });
        } else if (m.type === "button" && m.button) {
          out.push({ phoneNumberId, from: m.from, text: m.button.text, waMessageId: m.id });
        } else if (m.interactive && m.interactive.button_reply) {
          out.push({ phoneNumberId, from: m.from, text: m.interactive.button_reply.title, waMessageId: m.id });
        }
      }
    }
  }
  return out;
}

module.exports = { sendText, sendTemplate, parseIncoming };
