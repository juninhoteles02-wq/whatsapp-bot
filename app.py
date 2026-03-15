from flask import Flask, request
import requests

app = Flask(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
OPENAI_URL = "https://api.openai.com/v1/responses"
WHATSAPP_URL = f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages"


@app.route("/webhook", methods=["GET", "POST"])
def webhook():

    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        if mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge, 200
        else:
            return "Token inválido", 403


    data = request.get_json()
    print("WEBHOOK RECEBIDO:", data)

    try:
        value = data["entry"][0]["changes"][0]["value"]

        if "messages" not in value:
            print("Evento sem mensagem")
            return "ok", 200

        message = value["messages"][0]["text"]["body"]
        number = value["messages"][0]["from"]

        reply = ask_openai(message)

        send_message(number, reply)

    except Exception as e:
        import traceback
        print("ERRO:", e)
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
    print("OPENAI RESPOSTA:", response.text)

    try:
        result = response.json()
    except:
        return "Erro ao interpretar resposta da OpenAI."

    if response.status_code != 200:
        return result.get("error", {}).get("message", "Erro na OpenAI.")

    try:
        return result["output"][0]["content"][0]["text"]
    except:
        return "Formato inesperado da resposta da IA."


def send_message(to, text):

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

    response = requests.post(
        WHATSAPP_URL,
        headers=headers,
        json=payload
    )

    print("WHATSAPP STATUS:", response.status_code)
    print("WHATSAPP RESPOSTA:", response.text)


if __name__ == "__main__":
    app.run(port=5000)