// Lembrete da véspera: todo dia às 18h (horário de Brasília), olha os
// agendamentos de amanhã de cada cliente e manda um template aprovado
// perguntando se a pessoa confirma ou quer remarcar.
//
// IMPORTANTE: mensagens que a empresa inicia (o cliente não mandou nada nas
// últimas 24h) só podem ser um "template" pré-aprovado pela Meta. Crie um
// em Meta for Developers > WhatsApp > Modelos de mensagem, por exemplo:
//   Nome: lembrete_vespera
//   Corpo: "Oi {{1}}! Passando pra lembrar do seu horário amanhã às {{2}}, {{3}}.
//           Responda 1 para confirmar ou 2 para remarcar."
// e ajuste ELIAS_REMINDER_TEMPLATE no .env com o nome exato.

const cron = require("node-cron");
const { CLIENTS } = require("./config");
const gcal = require("./googleCalendar");
const sched = require("./scheduling");
const wa = require("./whatsapp");
const { getClientConvo } = require("./state");

function tomorrowISO() {
  const hoje = sched.fromIso(sched.isoToday());
  const d = new Date(hoje);
  d.setDate(hoje.getDate() + 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

async function sendRemindersForClient(client) {
  const amanha = tomorrowISO();
  if (!sched.isOpenDay(amanha, client.businessHours)) return;
  const events = await gcal.listEventsForDay(client.calendarId, amanha);
  const pendentes = events.filter((e) => e.situacao === "agendado" && e.telefone);

  for (const ev of pendentes) {
    const dia = `${sched.WEEK[sched.fromIso(amanha).getDay()]} (${sched.br(amanha)})`;
    const ok = await wa.sendTemplate(client.phoneNumberId, ev.telefone, client.reminderTemplate, "pt_BR", [
      {
        type: "body",
        parameters: [
          { type: "text", text: ev.cliente },
          { type: "text", text: `${dia} às ${ev.hora}` },
          { type: "text", text: ev.servico },
        ],
      },
    ]);
    if (ok) {
      const convo = getClientConvo(ev.telefone);
      convo.lastReminderEventId = ev.id;
      console.log(`Lembrete enviado para ${ev.cliente} (${ev.telefone}) - ${client.displayName}`);
    }
  }
}

function start() {
  // "0 18 * * *" = todo dia às 18h no fuso do processo. Se o servidor rodar
  // em UTC (comum em provedores de nuvem), ajuste para "0 21 * * *" (18h em
  // São Paulo = 21h UTC) ou configure TZ=America/Sao_Paulo no ambiente.
  cron.schedule("0 18 * * *", async () => {
    for (const client of CLIENTS) {
      if (!client.calendarId || !client.phoneNumberId) continue;
      try {
        await sendRemindersForClient(client);
      } catch (err) {
        console.error(`Erro ao enviar lembretes de ${client.displayName}:`, err);
      }
    }
  });
}

start();

module.exports = { sendRemindersForClient };
