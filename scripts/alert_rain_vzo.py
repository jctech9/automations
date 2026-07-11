import logging
from logging.handlers import RotatingFileHandler
import os
import sys

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==========================================
# CONFIGURAÇÕES
# ==========================================

# Use variáveis de ambiente por segurança
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_TOKEN"))
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Coordenadas para Várzea da Onça, Quixadá-CE
LATITUDE = os.environ.get("RAIN_ALERT_LATITUDE", "-4.9684")
LONGITUDE = os.environ.get("RAIN_ALERT_LONGITUDE", "-39.0154")

# Envia alerta se a probabilidade for maior ou igual a 50%
LIMIAR_ALERTA = int(os.environ.get("RAIN_ALERT_THRESHOLD", "50"))
HTTP_TIMEOUT = int(os.environ.get("HTTP_TIMEOUT_SECONDS", "10"))
HTTP_RETRIES = int(os.environ.get("HTTP_RETRIES", "3"))
HTTP_BACKOFF_FACTOR = float(os.environ.get("HTTP_BACKOFF_FACTOR", "0.5"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.environ.get(
    "RAIN_ALERT_LOG_FILE",
    os.path.join(BASE_DIR, "clima_telegram.log"),
)

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


def criar_sessao_http():
    retry = Retry(
        total=HTTP_RETRIES,
        connect=HTTP_RETRIES,
        read=HTTP_RETRIES,
        status=HTTP_RETRIES,
        backoff_factor=HTTP_BACKOFF_FACTOR,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def enviar_telegram(mensagem, session=None):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.error("TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID não configurado.")
        return False

    session = session or criar_sessao_http()
    url_telegram = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        response = session.post(
            url_telegram,
            data={
                "chat_id": CHAT_ID,
                "text": mensagem,
            },
            timeout=HTTP_TIMEOUT,
        )
        if response.status_code != 200:
            logger.error("Telegram retornou HTTP %s: %s", response.status_code, response.text)
            return False

        logger.info("Mensagem enviada para o Telegram.")
        return True

    except Exception as erro:
        logger.error(f"Erro ao enviar Telegram: {erro}")
        return False


def consultar_chuva(session=None):
    session = session or criar_sessao_http()
    response = session.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "hourly": "precipitation_probability",
            "timezone": "America/Fortaleza",
            "forecast_hours": 3,
        },
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()

    try:
        data = response.json()
    except ValueError as erro:
        raise RuntimeError("API retornou JSON inválido.") from erro

    probabilidades = data.get("hourly", {}).get("precipitation_probability", [])
    horarios = data.get("hourly", {}).get("time", [])

    if len(probabilidades) < 3:
        raise RuntimeError(f"API retornou poucos dados: {probabilidades}")

    agora = probabilidades[0]
    prox_1h = probabilidades[1]
    prox_2h = probabilidades[2]

    if any(valor is None for valor in (agora, prox_1h, prox_2h)):
        raise RuntimeError(f"API retornou probabilidade vazia: {probabilidades[:3]}")

    max_prob = max(agora, prox_1h, prox_2h)

    return {
        "agora": agora,
        "prox_1h": prox_1h,
        "prox_2h": prox_2h,
        "max_prob": max_prob,
        "horarios": horarios
    }


def main():
    session = criar_sessao_http()

    try:
        dados = consultar_chuva(session)

        max_prob = dados["max_prob"]

        logger.info(
            f"Probabilidades: agora={dados['agora']}%, "
            f"1h={dados['prox_1h']}%, "
            f"2h={dados['prox_2h']}%, "
            f"máxima={max_prob}%"
        )

        # Ignora quando a probabilidade estiver abaixo do limiar
        if max_prob < LIMIAR_ALERTA:
            logger.info(
                f"Nenhum alerta enviado. Probabilidade maxima {max_prob}% "
                f"abaixo do limiar de {LIMIAR_ALERTA}%."
            )
            return 0

        mensagem = (
            "⚠️ Alerta de Chuva!\n"
            f"Probabilidade máxima nas próximas 2 horas: {max_prob}%.\n\n"
            f"Agora: {dados['agora']}%\n"
            f"Próxima hora: {dados['prox_1h']}%\n"
            f"Daqui a 2 horas: {dados['prox_2h']}%\n\n"
            "Local: Várzea da Onça, Quixadá-CE."
        )
        if enviar_telegram(mensagem, session):
            logger.info(f"Alerta enviado. Probabilidade máxima: {max_prob}%")
            return 0

        logger.error("Falha ao enviar alerta via Telegram.")
        return 1

    except Exception as erro:
        logger.exception("Falha na automação: %s", erro)
        return 1


if __name__ == "__main__":
    sys.exit(main())
