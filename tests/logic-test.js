// Teste manual de lógica (não faz parte do projeto entregue). Substitui o
// Google Calendar real por uma agenda falsa em memória, pra validar as
// contas de horário sem precisar de credenciais de verdade.
process.env.ELIAS_PHONE_NUMBER_ID = "PN123";
process.env.ELIAS_CALENDAR_ID = "cal123";
process.env.ELIAS_OWNER_PHONE = "5521999990000";
process.env.ELIAS_OWNER_CODE = "1234";

const assert = require("assert");
const { getClientById } = require("../src/config");
const gcal = require("../src/googleCalendar");
const sched = require("../src/scheduling");
const { buildTools } = require("../src/tools");
const { buildOwnerTools } = require("../src/ownerTools");

const client = getClientById("elias");
const today = sched.isoToday();
const tomorrow = sched.nextOpenDays(client.businessHours, 6)[1];

// ---- agenda falsa em memória ----
let seq = 1;
let events = [];
function addMinutes(hm, min) {
  const [h, m] = hm.split(":").map(Number);
  const t = h * 60 + m + min;
  return `${String(Math.floor(t / 60) % 24).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
}
function makeEvent({ dateISO, hora, minutos, cliente, servico, barbeiro, telefone, origem, situacao }) {
  return {
    id: "EV" + seq++,
    hora,
    fimHora: addMinutes(hora, minutos),
    cliente, servico, barbeiro, telefone,
    origem: origem || "assistente",
    situacao: situacao || "agendado",
    raw: { start: { dateTime: `${dateISO}T${hora}:00-03:00` }, end: { dateTime: `${dateISO}T${addMinutes(hora, minutos)}:00-03:00` } },
  };
}

gcal.listEventsForDay = async (calendarId, dateISO) => events.filter((e) => e.raw.start.dateTime.slice(0, 10) === dateISO && e.situacao !== "cancelado");
gcal.listUpcomingForPhone = async (calendarId, telefone) => events.filter((e) => e.telefone === telefone && e.situacao !== "cancelado");
gcal.createEvent = async (calendarId, args) => { const ev = makeEvent(args); events.push(ev); return ev; };
gcal.patchEvent = async (calendarId, eventId, patch) => {
  const ev = events.find((e) => e.id === eventId);
  const priv = (patch.extendedProperties && patch.extendedProperties.private) || {};
  Object.assign(ev, priv);
  if (patch.start) { ev.hora = patch.start.dateTime.slice(11, 16); ev.raw.start.dateTime = patch.start.dateTime.includes("T") ? `${patch.start.dateTime}` : ev.raw.start.dateTime; }
  if (patch.start) ev.raw.start.dateTime = `${patch.start.dateTime}`;
  if (patch.end) ev.raw.end.dateTime = `${patch.end.dateTime}`;
  return ev;
};
gcal.moveEvent = async (calendarId, eventId, { dateISO, hora, minutos, barbeiro }) => {
  const ev = events.find((e) => e.id === eventId);
  ev.hora = hora; ev.barbeiro = barbeiro; ev.situacao = "agendado";
  ev.raw.start.dateTime = `${dateISO}T${hora}:00-03:00`;
  ev.raw.end.dateTime = `${dateISO}T${addMinutes(hora, minutos)}:00-03:00`;
  return ev;
};
gcal.setSituacao = async (calendarId, eventId, situacao) => { const ev = events.find((e) => e.id === eventId); ev.situacao = situacao; return ev; };
gcal.cancelEvent = async (calendarId, eventId) => { events = events.filter((e) => e.id !== eventId); return { ok: true }; };

async function run() {
  const telefone = "5521988887777";
  const ctx = { lastReminderEventId: null, onCallBarber: async () => {} };
  const tools = buildTools(client, telefone, ctx);
  const byName = Object.fromEntries(tools.map((t) => [t.name, t]));

  // 1) sem serviço deve falhar
  try {
    await byName.ver_horarios_livres.execute({ data: tomorrow });
    throw new Error("deveria ter falhado sem serviço");
  } catch (e) {
    assert.match(e.message, /Serviço não informado/);
    console.log("OK: exige serviço antes de ver horários");
  }

  // 2) ver horários livres para Corte
  const livres = await byName.ver_horarios_livres.execute({ data: tomorrow, servico: "Corte" });
  assert.ok(livres.livres.Elias.includes("15:00"));
  console.log("OK: 15:00 livre para Corte");

  // 3) criar agendamento às 15:00 Corte
  const criado = await byName.criar_agendamento.execute({ data: tomorrow, hora: "15:00", servico: "Corte", nome_cliente: "Lucas" });
  assert.strictEqual(criado.ok, true);
  assert.strictEqual(criado.hora, "15:00");
  console.log("OK: agendamento criado", criado.codigo);

  // 4) buscar agendamentos do cliente
  const meus = await byName.buscar_agendamentos.execute({});
  assert.strictEqual(meus.length, 1);
  console.log("OK: buscar_agendamentos encontra o agendamento");

  // 5) trocar serviço para Corte + Barba (1h) não deve caber às 15:00 se 15:30 ocupado por outro
  events.push(makeEvent({ dateISO: tomorrow, hora: "15:30", minutos: 30, cliente: "Outro", servico: "Corte", barbeiro: "Elias", telefone: "000" }));
  const troca = await byName.trocar_servico.execute({ codigo: criado.codigo, servico: "Corte + Barba" });
  assert.strictEqual(troca.ok, false);
  assert.ok(troca.horarios_mais_proximos_no_mesmo_dia.length > 0);
  console.log("OK: trocar_servico recusa e sugere horários:", troca.horarios_mais_proximos_no_mesmo_dia);

  // 6) remarcar para 17:00
  const remarcado = await byName.remarcar_agendamento.execute({ codigo: criado.codigo, data: tomorrow, hora: "17:00" });
  assert.strictEqual(remarcado.hora, "17:00");
  console.log("OK: remarcar_agendamento move o horário");

  // 7) confirmar presença
  const confirmado = await byName.confirmar_presenca.execute({ codigo: criado.codigo });
  assert.strictEqual(confirmado.status, "confirmado");
  console.log("OK: confirmar_presenca marca confirmado");

  // 8) cancelar
  const cancelado = await byName.cancelar_agendamento.execute({ codigo: criado.codigo });
  assert.strictEqual(cancelado.ok, true);
  const meusDepois = await byName.buscar_agendamentos.execute({});
  assert.strictEqual(meusDepois.length, 0);
  console.log("OK: cancelar_agendamento remove da lista do cliente");

  // ---- modo dono ----
  events = [];
  events.push(makeEvent({ dateISO: today, hora: "09:00", minutos: 30, cliente: "Marcos", servico: "Corte", barbeiro: "Elias", telefone: "111" }));
  events.push(makeEvent({ dateISO: today, hora: "10:00", minutos: 60, cliente: "Caio", servico: "Corte + Barba", barbeiro: "Elias", telefone: "222" }));
  const ownerTools = buildOwnerTools(client);
  const ownerByName = Object.fromEntries(ownerTools.map((t) => [t.name, t]));

  const resumo = await ownerByName.resumo_do_dia.execute({});
  assert.strictEqual(resumo.quantidade, 2);
  assert.strictEqual(resumo.previsto, 45 + 70);
  console.log("OK: resumo_do_dia soma previsto corretamente:", resumo.previsto);

  const fechamento = await ownerByName.registrar_fechamento.execute({ faltas: ["Marcos"], encaixes: [{ servico: "Corte", quantidade: 2 }] });
  assert.strictEqual(fechamento.faturamento_real, (45 + 70) - 45 + 2 * 45);
  console.log("OK: registrar_fechamento calcula faturamento real:", fechamento.faturamento_real);

  console.log("\nTodos os testes de lógica passaram.");
}

run().catch((err) => { console.error("FALHOU:", err); process.exit(1); });
