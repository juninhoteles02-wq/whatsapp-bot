// Ferramentas que a IA pode chamar durante o atendimento normal (cliente).
// Cada tool tem: name, description, parameters (JSON Schema) e um execute()
// que recebe (client, telefoneDoCliente, args) e devolve um objeto simples
// (a IA lê o resultado e decide o que responder).

const gcal = require("./googleCalendar");
const sched = require("./scheduling");

function needServico(client, servico) {
  if (!servico || !String(servico).trim()) {
    throw new Error("Serviço não informado. Pergunte ao cliente se é " + Object.keys(client.services).join(", ") + " antes de ver horários ou marcar.");
  }
  const norm = normServico(client, servico);
  if (!norm) throw new Error(`Serviço inválido. Opções: ${Object.keys(client.services).join(", ")}.`);
  return norm;
}

function normServico(client, s) {
  s = String(s || "").toLowerCase();
  const opts = Object.keys(client.services);
  if (s.includes("corte") && s.includes("barba")) return opts.find((o) => o.toLowerCase().includes("corte") && o.toLowerCase().includes("barba"));
  if (s.includes("barba")) return opts.find((o) => o.toLowerCase() === "barba") || opts.find((o) => o.toLowerCase().includes("barba"));
  if (s.includes("corte")) return opts.find((o) => o.toLowerCase() === "corte") || opts.find((o) => o.toLowerCase().includes("corte"));
  return opts.find((o) => o.toLowerCase() === s) || null;
}

function normBarbeiro(client, b) {
  if (!b) return null;
  return client.barbers.find((n) => n.toLowerCase() === String(b).trim().toLowerCase()) || null;
}

function describe(ev) {
  return {
    codigo: ev.id,
    servico: ev.servico,
    barbeiro: ev.barbeiro,
    data: ev.hora ? ev.raw.start.dateTime.slice(0, 10) : null,
    dia: ev.hora ? `${sched.WEEK[sched.fromIso(ev.raw.start.dateTime.slice(0, 10)).getDay()]} ${sched.br(ev.raw.start.dateTime.slice(0, 10))}` : null,
    hora: ev.hora,
    status: ev.situacao,
  };
}

async function findMine(client, telefone, codigo) {
  const upcoming = await gcal.listUpcomingForPhone(client.calendarId, telefone);
  const ev = upcoming.find((e) => e.id === String(codigo || "").trim());
  if (!ev) throw new Error("Código não encontrado entre os agendamentos deste cliente.");
  return ev;
}

function buildTools(client, telefone, ctx) {
  // ctx: objeto mutável só desta conversa, usado para lembrar o último lembrete
  // respondido (confirmar_presenca sem código) e para acionar alertas ao dono.
  return [
    {
      name: "ver_horarios_livres",
      description: "Lista os horários em que o serviço escolhido cabe inteiro. Só use depois que o cliente disse qual serviço quer.",
      parameters: {
        type: "object",
        properties: {
          data: { type: "string", description: "AAAA-MM-DD" },
          servico: { type: "string", enum: Object.keys(client.services) },
          barbeiro: { type: "string", enum: client.barbers },
        },
        required: ["data", "servico"],
      },
      async execute(args) {
        const dateISO = sched.checkDay(args.data, client.businessHours);
        const servico = needServico(client, args.servico);
        const minutos = client.services[servico].min;
        const only = normBarbeiro(client, args.barbeiro);
        const barbeiros = only ? [only] : client.barbers;
        const events = await gcal.listEventsForDay(client.calendarId, dateISO);
        const livres = {};
        for (const b of barbeiros) {
          livres[b] = sched.timesOfDay(client.businessHours).filter((t) =>
            sched.canFit(dateISO, b, t, minutos, client.businessHours, events, null)
          );
        }
        return { dia: `${sched.WEEK[sched.fromIso(dateISO).getDay()]} ${sched.br(dateISO)}`, servico, livres };
      },
    },
    {
      name: "criar_agendamento",
      description: "Marca um horário para o cliente desta conversa. Use só depois que ele escolheu dia, hora e serviço, e depois de confirmar que o horário está livre.",
      parameters: {
        type: "object",
        properties: {
          data: { type: "string" },
          hora: { type: "string", description: "HH:MM" },
          servico: { type: "string", enum: Object.keys(client.services) },
          barbeiro: { type: "string", enum: client.barbers },
          nome_cliente: { type: "string", description: "Nome do cliente, para identificar o agendamento." },
        },
        required: ["data", "hora", "servico", "nome_cliente"],
      },
      async execute(args) {
        const dateISO = sched.checkDay(args.data, client.businessHours);
        const servico = needServico(client, args.servico);
        const minutos = client.services[servico].min;
        const hora = String(args.hora).slice(0, 5);
        const events = await gcal.listEventsForDay(client.calendarId, dateISO);
        const escolhido = normBarbeiro(client, args.barbeiro) ||
          client.barbers.find((b) => sched.canFit(dateISO, b, hora, minutos, client.businessHours, events, null));
        if (!escolhido || !sched.canFit(dateISO, escolhido, hora, minutos, client.businessHours, events, null)) {
          throw new Error("Esse horário não está livre. Consulte os horários livres de novo.");
        }
        const ev = await gcal.createEvent(client.calendarId, {
          dateISO, hora, minutos,
          cliente: args.nome_cliente || "Cliente",
          servico, barbeiro: escolhido, telefone, origem: "assistente",
        });
        return { ok: true, ...describe(ev) };
      },
    },
    {
      name: "buscar_agendamentos",
      description: "Retorna os agendamentos ativos do cliente desta conversa (código, dia, hora, barbeiro, serviço, status).",
      parameters: { type: "object", properties: {} },
      async execute() {
        const upcoming = await gcal.listUpcomingForPhone(client.calendarId, telefone);
        return upcoming.map(describe);
      },
    },
    {
      name: "remarcar_agendamento",
      description: "Move um agendamento existente (pelo código) para outro dia/hora, e opcionalmente outro barbeiro.",
      parameters: {
        type: "object",
        properties: {
          codigo: { type: "string" },
          data: { type: "string" },
          hora: { type: "string" },
          barbeiro: { type: "string", enum: client.barbers },
        },
        required: ["codigo", "data", "hora"],
      },
      async execute(args) {
        const atual = await findMine(client, telefone, args.codigo);
        const dateISO = sched.checkDay(args.data, client.businessHours);
        const hora = String(args.hora).slice(0, 5);
        const minutos = client.services[atual.servico].min;
        const events = await gcal.listEventsForDay(client.calendarId, dateISO);
        const escolhido = normBarbeiro(client, args.barbeiro) ||
          (sched.canFit(dateISO, atual.barbeiro, hora, minutos, client.businessHours, events, atual.id) ? atual.barbeiro
            : client.barbers.find((b) => sched.canFit(dateISO, b, hora, minutos, client.businessHours, events, atual.id)));
        if (!escolhido || !sched.canFit(dateISO, escolhido, hora, minutos, client.businessHours, events, atual.id)) {
          throw new Error("Esse horário não está livre.");
        }
        const ev = await gcal.moveEvent(client.calendarId, atual.id, { dateISO, hora, minutos, barbeiro: escolhido });
        return { ok: true, ...describe(ev) };
      },
    },
    {
      name: "trocar_servico",
      description: "Troca o serviço de um agendamento existente (ex.: de Corte para Corte + Barba). Tenta manter o mesmo horário; se não couber, não muda nada e devolve os horários mais próximos em que cabe, no mesmo dia.",
      parameters: {
        type: "object",
        properties: {
          codigo: { type: "string" },
          servico: { type: "string", enum: Object.keys(client.services) },
        },
        required: ["codigo", "servico"],
      },
      async execute(args) {
        const atual = await findMine(client, telefone, args.codigo);
        const servico = needServico(client, args.servico);
        const minutos = client.services[servico].min;
        const dateISO = atual.raw.start.dateTime.slice(0, 10);
        const events = await gcal.listEventsForDay(client.calendarId, dateISO);
        if (sched.canFit(dateISO, atual.barbeiro, atual.hora, minutos, client.businessHours, events, atual.id)) {
          const ev = await gcal.patchEvent(client.calendarId, atual.id, {
            summary: `${atual.cliente} - ${servico}`,
            extendedProperties: { private: { servico } },
          });
          return { ok: true, manteve_horario: true, ...describe(ev) };
        }
        const i = sched.timesOfDay(client.businessHours).indexOf(atual.hora);
        const proximos = sched.timesOfDay(client.businessHours)
          .filter((t) => sched.canFit(dateISO, atual.barbeiro, t, minutos, client.businessHours, events, atual.id))
          .sort((a, b) => Math.abs(sched.timesOfDay(client.businessHours).indexOf(a) - i) - Math.abs(sched.timesOfDay(client.businessHours).indexOf(b) - i))
          .slice(0, 3)
          .sort();
        return {
          ok: false, manteve_horario: false,
          motivo: `${servico} leva ${minutos} min e não cabe às ${atual.hora}, porque o horário seguinte já está ocupado.`,
          horarios_mais_proximos_no_mesmo_dia: proximos,
          agendamento_atual: describe(atual),
        };
      },
    },
    {
      name: "cancelar_agendamento",
      description: "Cancela um agendamento do cliente pelo código. Use só se o cliente confirmou que quer cancelar.",
      parameters: { type: "object", properties: { codigo: { type: "string" } }, required: ["codigo"] },
      async execute(args) {
        const ev = await findMine(client, telefone, args.codigo);
        await gcal.cancelEvent(client.calendarId, ev.id);
        return { ok: true, cancelado: ev.id };
      },
    },
    {
      name: "confirmar_presenca",
      description: "Marca o agendamento do cliente como confirmado (resposta ao lembrete da véspera). Sem código, confirma o agendamento do último lembrete enviado.",
      parameters: { type: "object", properties: { codigo: { type: "string", description: "Opcional. Se omitido, usa o do último lembrete." } } },
      async execute(args) {
        const codigo = args.codigo || ctx.lastReminderEventId;
        if (!codigo) throw new Error("Não há um lembrete recente para confirmar. Pergunte qual agendamento o cliente quer confirmar.");
        const ev = await findMine(client, telefone, codigo);
        const atualizado = await gcal.setSituacao(client.calendarId, ev.id, "confirmado");
        return { ok: true, ...describe(atualizado) };
      },
    },
    {
      name: "chamar_barbeiro",
      description: "Avisa o barbeiro quando o cliente pede para falar com uma pessoa ou traz algo que o assistente não resolve.",
      parameters: { type: "object", properties: { motivo: { type: "string" } }, required: ["motivo"] },
      async execute(args) {
        if (ctx.onCallBarber) await ctx.onCallBarber(String(args.motivo || "").slice(0, 200));
        return { ok: true };
      },
    },
  ];
}

module.exports = { buildTools, normServico, describe, findMine };
