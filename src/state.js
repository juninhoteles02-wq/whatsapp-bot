// Estado de conversa em memória, compartilhado entre o servidor (index.js) e
// o job de lembretes (reminders.js). Some se o processo reiniciar - para
// persistir de verdade entre reinícios, trocar por store.js (arquivo) ou um
// banco de dados.

const clientConversations = new Map(); // phone -> { history, lastReminderEventId }

function getClientConvo(phone) {
  if (!clientConversations.has(phone)) clientConversations.set(phone, { history: [], lastReminderEventId: null });
  return clientConversations.get(phone);
}

module.exports = { clientConversations, getClientConvo };
