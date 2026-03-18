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
Você ajuda com agenda, tarefas, rotina de trabalho, manutenção predial, engenharia e organização.
Responda em português do Brasil.
Seja claro, direto, útil e profissional.
Nunca diga que não tem acesso à agenda se a pergunta puder ser respondida pelo fluxo de agenda do sistema.
Se não souber algo, diga com honestidade.
"""

# =========================
# UTIL
# =========================
def agora_sp():
    return datetime.now(TIMEZONE)

def remover_acentos_basico(texto: str) -> str:
    mapa = str.maketrans(
        "áàâãäéèêëíìîïóòôõöúùûüçÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ",
        "aaaaaeeeeiiiiooooouuuucAAAAAEEEEIIIIOOOOOUUUUC"
    )
    return texto.translate(mapa)

def normalizar(texto: str) -> str:
    return remover_acentos_basico(texto.lower().strip())

# =========================
# TAREFAS
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
    next_id = max([t["id"] for t in tasks], default=0) + 1
    item = {
        "id": next_id,
        "texto": texto.strip(),
        "status": "pendente",
        "criada_em": agora_sp().strftime("%d/%m/%Y %H:%M"),
    }
    tasks.append(item)
    save_tasks(tasks)
    return item

def complete_task(task_id):
    tasks = load_tasks()
    for task in tasks:
        if task["id"] == task_id:
            task["status"] = "concluída"
            save_tasks(tasks)
            return task
    return None

def formatar_tarefas(tasks):
    if not tasks:
        return "Você não tem tarefas cadastradas no momento."

    linhas = ["Suas tarefas:"]
    for task in tasks:
        status = "✅" if task["status"] == "concluída" else "🕒"
        linhas.append(f'{task["id"]}. {status} {task["texto"]}')
    return "\n".join(linhas)

# =========================
# GOOGLE CALENDAR
# =========================
def get_calendar_service():
    if not GOOGLE_TOKEN:
        raise ValueError("GOOGLE_TOKEN não configurado.")

    try:
        token_info = json.loads(GOOGLE_TOKEN)
    except json.JSONDecodeError:
        raise ValueError("GOOGLE_TOKEN mal formatado.")

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

def listar_eventos_intervalo(inicio_dt, fim_dt):
    service = get_calendar_service()

    eventos = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=inicio_dt.isoformat(),
            timeMax=fim_dt.isoformat(),
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
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": texto_usuario},
        ],
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()

        if data.get("output_text"):
            return data["output_text"].strip()

        partes = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    partes.append(content.get("text", ""))

        texto = "\n".join(partes).strip()
        return texto or "Não consegui gerar uma resposta agora."
    except Exception as e:
        return f"Não consegui consultar a IA agora: {str(e)}"

# =========================
# INTERPRETAÇÃO DE DATA
# =========================
def proxima_data_por_dia_semana(texto_normalizado):
    hoje = agora_sp()

    dias_semana = {
        "segunda": 0,
        "terca": 1,
        "terça": 1,
        "quarta": 2,
        "quinta": 3,
        "sexta": 4,
        "sabado": 5,
        "sábado": 5,
        "domingo": 6,
    }

    for nome, numero in dias_semana.items():
        if nome in texto_normalizado:
            dias_ate = (numero - hoje.weekday()) % 7
            if dias_ate == 0:
                dias_ate = 7
            return hoje + timedelta(days=dias_ate)
    return None

def extrair_data_referencia(texto):
    texto_n = normalizar(texto)
    hoje = agora_sp()

    if "amanha" in texto_n:
        return hoje + timedelta(days=1)

    if "hoje" in texto_n:
        return hoje

    data_match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", texto_n)
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

    data_semana = proxima_data_por_dia_semana(texto_n)
    if data_semana:
        return data_semana

    return None

def extrair_hora(texto):
    texto_n = normalizar(texto)
    hora_match = re.search(r"(?:as|às)\s+(\d{1,2})(?::(\d{2}))?", texto_n)
    if not hora_match:
        return None

    hora = int(hora_match.group(1))
    minuto = int(hora_match.group(2)) if hora_match.group(2) else 0

    if 0 <= hora <= 23 and 0 <= minuto <= 59:
        return hora, minuto
    return None

# =========================
# INTENÇÕES
# =========================
def detectar_intencao(texto):
    texto_n = normalizar(texto)

    # tarefas
    if texto_n.startswith("criar tarefa "):
        return "criar_tarefa"

    if texto_n.startswith("adicionar tarefa "):
        return "criar_tarefa"

    if texto_n.startswith("me lembra de "):
        return "criar_tarefa"

    if texto_n.startswith("lembrar de "):
        return "criar_tarefa"

    if texto_n in ["listar tarefas", "lista de tarefas", "quais tarefas eu tenho?", "quais tarefas eu tenho", "minhas tarefas"]:
        return "listar_tarefas"

    if texto_n.startswith("concluir tarefa "):
        return "concluir_tarefa"

    # agenda - consulta
    sinais_consulta_agenda = [
        "agenda",
        "compromisso",
        "compromissos",
        "reuniao",
        "reunião",
        "tenho",
        "livre",
        "marcado",
        "marcada",
        "agendada",
        "agendado",
    ]

    perguntas_consulta = [
        "tenho reuniao",
        "tenho reunião",
        "tenho algo",
        "o que tenho",
        "quais compromissos",
        "estou livre",
        "tem algo",
        "tem reuniao",
        "tem reunião",
    ]

    if any(p in texto_n for p in perguntas_consulta):
        if any(ref in texto_n for ref in ["hoje", "amanha", "agenda", "/", "segunda", "terca", "terça", "quarta", "quinta", "sexta", "sabado", "sábado", "domingo"]):
            return "consultar_agenda"

    if texto_n.startswith("agenda"):
        return "consultar_agenda"

    # agenda - criação
    sinais_criar_evento = [
        "agendar",
        "agende",
        "marcar",
        "marque",
        "criar evento",
        "crie evento",
        "reuniao",
        "reunião",
        "vistoria",
    ]

    if any(s in texto_n for s in sinais_criar_evento) and extrair_hora(texto) and extrair_data_referencia(texto):
        return "criar_evento"

    # fallback
    return "ia"

# =========================
# TAREFAS - interpretação
# =========================
def interpretar_criar_tarefa(texto):
    texto_n = normalizar(texto)

    prefixos = [
        "criar tarefa ",
        "adicionar tarefa ",
        "me lembra de ",
        "lembrar de ",
    ]

    for prefixo in prefixos:
        if texto_n.startswith(prefixo):
            return texto[len(prefixo):].strip()

    return None

def interpretar_concluir_tarefa(texto):
    texto_n = normalizar(texto)
    match = re.search(r"concluir tarefa (\d+)", texto_n)
    if match:
        return int(match.group(1))
    return None

# =========================
# AGENDA - interpretação
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

    texto_limpo = re.sub(r"^\s*(uma|um|na|no)\s*", "", texto_limpo, flags=re.IGNORECASE)
    texto_limpo = re.sub(r"\s+", " ", texto_limpo).strip(" -,:;")

    if not texto_limpo:
        return "Compromisso"

    return texto_limpo[:1].upper() + texto_limpo[1:]

def interpretar_criar_evento(texto):
    data_ref = extrair_data_referencia(texto)
    hora_ref = extrair_hora(texto)

    if not data_ref or not hora_ref:
        return None

    hora, minuto = hora_ref
    inicio = data_ref.replace(hour=hora, minute=minuto, second=0, microsecond=0)
    fim = inicio + timedelta(hours=1)
    titulo = extrair_titulo_evento(texto)

    return titulo, inicio, fim

def interpretar_consulta_agenda(texto):
    data_ref = extrair_data_referencia(texto)
    if data_ref:
        return data_ref

    texto_n = normalizar(texto)
    if "agenda" in texto_n or "tenho" in texto_n or "compromisso" in texto_n:
        return agora_sp()

    return None

# =========================
# FORMATAÇÃO
# =========================
def formatar_data_relativa(data_ref):
    hoje = agora_sp().date()
    amanha = hoje + timedelta(days=1)

    if data_ref.date() == hoje:
        return "hoje"
    if data_ref.date() == amanha:
        return "amanhã"
    return data_ref.strftime("%d/%m/%Y")

def formatar_eventos(eventos, data_ref):
    ref_txt = formatar_data_relativa(data_ref)

    if not eventos:
        return f"Você não tem compromissos agendados para {ref_txt}."

    if len(eventos) == 1:
        ev = eventos[0]
        titulo = ev.get("summary", "Sem título")
        inicio = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date")

        if "T" in str(inicio):
            dt = datetime.fromisoformat(inicio.replace("Z", "+00:00")).astimezone(TIMEZONE)
            hora_txt = dt.strftime("%H:%M")
            return f"Para {ref_txt}, você tem 1 compromisso agendado: {titulo}, às {hora_txt}."
        return f"Para {ref_txt}, você tem 1 compromisso de dia inteiro: {titulo}."

    linhas = [f"Para {ref_txt}, você tem {len(eventos)} compromissos:"]
    for i, ev in enumerate(eventos, start=1):
        titulo = ev.get("summary", "Sem título")
        inicio = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date")

        if "T" in str(inicio):
            dt = datetime.fromisoformat(inicio.replace("Z", "+00:00")).astimezone(TIMEZONE)
            hora_txt = dt.strftime("%H:%M")
        else:
            hora_txt = "Dia inteiro"

        linhas.append(f"{i}. {hora_txt} - {titulo}")

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

@app.route("/health", methods=["GET"])
def health():
    return "ok", 200

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
        intencao = detectar_intencao(texto)

        # 1) criar tarefa
        if intencao == "criar_tarefa":
            descricao = interpretar_criar_tarefa(texto)
            if not descricao:
                resposta = "Me diga a tarefa após o comando. Ex.: criar tarefa comprar material"
            else:
                task = add_task(descricao)
                resposta = f'Tarefa criada com sucesso: {task["texto"]}'
            enviar_mensagem_whatsapp(numero, resposta)
            return "ok", 200

        # 2) listar tarefas
        if intencao == "listar_tarefas":
            resposta = formatar_tarefas(load_tasks())
            enviar_mensagem_whatsapp(numero, resposta)
            return "ok", 200

        # 3) concluir tarefa
        if intencao == "concluir_tarefa":
            task_id = interpretar_concluir_tarefa(texto)
            if task_id is None:
                resposta = "Me diga o número da tarefa. Ex.: concluir tarefa 2"
            else:
                task = complete_task(task_id)
                resposta = (
                    f'Tarefa {task_id} concluída com sucesso.'
                    if task
                    else f'Não encontrei a tarefa {task_id}.'
                )
            enviar_mensagem_whatsapp(numero, resposta)
            return "ok", 200

        # 4) consultar agenda
        if intencao == "consultar_agenda":
            try:
                data_ref = interpretar_consulta_agenda(texto)
                inicio = data_ref.replace(hour=0, minute=0, second=0, microsecond=0)
                fim = inicio + timedelta(days=1)
                eventos = listar_eventos_intervalo(inicio, fim)
                resposta = formatar_eventos(eventos, data_ref)
            except Exception as e:
                resposta = f"Não consegui consultar sua agenda agora: {str(e)}"

            enviar_mensagem_whatsapp(numero, resposta)
            return "ok", 200

        # 5) criar evento
        if intencao == "criar_evento":
            try:
                evento = interpretar_criar_evento(texto)
                if not evento:
                    resposta = "Não consegui entender a data e a hora. Ex.: agendar reunião amanhã às 10"
                else:
                    titulo, inicio, fim = evento
                    link = criar_evento_calendar(titulo, inicio, fim)
                    resposta = (
                        f"{titulo} agendada com sucesso para "
                        f"{inicio.strftime('%d/%m/%Y')} das {inicio.strftime('%H:%M')} às {fim.strftime('%H:%M')}.\n"
                        f"Link: {link}"
                    )
            except Exception as e:
                resposta = f"Não consegui criar o evento na agenda: {str(e)}"

            enviar_mensagem_whatsapp(numero, resposta)
            return "ok", 200

        # 6) IA geral
        resposta = perguntar_openai(texto)
        enviar_mensagem_whatsapp(numero, resposta)
        return "ok", 200

    except Exception as e:
        print("ERRO NO WEBHOOK:", str(e))
        return "erro interno", 500

if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=porta)
