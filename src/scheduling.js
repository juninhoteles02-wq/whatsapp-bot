// Regras puras de agenda: horários possíveis, dia útil, se um serviço cabe
// num horário etc. Não fala com o Google nem com a IA, só faz contas.

const WEEK = ["domingo", "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado"];
const WEEK_S = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];

function pad(n) { return String(n).padStart(2, "0"); }

function isoToday(tz = "America/Sao_Paulo") {
  const now = new Date(new Date().toLocaleString("en-US", { timeZone: tz }));
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function nowHM(tz = "America/Sao_Paulo") {
  const now = new Date(new Date().toLocaleString("en-US", { timeZone: tz }));
  return `${pad(now.getHours())}:${pad(now.getMinutes())}`;
}

function fromIso(dateISO) {
  const [y, m, d] = dateISO.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function br(dateISO) {
  const [, m, d] = dateISO.split("-");
  return `${d}/${m}`;
}

function isOpenDay(dateISO, hours) {
  const dow = fromIso(dateISO).getDay();
  return dow >= hours.openDay && dow <= hours.closeDay;
}

function isLunch(timeHM, hours) {
  return timeHM >= `${pad(hours.lunchStart)}:00` && timeHM < `${pad(hours.lunchEnd)}:00`;
}

function timesOfDay(hours) {
  const out = [];
  for (let h = hours.openHour; h < hours.closeHour; h++) {
    out.push(`${pad(h)}:00`);
    out.push(`${pad(h)}:30`);
  }
  return out;
}

function nextOpenDays(hours, n = 6, tz = "America/Sao_Paulo") {
  const out = [];
  const start = fromIso(isoToday(tz));
  for (let i = 0; out.length < n && i < 30; i++) {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    const iso = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    if (isOpenDay(iso, hours)) out.push(iso);
  }
  return out;
}

// Lança erro com mensagem amigável (a IA repassa isso pro cliente) se a data
// não servir; devolve a data validada (string) se estiver tudo certo.
function checkDay(dateISO, hours, tz = "America/Sao_Paulo") {
  dateISO = String(dateISO || "").trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateISO)) {
    throw new Error("Data deve estar no formato AAAA-MM-DD.");
  }
  if (!isOpenDay(dateISO, hours)) {
    throw new Error(`A barbearia não abre ${WEEK[fromIso(dateISO).getDay()]}. Dias de atendimento: ${WEEK[hours.openDay]} a ${WEEK[hours.closeDay]}.`);
  }
  if (dateISO < isoToday(tz)) {
    throw new Error("Essa data já passou.");
  }
  return dateISO;
}

function isPast(dateISO, timeHM, tz = "America/Sao_Paulo") {
  return dateISO === isoToday(tz) && timeHM <= nowHM(tz);
}

// events: lista já filtrada (parseEvent do googleCalendar.js) do dia inteiro
function occupiedSlots(events, barbeiro, ignoreId, minutosPorSlotFn) {
  const set = new Set();
  events.forEach((ev) => {
    if (ev.barbeiro !== barbeiro) return;
    if (ev.situacao === "cancelado") return;
    if (ev.id === ignoreId) return;
    const dur = minutosPorSlotFn(ev.servico);
    const slots = Math.round(dur / 30);
    const times = timesOfDayFromHora(ev.hora, slots);
    times.forEach((t) => set.add(t));
  });
  return set;
}

function timesOfDayFromHora(horaInicio, quantidadeSlots) {
  const [h, m] = horaInicio.split(":").map(Number);
  const out = [];
  let total = h * 60 + m;
  for (let i = 0; i < quantidadeSlots; i++) {
    out.push(`${pad(Math.floor(total / 60) % 24)}:${pad(total % 60)}`);
    total += 30;
  }
  return out;
}

function canFit(dateISO, barbeiro, timeHM, minutos, hours, events, ignoreId, tz) {
  const n = Math.round(minutos / 30);
  const times = timesOfDayFromHora(timeHM, n);
  const dayTimes = new Set(timesOfDay(hours));
  const occ = occupiedSlots(events, barbeiro, ignoreId, () => minutos);
  for (const t of times) {
    if (!dayTimes.has(t)) return false;
    if (occ.has(t)) return false;
    if (isLunch(t, hours)) return false;
    if (isPast(dateISO, t, tz)) return false;
  }
  return true;
}

module.exports = {
  WEEK, WEEK_S,
  isoToday, nowHM, fromIso, br,
  isOpenDay, isLunch, timesOfDay, nextOpenDays,
  checkDay, isPast, occupiedSlots, canFit, timesOfDayFromHora,
};
