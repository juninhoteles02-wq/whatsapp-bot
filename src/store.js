// Armazenamento simples em arquivos JSON, para não depender de um banco de
// dados no início. Se o volume crescer, trocar por um banco de verdade
// (Postgres, SQLite etc.) é só reimplementar estas duas funções.

const fs = require("fs");
const path = require("path");

const DATA_DIR = path.resolve(process.cwd(), "data");

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function readJSON(relPath, fallback) {
  const full = path.join(DATA_DIR, relPath);
  try {
    return JSON.parse(fs.readFileSync(full, "utf8"));
  } catch {
    return fallback;
  }
}

function writeJSON(relPath, data) {
  const full = path.join(DATA_DIR, relPath);
  ensureDir(path.dirname(full));
  fs.writeFileSync(full, JSON.stringify(data, null, 2), "utf8");
}

module.exports = { readJSON, writeJSON };
