// Configuração central do Combinado.
// Cada barbearia (cliente) vira uma entrada em CLIENTS. Para adicionar um novo
// cliente no futuro, basta copiar o bloco do Elias, trocar os dados e criar as
// variáveis de ambiente correspondentes (ex: NOVOCLIENTE_PHONE_NUMBER_ID etc.).

require("dotenv").config();

const CLIENTS = [
  {
    id: "elias",
    displayName: "Barbearia do Elias",
    address: "Av. Henrique Duque Estrada Meyer, 540, Posse, Nova Iguaçu - RJ, 26030-380",
    phoneNumberId: process.env.ELIAS_PHONE_NUMBER_ID,
    calendarId: process.env.ELIAS_CALENDAR_ID,
    barbers: ["Elias"],
    services: {
      "Corte": { min: 30, price: 45 },
      "Barba": { min: 30, price: 35 },
      "Corte + Barba": { min: 60, price: 70 },
    },
    // openDay/closeDay: 0=domingo .. 6=sábado
    businessHours: { openDay: 2, closeDay: 6, openHour: 9, closeHour: 19, lunchStart: 12, lunchEnd: 13 },
    owner: {
      phone: (process.env.ELIAS_OWNER_PHONE || "").replace(/\D/g, ""),
      code: process.env.ELIAS_OWNER_CODE || "1234",
      unlockHours: 4,
    },
    reminderTemplate: process.env.ELIAS_REMINDER_TEMPLATE || "lembrete_vespera",
  },
];

function getClientByPhoneNumberId(phoneNumberId) {
  return CLIENTS.find((c) => c.phoneNumberId === phoneNumberId) || null;
}

function getClientById(id) {
  return CLIENTS.find((c) => c.id === id) || null;
}

module.exports = {
  CLIENTS,
  getClientByPhoneNumberId,
  getClientById,
  env: {
    whatsappToken: process.env.WHATSAPP_TOKEN,
    verifyToken: process.env.WHATSAPP_VERIFY_TOKEN || "combinado-verify-2026",
    graphVersion: process.env.GRAPH_API_VERSION || "v21.0",
    openaiKey: process.env.OPENAI_API_KEY,
    openaiModel: process.env.OPENAI_MODEL || "gpt-4o-mini",
    googleKeyPath: process.env.GOOGLE_SERVICE_ACCOUNT_KEY_PATH || "./secrets/combinado-servidor.json",
    port: parseInt(process.env.PORT || "3000", 10),
  },
};
