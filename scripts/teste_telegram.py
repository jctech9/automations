import os
import requests

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if not TOKEN or not CHAT_ID:
    print("ERRO: TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não configurados.")
    exit(1)

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

try:
    resposta = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": "✅ Token vindo do GitHub Actions funcionando!",
        },
        timeout=20,
    )
    
    resposta.raise_for_status()
    print("Mensagem enviada com sucesso.")
    
except requests.exceptions.RequestException as e:
    print(f"ERRO ao enviar mensagem: {e}")
    exit(1)