from flask import Flask, request
import requests
import os

app = Flask(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

OPENAI_URL = "https://api.openai.com/v1/responses"


@app.route("/", methods=["GET"])
def home():
    return "Bot online", 200


@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        print("GET WEBHOOK")
        print("mode:", mode)
        print("token:", token)
        print("VERIFY_TOKEN:", VERIFY_TOKEN)
        print("challenge:", challenge)

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

    print("OPENAI STATUS:", response.status_code)
    print("OPENAI BODY:", response.text)

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

    response = requests.post(url, headers=headers, json=payload, timeout=30)
    print("WHATSAPP STATUS:", response.status_code)
    print("WHATSAPP BODY:", response.text)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)