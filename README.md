# Automations

Automacoes em Python executadas pelo GitHub Actions para:

- enviar alerta de chuva para Varzea da Onca, Quixada-CE;
- monitorar o feed RSS/Atom do campus UFC Quixada e notificar novas publicacoes ou alteracoes.

## Secrets

Configure estes secrets no repositorio:

- `TELEGRAM_BOT_TOKEN`: token do bot do Telegram.
- `TELEGRAM_CHAT_ID`: chat, grupo ou canal que recebera as mensagens.

## Workflows

- `rain_alert_vzo`: roda a cada 2 horas, no minuto 7.
- `quixada_feed_monitor`: roda a cada hora, no minuto 13.
- `tests`: roda em push, pull request e manualmente.

Os workflows usam `timezone: America/Sao_Paulo`, permissoes minimas de leitura e `timeout-minutes` para evitar execucoes presas.

## Variaveis de ambiente

### Alerta de chuva

- `RAIN_ALERT_LATITUDE` e `RAIN_ALERT_LONGITUDE`: coordenadas monitoradas.
- `RAIN_ALERT_THRESHOLD`: limiar minimo de probabilidade para enviar alerta. Padrao: `50`.
- `RAIN_ALERT_LOG_FILE`: caminho opcional do arquivo de log.

### Monitor do feed

- `QUIXADA_FEED_URL`: URL do feed. Padrao: `https://www.quixada.ufc.br/feed/`.
- `QUIXADA_FEED_STATE_FILE`: arquivo usado para comparar execucoes. No Actions, fica em `.cache/quixada_feed_state.json`.
- `QUIXADA_FEED_MAX_STORED_ITEMS`: total de itens guardados no estado. Padrao: `40`.
- `QUIXADA_FEED_MAX_ITEMS_IN_MESSAGE`: total maximo de itens por mensagem. Padrao: `6`.

### HTTP

- `HTTP_TIMEOUT_SECONDS`: timeout das chamadas HTTP.
- `TELEGRAM_TIMEOUT_SECONDS`: timeout especifico do Telegram no monitor do feed.
- `HTTP_RETRIES`: quantidade de tentativas em falhas transitorias.
- `HTTP_BACKOFF_FACTOR`: fator de espera entre tentativas.

## Estado do monitor

O estado do feed e salvo via `actions/cache`. Isso reduz notificacoes duplicadas entre execucoes, mas cache nao e armazenamento permanente: pode expirar ou ser removido pelo GitHub. Se o historico ficar critico, mova o estado para um storage persistente, como uma branch dedicada, banco simples ou bucket.

## SSL do feed UFC Quixada

O monitor mantem uma excecao controlada para `www.quixada.ufc.br`: se a validacao SSL falhar, ele tenta novamente sem validar certificado apenas para esse host conhecido. Revise e remova essa excecao quando a cadeia de certificados do site estiver corrigida.

## Rodar localmente

Instale dependencias:

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
```

Execute os testes:

```bash
python -m pytest
```

Execute uma automacao:

```bash
python scripts/alert_rain_vzo.py
python scripts/monitor_quixada_feed.py
```
