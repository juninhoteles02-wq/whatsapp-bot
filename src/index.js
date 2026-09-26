const express = require("express");
const { env, getClientByPhoneNumberId } = require("./config");
const wa = require("./whatsapp");
const gcal = require("./googleCalendar");
const sched = require("./scheduling");
const { buildTools, describe } = require("./tools");
const { buildOwnerTools } = require("./ownerTools");
const { clientRules, ownerRules } = require("./prompts");
const ownerSession = require("./ownerSession");
const ai = require("./ai");
require("./reminders"); // agenda o lembrete da véspera (node-cron)

const app = express();
app.use(express.json());

// ---------- estado em memória (por conversa) ----------
const { getClientConvo } = require("./state");
const ownerConversations = new Map(); // phone -> { history }
const ownerPending = new Map(); // phone -> { awaitingCode: bool, pendingText: string|null }
const seenMessageIds = [];
const seenMessageSet = new Set();

function markSeen(id) {
  if (!id) return false;
  if (seenMessageSet.has(id)) return true;
  seenMessageSet.add(id);
  seenMessageIds.push(id);
  if (seenMessageIds.length > 1000) {
    const old = seenMessageIds.shift();
    seenMessageSet.delete(old);
  }
  return false;
}

function getOwnerConvo(phone) {
  if (!ownerConversations.has(phone)) ownerConversations.set(phone, { history: [] });
  return ownerConversations.get(phone);
}

// ---------- verificação do webhook (GET) ----------
app.get("/webhook", (req, res) => {
  const mode = req.query["hub.mode"];
  const token = req.query["hub.verify_token"];
  const challenge = req.query["hub.challenge"];
  if (mode === "subscribe" && token === env.verifyToken) {
    return res.status(200).send(challenge);
  }
  return res.sendStatus(403);
});

// ---------- recebimento de mensagens (POST) ----------
app.post("/webhook", async (req, res) => {
  res.sendStatus(200); // responde rápido pra Meta; processamos em seguida
  try {
    const incoming = wa.parseIncoming(req.body);
    for (const msg of incoming) {
      if (markSeen(msg.waMessageId)) continue; // evita responder duplicado
      const client = getClientByPhoneNumberId(msg.phoneNumberId);
      if (!client) {
        console.warn("Mensagem recebida para phone_number_id sem cliente configurado:", msg.phoneNumberId);
        continue;
      }
      handleMessage(client, msg.from, msg.text).catch((err) => console.error("Erro ao processar mensagem:", err));
    }
  } catch (err) {
    console.error("Erro no webhook:", err);
  }
});

async function handleMessage(client, from, text) {
  const isOwner = client.owner.phone && from === client.owner.phone;
  if (isOwner) return handleOwnerMessage(client, from, text);
  return handleClientMessage(client, from, text);
}

async function handleClientMessage(client, from, text) {
  const convo = getClientConvo(from);
  convo.history.push({ role: "user", content: text });

  const upcoming = await gcal.listUpcomingForPhone(client.calendarId, from);
  const agendaTexto = upcoming
    .map((e) => `${e.id}: ${e.servico} com ${e.barbeiro}, ${sched.WEEK[sched.fromIso(e.raw.start.dateTime.slice(0, 10)).getDay()]} ${sched.br(e.raw.start.dateTime.slice(0, 10))} às ${e.hora} (${e.situacao})`)
    .join("; ");

  const ctx = {
    lastReminderEventId: convo.lastReminderEventId,
    onCallBarber: async (motivo) => {
      if (client.owner.phone) {
        await wa.sendText(client.phoneNumberId, client.owner.phone, `🔔 Um cliente pediu atendimento pelo Combinado.\nMotivo: ${motivo}`);
      }
    },
  };
  const tools = buildTools(client, from, ctx);
  const systemPrompt = clientRules(client, from, agendaTexto, convo.lastReminderEventId);

  const { text: reply, messages } = await ai.runConversation({
    systemPrompt,
    history: convo.history.slice(-16),
    tools,
  });

  convo.history = trimHistory(messages);
  const finalText = reply || "Desculpa, pode repetir?";
  convo.history.push({ role: "assistant", content: finalText });
  await wa.sendText(client.phoneNumberId, from, finalText);
}

async function handleOwnerMessage(client, from, text) {
  const pending = ownerPending.get(from) || { awaitingCode: false, pendingText: null };

  if (ownerSession.isBlocked(client.id)) {
    await wa.sendText(client.phoneNumberId, from, "Acesso bloqueado por algumas tentativas erradas. Tenta de novo daqui a pouco.");
    return;
  }

  if (!ownerSession.isUnlocked(client.id)) {
    if (pending.awaitingCode && /^\d{4}$/.test(text.trim())) {
      if (text.trim() === client.owner.code) {
        ownerSession.unlock(client.id, client.owner.unlockHours);
        const toProcess = pending.pendingText;
        ownerPending.set(from, { awaitingCode: false, pendingText: null });
        if (toProcess) return processOwnerText(client, from, toProcess);
        await wa.sendText(client.phoneNumberId, from, "Código conferido. O que você quer ver?");
        return;
      }
      const { blocked, triesLeft } = ownerSession.registerFailedAttempt(client.id);
      if (blocked) {
        await wa.sendText(client.phoneNumberId, from, "Código errado 3 vezes. Por segurança, o acesso ficou bloqueado por 15 minutos.");
      } else {
        await wa.sendText(client.phoneNumberId, from, `Código incorreto. Tenta de novo (${triesLeft} ${triesLeft === 1 ? "tentativa" : "tentativas"}).`);
      }
      return;
    }
    ownerPending.set(from, { awaitingCode: true, pendingText: text });
    await wa.sendText(client.phoneNumberId, from, "Oi! Esse assunto é restrito. Me manda seu código de acesso de 4 dígitos, por favor.");
    return;
  }

  return processOwnerText(client, from, text);
}

async function processOwnerText(client, from, text) {
  const convo = getOwnerConvo(from);
  convo.history.push({ role: "user", content: text });
  const tools = buildOwnerTools(client);
  const systemPrompt = ownerRules(client);
  const { text: reply, messages } = await ai.runConversation({
    systemPrompt,
    history: convo.history.slice(-16),
    tools,
  });
  convo.history = trimHistory(messages);
  const finalText = reply || "Pronto.";
  convo.history.push({ role: "assistant", content: finalText });
  await wa.sendText(client.phoneNumberId, from, finalText);
}

// Mantém só role/content (user/assistant) no histórico salvo entre mensagens;
// as chamadas de ferramenta em si não precisam ser lembradas de uma mensagem
// para a outra, só o que foi dito.
function trimHistory(messages) {
  return messages
    .filter((m) => (m.role === "user" || m.role === "assistant") && typeof m.content === "string" && m.content.length > 0)
    .slice(-16);
}

app.get("/", (req, res) => res.send("Combinado está de pé."));

app.listen(env.port, () => console.log(`Combinado rodando na porta ${env.port}`));
