import urllib.request
import urllib.parse
import json
import logging
from logging.handlers import RotatingFileHandler
import gc
import os

# ==========================================
# CONFIGURAÇÕES
# ==========================================

# Use variáveis de ambiente por segurança
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_TOKEN"))
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Coordenadas para Várzea da Onça, Quixadá-CE
LATITUDE = "-4.9684"
LONGITUDE = "-39.0154"

# Envia alerta se a probabilidade for ACIMA de 5%
LIMIAR_ALERTA = 0

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "clima_telegram.log")

# ==========================================
# LOG
# ==========================================

logger = logging.getLogger("ClimaBot")
logger.setLevel(logging.INFO)

if not logger.handlers:
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=100000,
        backupCount=1,
        encoding="utf-8"
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter("%(levelname)s - %(message)s")
    )
    logger.addHandler(console_handler)


def enviar_telegram(mensagem):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.error("TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID não configurado.")
        return False

    url_telegram = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": mensagem,
        "parse_mode": "Markdown"
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            url_telegram,
            data=payload,
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=10) as response:
            resposta = response.read().decode("utf-8", errors="ignore")

            if response.status != 200:
                logger.error(f"Telegram retornou HTTP {response.status}: {resposta}")
                return False

        logger.info("Mensagem enviada para o Telegram.")
        return True

    except Exception as erro:
        logger.error(f"Erro ao enviar Telegram: {erro}")
        return False


def consultar_chuva():
    url_weather = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LATITUDE}"
        f"&longitude={LONGITUDE}"
        "&hourly=precipitation_probability"
        "&timezone=America%2FFortaleza"
        "&forecast_hours=3"
    )

    req = urllib.request.Request(
        url_weather,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(req, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))

    probabilidades = data.get("hourly", {}).get("precipitation_probability", [])
    horarios = data.get("hourly", {}).get("time", [])

    if len(probabilidades) < 3:
        raise RuntimeError(f"API retornou poucos dados: {probabilidades}")

    agora = probabilidades[0]
    prox_1h = probabilidades[1]
    prox_2h = probabilidades[2]

    max_prob = max(prox_1h, prox_2h)

    return {
        "agora": agora,
        "prox_1h": prox_1h,
        "prox_2h": prox_2h,
        "max_prob": max_prob,
        "horarios": horarios
    }


def main():
    try:
        dados = consultar_chuva()

        max_prob = dados["max_prob"]

        logger.info(
            f"Probabilidades: agora={dados['agora']}%, "
            f"1h={dados['prox_1h']}%, "
            f"2h={dados['prox_2h']}%, "
            f"máxima={max_prob}%"
        )

        # Envia TODA VEZ que rodar e estiver acima de 5%
        if max_prob > LIMIAR_ALERTA:
            mensagem = (
                "⚠️ *Alerta de Chuva!*\n"
                f"Probabilidade máxima nas próximas 2 horas: *{max_prob}%*.\n\n"
                f"Agora: {dados['agora']}%\n"
                f"Próxima hora: {dados['prox_1h']}%\n"
                f"Daqui a 2 horas: {dados['prox_2h']}%\n\n"
                "Local: Várzea da Onça, Quixadá-CE."
            )

            if enviar_telegram(mensagem):
                logger.info(f"Alerta enviado. Probabilidade máxima: {max_prob}%")
            else:
                logger.error("Alerta detectado, mas o envio pelo Telegram falhou.")

        else:
            logger.info(
                f"Sem alerta. Probabilidade máxima {max_prob}% não está acima de {LIMIAR_ALERTA}%."
            )

    except Exception as erro:
        logger.error(f"Falha na automação: {erro}")

    finally:
        gc.collect()


if __name__ == "__main__":
    main()
