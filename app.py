from flask import Flask, request
import requests
import os
import re
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build

app = Flask(__name__)

# =========================
# CONFIG
# =========================
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

GOOGLE_TOKEN = os.getenv("GOOGLE_TOKEN")
SCOPES = ["https://www.googleapis.com/auth/calendar"]

TIMEZONE = ZoneInfo("America/Sao_Paulo")
TASKS_FILE = "tasks.json"

SYSTEM_PROMPT = """
Você é o EngFlow, assistente profissional do Junior.
Seu papel é ajudar com engenharia, manutenção predial, organização, produtividade e respostas úteis do dia a dia.
Responda em português do Brasil.
Seja direto, profissional e claro.
Quando for apropriado, organize em poucos tópicos.
Não invente informações.
"""

# =========================
# ARQUIVO DE TAREFAS
# =========================
def load_tasks():
    if not os.path.exists(TASKS_FILE):
        return []
    try:
        with open(TASKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_tasks(tasks):
    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)

def add_task(texto):
    tasks = load_tasks()
    task_id = len(tasks) + 1
    item = {
        "id": task_id,
        "texto": texto.strip(),
        "status": "pendente",
        "criada_em": datetime.now(TIMEZONE).strftime("%d/%m/%Y %H:%M")
    }
    tasks.append(item)
    save_tasks(tasks)
    return item

def list_tasks():
    return load_tasks()

def complete_task(task_id):
    tasks = load_tasks()
    for task in tasks:
        if task["id"] == task_id:
            task["status"] = "concluída"
            save_tasks(tasks)
            return task
    return None

# =========================
# GOOGLE CALENDAR
# =========================
def get_calendar_service():
    if not GOOGLE_TOKEN:
        raise ValueError("Variável GOOGLE_TOKEN não encontrada no ambiente.")

    try:
        token_info = json.loads(GOOGLE_TOKEN)
    except json.JSONDecodeError:
        raise ValueError("GOOGLE_TOKEN está mal formatado.")

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

def listar_eventos_do_dia(data_base):
    service = get_calendar_service()

    inicio = datetime(
        data_base.year, data_base.month, data_base.day, 0, 0, 0, tzinfo=TIMEZONE
    )
    fim = inicio + timedelta(days=1)

    eventos = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=inicio.isoformat(),
            timeMax=fim.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    return eventos.get("items", [])

# =========================
# OPENAI
# =========================
def perguntar_openai(texto_usuario):
    if not OPENAI_API_KEY:
        return "A chave da OpenAI não está configurada no ambiente."

    url = "https://api.openai.com/v1/responses"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "gpt-4.1-mini",
        "input": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": texto_usuario
            }
        ]
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()

        # Tenta formato simples
        if "output_text" in data and data["output_text"]:
            return data["output_text"].strip()

        # Fallback de parsing
        output = data.get("output", [])
        partes = []
        for item in output:
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    partes.append(content.get("text", ""))
        texto = "\n".join(partes).strip()

        return texto or "Não consegui gerar uma resposta agora."
    except Exception as e:
        return f"Não consegui consultar a IA agora: {str(e)}"

# =========================
# INTERPRETAÇÃO
# =========================
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
        r"^\s*(agendar|agende|marcar|marque|criar|crie|evento|reunião|reuniao|vistoria)\s*",
        "",
        texto_limpo,
        flags=re.IGNORECASE,
    )

    texto_limpo = re.sub(r"^\s*(uma|um)\s*", "", texto_limpo, flags=re.IGNORECASE)
    texto_limpo = re.sub(r"\s+", " ", texto_limpo).strip(" -,:;")

    if not texto_limpo:
        return "Compromisso agendado pelo WhatsApp"

    return texto_limpo[:1].upper() + texto_limpo[1:]

def interpretar_pedido_reuniao(texto):
    texto_lower = texto.lower().strip()
    agora = datetime.now(TIMEZONE)

    hora_match = re.search(r"(?:às|as)\s+(\d{1,2})(?::(\d{2}))?", texto_lower)
    if not hora_match:
        return None

    hora = int(hora_match.group(1))
    minuto = int(hora_match.group(2)) if hora_match.group(2) else 0

    if hora < 0 or hora > 23 or minuto < 0 or minuto > 59:
        return None

    data_evento = None

    if "hoje" in texto_lower:
        data_evento = agora
    elif "amanhã" in texto_lower or "amanha" in texto_lower:
        data_evento = agora + timedelta(days=1)
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
                dias_ate = (numero_dia - agora.weekday()) % 7
                if dias_ate == 0:
                    dias_ate = 7
                data_evento = agora + timedelta(days=dias_ate)
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
                data_evento = datetime(ano, mes, dia, tzinfo=TIMEZONE)
            except ValueError:
                return None

    if data_evento is None:
        return None

    inicio = data_evento.replace(hour=hora, minute=minuto, second=0, microsecond=0)
    fim = inicio + timedelta(hours=1)
    titulo = extrair_titulo_evento(texto)

    return titulo, inicio, fim

def interpretar_consulta_agenda(texto):
    texto_lower = texto.lower().strip()
    agora = datetime.now(TIMEZONE)

    if not texto_lower.startswith("agenda"):
        return None

    if "hoje" in texto_lower:
        return agora

    if "amanhã" in texto_lower or "amanha" in texto_lower:
        return agora + timedelta(days=1)

    data_match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", texto_lower)
    if data_match:
        dia = int(data_match.group(1))
        mes = int(data_match.group(2))
        ano = int(data_match.group(3))
        if ano < 100:
            ano += 2000
        try:
            return datetime(ano, mes, dia, tzinfo=TIMEZONE)
        except ValueError:
            return None

    # "agenda" sozinho = hoje
    return agora

def interpretar_tarefa(texto):
    texto_lower = texto.lower().strip()

    if texto_lower.startswith("criar tarefa "):
        return ("criar", texto[13:].strip())

    if texto_lower == "listar tarefas":
        return ("listar", None)

    if texto_lower.startswith("concluir tarefa "):
        numero = re.search(r"concluir tarefa (\d+)", texto_lower)
        if numero:
            return ("concluir", int(numero.group(1)))

    return None

def formatar_eventos(eventos, data_ref):
    data_str = data_ref.strftime("%d/%m/%Y")
    if not eventos:
        return f"Não encontrei compromissos na agenda para {data_str}."

    linhas = [f"Compromissos em {data_str}:"]
    for i, ev in enumerate(eventos, start=1):
        inicio = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date")
        titulo = ev.get("summary", "Sem título")

        hora_txt = ""
        if "T" in str(inicio):
            try:
                dt = datetime.fromisoformat(inicio.replace("Z", "+00:00")).astimezone(TIMEZONE)
                hora_txt = dt.strftime("%H:%M")
            except Exception:
                hora_txt = str(inicio)
        else:
            hora_txt = "Dia inteiro"

        linhas.append(f"{i}. {hora_txt} - {titulo}")

    return "\n".join(linhas)

def formatar_tarefas(tasks):
    if not tasks:
        return "Você não tem tarefas cadastradas."

    linhas = ["Suas tarefas:"]
    for task in tasks:
        status = "✅" if task["status"] == "concluída" else "🕒"
        linhas.append(f'{task["id"]}. {status} {task["texto"]}')
    return "\n".join(linhas)

# =========================
# WHATSAPP
# =========================
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
        "text": {"body": mensagem[:4000]},
    }

    response = requests.post(url, headers=headers, json=payload, timeout=30)
    print("WHATSAPP STATUS:", response.status_code)
    print("WHATSAPP BODY:", response.text)
    return response

# =========================
# ROTAS
# =========================
@app.route("/", methods=["GET"])
def home():
    return "EngFlow online", 200

@app.route("/teste", methods=["GET"])
def teste():
    return "nova versao funcionando", 200

@app.route("/webhook", methods=["GET"])
def verificar_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200

    return "Token inválido", 403

@app.route("/webhook", methods=["POST"])
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
        texto = mensagem["text"]["body"].strip()

        # 1) tarefas
        comando_tarefa = interpretar_tarefa(texto)
        if comando_tarefa:
            acao, dado = comando_tarefa

            if acao == "criar":
                if not dado:
                    resposta = "Me diga a tarefa após 'criar tarefa'. Ex.: criar tarefa comprar material"
                else:
                    task = add_task(dado)
                    resposta = f'Tarefa criada com sucesso.\nID: {task["id"]}\nDescrição: {task["texto"]}'
                enviar_mensagem_whatsapp(numero, resposta)
                return "ok", 200

            if acao == "listar":
                resposta = formatar_tarefas(list_tasks())
                enviar_mensagem_whatsapp(numero, resposta)
                return "ok", 200

            if acao == "concluir":
                task = complete_task(dado)
                resposta = (
                    f'Tarefa {dado} concluída com sucesso.'
                    if task
                    else f'Não encontrei a tarefa {dado}.'
                )
                enviar_mensagem_whatsapp(numero, resposta)
                return "ok", 200

        # 2) consulta de agenda
        data_consulta = interpretar_consulta_agenda(texto)
        if data_consulta:
            try:
                eventos = listar_eventos_do_dia(data_consulta)
                resposta = formatar_eventos(eventos, data_consulta)
            except Exception as e:
                resposta = f"Não consegui consultar a agenda: {str(e)}"

            enviar_mensagem_whatsapp(numero, resposta)
            return "ok", 200

        # 3) criação de evento
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

            enviar_mensagem_whatsapp(numero, resposta)
            return "ok", 200

        # 4) IA geral
        resposta = perguntar_openai(texto)
        enviar_mensagem_whatsapp(numero, resposta)
        return "ok", 200

    except Exception as e:
        print("ERRO NO WEBHOOK:", str(e))
        return "erro interno", 500

if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=porta)
