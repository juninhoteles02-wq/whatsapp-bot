from flask import Flask, request
import requests
import os
import re
import json
from datetime import datetime, timedelta

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build

app = Flask(__name__)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")
GOOGLE_TOKEN = os.getenv("GOOGLE_TOKEN")

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def get_calendar_service():
    if not GOOGLE_CREDENTIALS:
        raise ValueError("Variável GOOGLE_CREDENTIALS não encontrada no Render.")

    if not GOOGLE_TOKEN:
        raise ValueError("Variável GOOGLE_TOKEN não encontrada no Render.")

    token_info = json.loads(GOOGLE_TOKEN)
    creds = Credentials.from_authorized_user_info(token_info, SCOPES)

    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())

    return build("calendar", "v3", credentials=creds)


def criar_evento_calendar(titulo, inicio_dt, fim_dt):
    service = get_calendar_service()

    evento = {
        "summary": titulo,
        "start": {
            "dateTime": inicio_dt.isoformat(),
            "timeZone": "America/Sao_Paulo",
        },
        "end": {
            "dateTime": fim_dt.isoformat(),
            "timeZone": "America/Sao_Paulo",
        },
    }

    criado = service.events().insert(calendarId="primary", body=evento).execute()
    return criado.get("htmlLink")


def extrair_titulo_evento(texto):
    texto_limpo = texto.strip()

    texto_limpo = re.sub(r"\s+(?:às|as)\s+\d{1,2}(?::\d{2})?\s*$", "", texto_limpo, flags=re.IGNORECASE)

    expressoes_data = [
        r"\bhoje\b", r"\bamanhã\b", r"\bamanha\b",
        r"\bsegunda\b", r"\bterça\b", r"\bterca\b",
        r"\bquarta\b", r"\bquinta\b", r"\bsexta\b",
        r"\bsábado\b", r"\bsabado\b", r"\bdomingo\b",
        r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    ]

    for exp in expressoes_data:
        texto_limpo = re.sub(exp, "", texto_limpo, flags=re.IGNORECASE)

    texto_limpo = re.sub(r"^\s*(agendar|marcar|criar|evento|reunião|reuniao)\s*", "", texto_limpo, flags=re.IGNORECASE)
    texto_limpo = re.sub(r"^\s*(uma|um)\s*", "", texto_limpo, flags=re.IGNORECASE)
    texto_limpo = re.sub(r"\s+", " ", texto_limpo).strip(" -,:;")

    return texto_limpo.capitalize() if texto_limpo else "Reunião agendada"


def interpretar_pedido_reuniao(texto):
    texto_lower = texto.lower().strip()
    hoje = datetime.now()

    hora_match = re.search(r"(?:às|as)\s+(\d{1,2})(?::(\d{2}))?", texto_lower)
    if not hora_match:
        return None

    hora = int(hora_match.group(1))
    minuto = int(hora_match.group(2)) if hora_match.group(2) else 0

    data_evento = hoje if "hoje" in texto_lower else hoje + timedelta(days=1)

    inicio = data_evento.replace(hour=hora, minute=minuto, second=0, microsecond=0)
    fim = inicio + timedelta(hours=1)
    titulo = extrair_titulo_evento(texto)

    return titulo, inicio, fim


def enviar_mensagem_whatsapp(numero, mensagem):
    url = f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": numero,
        "type": "text",
        "text": {"body": mensagem},
    }

    response = requests.post(url, headers=headers, json=payload, timeout=30)
    print("WHATSAPP STATUS:", response.status_code)
    print("WHATSAPP BODY:", response.text)


# 🔥 TESTE SIMPLES
@app.route("/teste")
def teste():
    return "nova versao funcionando", 200


# HOME
@app.route("/", methods=["GET"])
def home():
    return "Servidor do bot rodando com sucesso!", 200


# VERIFICAÇÃO META
@app.route("/webhook", methods=["GET"])
def verificar_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200

    return "Token inválido", 403


# RECEBER MENSAGEM
@app.route("/webhook", methods=["POST"])
def receber_mensagem():
    try:
        data = request.get_json()
        print("WEBHOOK RECEBIDO:", data)

        entry = data["entry"][0]
        changes = entry["changes"][0]["value"]
        mensagem = changes["messages"][0]

        numero = mensagem["from"]
        texto = mensagem["text"]["body"]

        pedido = interpretar_pedido_reuniao(texto)

        if pedido:
            titulo, inicio, fim = pedido
            link = criar_evento_calendar(titulo, inicio, fim)
            resposta = f"Evento criado: {titulo}\n{link}"
        else:
            resposta = "Envie algo como: agendar reunião amanhã às 10"

        enviar_mensagem_whatsapp(numero, resposta)
        return "ok", 200

    except Exception as e:
        print("ERRO:", str(e))
        return "erro", 500


if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=porta)
