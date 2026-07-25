import logging
from logging.handlers import RotatingFileHandler
import os
import sys

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_TOKEN"))
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

NOME_LOCAL = os.environ.get("RAIN_ALERT_LOCATION_NAME", "Quixadá sede, CE")
LATITUDE = os.environ.get("RAIN_ALERT_LATITUDE", "-4.96")
LONGITUDE = os.environ.get("RAIN_ALERT_LONGITUDE", "-39.01")
LIMIAR_ALERTA = int(os.environ.get("RAIN_ALERT_THRESHOLD", "50"))
MODO_TESTE = os.environ.get("RAIN_ALERT_TEST_MODE", "false").lower() in {
    "1",
    "true",
    "yes",
}

HTTP_TIMEOUT = int(os.environ.get("HTTP_TIMEOUT_SECONDS", "10"))
HTTP_RETRIES = int(os.environ.get("HTTP_RETRIES", "3"))
HTTP_BACKOFF_FACTOR = float(os.environ.get("HTTP_BACKOFF_FACTOR", "0.5"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.environ.get(
    "RAIN_ALERT_LOG_FILE",
    os.path.join(BASE_DIR, "clima_telegram.log"),
)

logger = logging.getLogger("ClimaBot")
logger.setLevel(logging.INFO)

if not logger.handlers:
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=100000,
        backupCount=1,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(levelname)s - %(message)s"))
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
        logger.error("TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não configurado.")
        return False

    session = session or criar_sessao_http()
    url_telegram = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        response = session.post(
            url_telegram,
            data={"chat_id": CHAT_ID, "text": mensagem},
            timeout=HTTP_TIMEOUT,
        )
        if response.status_code != 200:
            logger.error(
                "Telegram retornou HTTP %s: %s",
                response.status_code,
                response.text,
            )
            return False

        logger.info("Mensagem enviada para o Telegram.")
        return True
    except requests.RequestException as erro:
        # A URL da exceção pode conter o token do bot; registre apenas o tipo.
        logger.error("Falha de comunicação com o Telegram: %s", type(erro).__name__)
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
        headers={"User-Agent": "automations-rain-alert/1.0"},
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

    agora, prox_1h, prox_2h = probabilidades[:3]
    if any(valor is None for valor in (agora, prox_1h, prox_2h)):
        raise RuntimeError(f"API retornou probabilidade vazia: {probabilidades[:3]}")

    return {
        "agora": agora,
        "prox_1h": prox_1h,
        "prox_2h": prox_2h,
        "max_prob": max(agora, prox_1h, prox_2h),
        "horarios": horarios,
    }


def criar_mensagem_alerta(dados):
    hora_atual, proxima_hora, hora_seguinte = (
        horario.split("T", 1)[-1][:5] for horario in dados["horarios"][:3]
    )

    return (
        "⚠️ Alerta de Chuva!\n"
        f"Probabilidade máxima nas próximas 2 horas: {dados['max_prob']}%.\n\n"
        f"{hora_atual}: {dados['agora']}%\n"
        f"{proxima_hora}: {dados['prox_1h']}%\n"
        f"{hora_seguinte}: {dados['prox_2h']}%\n\n"
        f"Local: {NOME_LOCAL}."
    )


def criar_mensagem_teste():
    return (
        "✅ Teste do alerta de chuva concluído.\n\n"
        f"Local: {NOME_LOCAL}.\n"
        f"Coordenadas: {LATITUDE}, {LONGITUDE}.\n"
        "Esta é uma mensagem de teste; não indica previsão de chuva."
    )


def main():
    session = criar_sessao_http()

    try:
        if MODO_TESTE:
            logger.info("Enviando mensagem de teste para %s.", NOME_LOCAL)
            return 0 if enviar_telegram(criar_mensagem_teste(), session) else 1

        dados = consultar_chuva(session)
        max_prob = dados["max_prob"]

        logger.info(
            "Local=%s; probabilidades: agora=%s%%, 1h=%s%%, 2h=%s%%, máxima=%s%%",
            NOME_LOCAL,
            dados["agora"],
            dados["prox_1h"],
            dados["prox_2h"],
            max_prob,
        )

        if max_prob < LIMIAR_ALERTA:
            logger.info(
                "Nenhum alerta enviado. Probabilidade máxima %s%% abaixo do limiar de %s%%.",
                max_prob,
                LIMIAR_ALERTA,
            )
            return 0

        if enviar_telegram(criar_mensagem_alerta(dados), session):
            logger.info("Alerta enviado para %s. Probabilidade máxima: %s%%", NOME_LOCAL, max_prob)
            return 0

        logger.error("Falha ao enviar alerta via Telegram para %s.", NOME_LOCAL)
        return 1
    except Exception as erro:
        logger.exception("Falha na automação de %s: %s", NOME_LOCAL, erro)
        return 1


if __name__ == "__main__":
    sys.exit(main())
