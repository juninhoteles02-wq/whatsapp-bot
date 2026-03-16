from flask import Flask, request, jsonify
import requests
import os
import re
from datetime import datetime, timedelta

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

app = Flask(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

OPENAI_URL = "https://api.openai.com/v1/responses"

SCOPES = ["https://www.googleapis.com/auth/calendar"]


# =========================
# WEBHOOK (VALIDAÇÃO META)
# =========================
@app.route("/", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        if mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge, 200
        else:
            return "Erro de verificação", 403

    if request.method == "POST":
        data = request.get_json()

        try:
            message = data["entry"][0]["changes"][0]["value"]["messages"][0]
            text = message["text"]["body"]
            phone = message["from"]

            resposta = "Teste funcionando 🔥"

            enviar_resposta(phone, resposta)

        except:
            pass

        return "OK", 200


# =========================
# PROCESSAMENTO DE TEXTO
# =========================
def processar_mensagem(texto):
    texto = texto.lower()

    hoje = datetime.now()

    if "amanhã" in texto:
        data = hoje + timedelta(days=1)
    elif "hoje" in texto:
        data = hoje
    elif "sexta" in texto:
        dias_ahead = (4 - hoje.weekday()) % 7
        data = hoje + timedelta(days=dias_ahead)
    else:
        match = re.search(r"\d{1,2}/\d{1,2}/\d{4}", texto)
        if match:
            data = datetime.strptime(match.group(), "%d/%m/%Y")
        else:
            return "Não entendi a data. Use: 25/03/2026 ou 'amanhã'."

    return f"Evento entendido para {data.strftime('%d/%m/%Y')}"


# =========================
# ENVIO WHATSAPP
# =========================
def enviar_resposta(numero, mensagem):
    url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": numero,
        "type": "text",
        "text": {"body": mensagem}
    }

    requests.post(url, headers=headers, json=payload)


# =========================
# ROTA TESTE
# =========================
@app.route("/test")
def test():
    return "Servidor rodando", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
