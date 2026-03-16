from flask import Flask, request
import requests
import os
import re
from datetime import datetime, timedelta

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

app = Flask(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

OPENAI_URL = "https://api.openai.com/v1/responses"

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def get_calendar_service():
    creds = None

    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=8080)

        with open("token.json", "w") as token:
            token.write(creds.to_json())

    service = build("calendar", "v3", credentials=creds)
    return service


def criar_evento(titulo, data, hora):
    service = get_calendar_service()

    inicio = datetime.strptime(f"{data} {hora}", "%Y-%m-%d %H:%M")
    fim = inicio + timedelta(hours=1)

    evento = {
        "summary": titulo,
        "start": {
            "dateTime": inicio.isoformat(),
            "timeZone": "America/Sao_Paulo",
        },
        "end": {
            "dateTime": fim.isoformat(),
            "timeZone": "America/Sao_Paulo",
        },
    }

    service.events().insert(calendarId="primary", body=evento).execute()

    return f"Evento '{titulo}' criado para {inicio.strftime('%d/%m/%Y às %H:%M')}"


def tentar_criar_evento(message):
    texto = message.lower()

    if "criar reunião" not in texto:
        return None

    try:
        if "amanhã" in texto:
            data = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            data = datetime.now().strftime("%Y-%m-%d")

        hora_match = re.search(r'(\d{1,2})h', texto)

        if not hora_match:
            return None

        hora = hora_match.group(1)
        hora = f"{int(hora):02d}:00"

        titulo = "Reunião"

        if "com" in texto:
            pessoa = texto.split("com")[-1].strip().title()
            titulo = f"Reunião com {pessoa}"

        return criar_evento(titulo, data, hora)

    except Exception as e:
        print("ERRO EVENTO:", e)
        return "Não consegui criar o evento."


@app.route("/", methods=["GET"])
def home():
    return "Bot online", 200


@app.route("/webhook", methods=["GET", "POST"])
def webhook():

    if request.method == "GET":

        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        if mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge, 200

        return "Token inválido", 403

    data = request.get_json(silent=True) or {}
    print("WEBHOOK RECEBIDO:", data)

    try:

        value = data["entry"][0]["changes"][0]["value"]

        if "messages" not in value:
            return "ok", 200

        incoming = value["messages"][0]

        if incoming.get("type") != "text":
            return "ok", 200

        message = incoming["text"]["body"]
        number = incoming["from"]

        evento = tentar_criar_evento(message)

        if evento:
            send_message(number, evento)
        else:
            reply = ask_openai(message)
            send_message(number, reply)

    except Exception as e:
        import traceback
        print("ERRO:", repr(e))
        traceback.print_exc()

    return "ok", 200


def ask_openai(message):

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "gpt-4.1-mini",
        "input": message
    }

    response = requests.post(
        OPENAI_URL,
        headers=headers,
        json=payload,
        timeout=30
    )

    try:
        result = response.json()
    except Exception:
        return "Erro ao interpretar resposta da OpenAI."

    if response.status_code != 200:
        return result.get("error", {}).get("message", "Erro na OpenAI.")

    try:
        return result["output"][0]["content"][0]["text"][:1500]
    except Exception:
        return "Formato inesperado da resposta da IA."


def send_message(to, text):

    url = f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }

    response = requests.post(url, headers=headers, json=payload)

    print("WHATSAPP STATUS:", response.status_code)
    print("WHATSAPP BODY:", response.text)


if __name__ == "__main__":

    try:
        get_calendar_service()
        print("Google Agenda conectada com sucesso!")
    except Exception as e:
        print("Erro Google Agenda:", e)

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)