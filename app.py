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

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def get_calendar_service():
    if not os.path.exists("token.json"):
        raise FileNotFoundError("token.json não encontrado.")
    if not os.path.exists("credentials.json"):
        raise FileNotFoundError("credentials.json não encontrado.")

    creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())

        with open("token.json", "w", encoding="utf-8") as token_file:
            token_file.write(creds.to_json())

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

    texto_limpo = re.sub(
        r"\s+(?:às|as)\s+\d{1,2}(?::\d{2})?\s*$",
        "",
        texto_limpo,
        flags=re.IGNORECASE,
    )

    expressoes_data = [
        r"\bhoje\b",
        r"\bamanhã\b",
        r"\bamanha\b",
        r"\bsegunda\b",
        r"\bterça\b",
        r"\bterca\b",
        r"\bquarta\b",
        r"\bquinta\b",
        r"\bsexta\b",
        r"\bsábado\b",
        r"\bsabado\b",
        r"\bdomingo\b",
        r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    ]

    for exp in expressoes_data:
        texto_limpo = re.sub(exp, "", texto_limpo, flags=re.IGNORECASE)

    texto_limpo = re.sub(
        r"^\s*(agendar|agende|marcar|marque|criar|crie|evento|reunião|reuniao)\s*",
        "",
        texto_limpo,
        flags=re.IGNORECASE,
    )
    texto_limpo = re.sub(r"^\s*(uma|um)\s*", "", texto_limpo, flags=re.IGNORECASE)

    texto_limpo = re.sub(r"\s+", " ", texto_limpo).strip(" -,:;")

    if not texto_limpo:
        return "Reunião agendada pelo WhatsApp"

    return texto_limpo[:1].upper() + texto_limpo[1:]


def interpretar_pedido_reuniao(texto):
    texto_lower = texto.lower().strip()
    hoje = datetime.now()

    hora_match = re.search(r"(?:às|as)\s+(\d{1,2})(?::(\d{2}))?", texto_lower)
    if not hora_match:
        return None

    hora = int(hora_match.group(1))
    minuto = int(hora_match.group(2)) if hora_match.group(2) else 0

    if hora < 0 or hora > 23 or minuto < 0 or minuto > 59:
        return None

    data_evento = None

    if "hoje" in texto_lower:
        data_evento = hoje
    elif "amanhã" in texto_lower or "amanha" in texto_lower:
        data_evento = hoje + timedelta(days=1)
    else:
        dias_semana = {
            "segunda": 0,
            "terça": 1,
            "terca": 1,
            "quarta": 2,
            "quinta": 3,
            "sexta": 4,
            "sábado": 5,
            "sabado": 5,
            "domingo": 6,
        }

        for nome_dia, numero_dia in dias_semana.items():
            if nome_dia in texto_lower:
                dias_ate = (numero_dia - hoje.weekday()) % 7
                if dias_ate == 0:
                    dias_ate = 7
                data_evento = hoje + timedelta(days=dias_ate)
                break

    if data_evento is None:
        data_match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", texto_lower)
        if data_match:
            dia = int(data_match.group(1))
            mes = int(data_match.group(2))
            ano = int(data_match.group(3))

            if ano < 100:
                ano += 2000

            try:
                data_evento = datetime(ano, mes, dia)
            except ValueError:
                return None

    if data_evento is None:
        return None

    try:
        inicio = data_evento.replace(hour=hora, minute=minuto, second=0, microsecond=0)
    except ValueError:
        return None

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
    return response


@app.route("/", methods=["GET"])
def home():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200

    return "Servidor do bot rodando com sucesso!", 200


@app.route("/", methods=["POST"])
def receber_mensagem():
    try:
        data = request.get_json()
        print("WEBHOOK RECEBIDO:")
        print(json.dumps(data, indent=2, ensure_ascii=False))

        if not data or "entry" not in data:
            return "ok", 200

        entry = data["entry"][0]
        changes = entry.get("changes", [])
        if not changes:
            return "ok", 200

        value = changes[0].get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return "ok", 200

        mensagem = messages[0]
        if mensagem.get("type") != "text":
            return "ok", 200

        numero = mensagem["from"]
        texto = mensagem["text"]["body"]

        pedido_reuniao = interpretar_pedido_reuniao(texto)

        if pedido_reuniao:
            try:
                titulo, inicio, fim = pedido_reuniao
                link = criar_evento_calendar(titulo, inicio, fim)
                resposta = (
                    f"Evento criado com sucesso na sua agenda.\n"
                    f"Título: {titulo}\n"
                    f"Início: {inicio.strftime('%d/%m/%Y %H:%M')}\n"
                    f"Fim: {fim.strftime('%d/%m/%Y %H:%M')}\n"
                    f"Link: {link}"
                )
            except Exception as e:
                resposta = f"Não consegui criar o evento na agenda: {str(e)}"
        else:
            resposta = (
                "Para agendar, use exemplos como:\n"
                "- agendar reunião hoje às 14\n"
                "- agendar reunião com Rafael amanhã às 9:30\n"
                "- agendar vistoria sexta às 16\n"
                "- agendar reunião 25/03/2026 às 10"
            )

        enviar_mensagem_whatsapp(numero, resposta)
        return "ok", 200

    except Exception as e:
        print("ERRO NO WEBHOOK:", str(e))
        return "erro interno", 500


if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=porta)
