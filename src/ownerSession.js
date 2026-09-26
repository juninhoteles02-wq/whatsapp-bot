// Controle de acesso ao "modo dono": só o número configurado em client.owner.phone
// entra, e só depois de acertar o código. Guardado em memória (reinicia se o
// servidor reiniciar - se isso incomodar no futuro, mover para o store.js).

const sessions = new Map(); // key: clientId -> { unlockedUntil, tries, blockedUntil }

function keyFor(clientId) { return clientId; }

function getState(clientId) {
  return sessions.get(keyFor(clientId)) || { unlockedUntil: 0, tries: 0, blockedUntil: 0 };
}

function isUnlocked(clientId) {
  return Date.now() < getState(clientId).unlockedUntil;
}

function isBlocked(clientId) {
  return Date.now() < getState(clientId).blockedUntil;
}

function unlock(clientId, hours) {
  const s = getState(clientId);
  s.unlockedUntil = Date.now() + hours * 60 * 60 * 1000;
  s.tries = 0;
  s.blockedUntil = 0;
  sessions.set(keyFor(clientId), s);
}

function relock(clientId) {
  const s = getState(clientId);
  s.unlockedUntil = 0;
  sessions.set(keyFor(clientId), s);
}

function registerFailedAttempt(clientId, maxTries = 3, blockMinutes = 15) {
  const s = getState(clientId);
  s.tries = (s.tries || 0) + 1;
  let blocked = false;
  if (s.tries >= maxTries) {
    s.blockedUntil = Date.now() + blockMinutes * 60 * 1000;
    s.tries = 0;
    blocked = true;
  }
  sessions.set(keyFor(clientId), s);
  return { blocked, triesLeft: Math.max(0, maxTries - s.tries) };
}

module.exports = { isUnlocked, isBlocked, unlock, relock, registerFailedAttempt, getState };
