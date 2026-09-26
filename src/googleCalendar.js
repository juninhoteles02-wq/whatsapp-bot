// Camada fina sobre a API do Google Calendar.
// Guardamos os dados do agendamento (cliente, serviço, status, origem) em
// extendedProperties.private, que não aparece para o Elias na tela do app do
// Google Agenda, mas o servidor consegue ler e filtrar.

const { google } = require("googleapis");
const path = require("path");
const { env } = require("./config");

let calendarClientPromise = null;

function getCalendarClient() {
  if (!calendarClientPromise) {
    const keyFile = path.resolve(process.cwd(), env.googleKeyPath);
    const auth = new google.auth.GoogleAuth({
      keyFile,
      scopes: ["https://www.googleapis.com/auth/calendar"],
    });
    calendarClientPromise = auth.getClient().then(
      (authClient) => google.calendar({ version: "v3", auth: authClient })
    );
  }
  return calendarClientPromise;
}

function toRFC3339(dateISO, timeHM, timeZone = "America/Sao_Paulo") {
  // dateISO: "2026-09-26", timeHM: "14:30"
  return { dateTime: `${dateISO}T${timeHM}:00`, timeZone };
}

function addMinutes(timeHM, minutes) {
  const [h, m] = timeHM.split(":").map(Number);
  const total = h * 60 + m + minutes;
  const hh = Math.floor(total / 60) % 24;
  const mm = total % 60;
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
}

async function listEvents(calendarId, timeMin, timeMax) {
  const calendar = await getCalendarClient();
  const res = await calendar.events.list({
    calendarId,
    timeMin,
    timeMax,
    singleEvents: true,
    orderBy: "startTime",
    maxResults: 250,
  });
  return (res.data.items || [])
    .filter((ev) => ev.status !== "cancelled")
    .map(parseEvent);
}

// Lista os eventos (não cancelados) de um dia inteiro na agenda do cliente.
async function listEventsForDay(calendarId, dateISO) {
  return listEvents(calendarId, `${dateISO}T00:00:00-03:00`, `${dateISO}T23:59:59-03:00`);
}

// Busca os agendamentos futuros (próximos N dias) de um telefone específico,
// varrendo a agenda inteira do cliente (independente do dia).
async function listUpcomingForPhone(calendarId, telefone, diasAFrente = 45) {
  const now = new Date();
  const until = new Date(now.getTime() + diasAFrente * 24 * 60 * 60 * 1000);
  const events = await listEvents(calendarId, now.toISOString(), until.toISOString());
  return events.filter((ev) => ev.telefone === telefone && ev.situacao !== "cancelado");
}

function parseEvent(ev) {
  const priv = (ev.extendedProperties && ev.extendedProperties.private) || {};
  const hora = ev.start && ev.start.dateTime ? ev.start.dateTime.slice(11, 16) : null;
  return {
    id: ev.id,
    hora,
    fimHora: ev.end && ev.end.dateTime ? ev.end.dateTime.slice(11, 16) : null,
    cliente: priv.cliente || (ev.summary || "").split(" - ")[0] || "Cliente",
    servico: priv.servico || "Corte",
    barbeiro: priv.barbeiro || "Elias",
    telefone: priv.telefone || "",
    origem: priv.origem || "balcao",
    situacao: priv.situacao || "agendado", // agendado | confirmado | cancelado | faltou
    raw: ev,
  };
}

async function createEvent(calendarId, { dateISO, hora, minutos, cliente, servico, barbeiro, telefone, origem }) {
  const calendar = await getCalendarClient();
  const fim = addMinutes(hora, minutos);
  const res = await calendar.events.insert({
    calendarId,
    requestBody: {
      summary: `${cliente} - ${servico}`,
      description: `Agendado via Combinado.\nCliente: ${cliente}\nTelefone: ${telefone}\nServiço: ${servico}`,
      start: toRFC3339(dateISO, hora),
      end: toRFC3339(dateISO, fim),
      extendedProperties: {
        private: { cliente, servico, barbeiro, telefone, origem: origem || "assistente", situacao: "agendado" },
      },
    },
  });
  return parseEvent(res.data);
}

async function getEvent(calendarId, eventId) {
  const calendar = await getCalendarClient();
  const res = await calendar.events.get({ calendarId, eventId });
  return res.data;
}

// A API do Calendar substitui o mapa extendedProperties.private inteiro a
// cada patch (não faz merge por chave). Por isso, sempre buscamos o evento
// atual e mesclamos manualmente antes de enviar o patch.
async function patchEvent(calendarId, eventId, patch) {
  const calendar = await getCalendarClient();
  if (patch.extendedProperties && patch.extendedProperties.private) {
    const current = await getEvent(calendarId, eventId);
    const currentPrivate = (current.extendedProperties && current.extendedProperties.private) || {};
    patch = {
      ...patch,
      extendedProperties: { private: { ...currentPrivate, ...patch.extendedProperties.private } },
    };
  }
  const res = await calendar.events.patch({ calendarId, eventId, requestBody: patch });
  return parseEvent(res.data);
}

async function moveEvent(calendarId, eventId, { dateISO, hora, minutos, barbeiro }) {
  const fim = addMinutes(hora, minutos);
  return patchEvent(calendarId, eventId, {
    start: toRFC3339(dateISO, hora),
    end: toRFC3339(dateISO, fim),
    extendedProperties: { private: { barbeiro, situacao: "agendado" } },
  });
}

async function setSituacao(calendarId, eventId, situacao) {
  return patchEvent(calendarId, eventId, { extendedProperties: { private: { situacao } } });
}

async function cancelEvent(calendarId, eventId) {
  const calendar = await getCalendarClient();
  await calendar.events.patch({ calendarId, eventId, requestBody: { status: "cancelled" } });
  return { ok: true };
}

module.exports = {
  listEvents,
  listEventsForDay,
  listUpcomingForPhone,
  createEvent,
  patchEvent,
  moveEvent,
  setSituacao,
  cancelEvent,
  addMinutes,
};
