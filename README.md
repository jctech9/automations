# Automations

Automacoes em Python executadas pelo GitHub Actions para:

- enviar alertas de chuva separados para Varzea da Onca e Quixada sede;
- monitorar o feed RSS/Atom do campus UFC Quixada e notificar novas publicacoes ou alteracoes.

## Secrets

Configure estes secrets no repositorio:

- `TELEGRAM_RAIN_BOT_TOKEN`: token do bot dedicado aos alertas de chuva.
- `TELEGRAM_FEED_BOT_TOKEN`: token do bot dedicado ao monitor do feed.
- `TELEGRAM_ID`: chat, grupo ou canal que recebera as mensagens dos dois bots.

## Workflows

- `rain_alerts`: roda dois jobs a cada 3 horas, no minuto 7: um para Varzea da Onca e outro para Quixada sede. A execucao manual permite enviar mensagens de teste.
- `quixada_feed_monitor`: roda a cada hora, no minuto 13.
- `tests`: roda em push, pull request e manualmente.

Os workflows usam `timezone: America/Sao_Paulo`, permissoes minimas de leitura e `timeout-minutes` para evitar execucoes presas.

## Variaveis de ambiente

### Alerta de chuva

- `RAIN_ALERT_LOCATION_NAME`: nome exibido na mensagem.
- `RAIN_ALERT_LATITUDE` e `RAIN_ALERT_LONGITUDE`: coordenadas monitoradas.
- `RAIN_ALERT_THRESHOLD`: limiar minimo de probabilidade para enviar alerta. Padrao: `50`.
- `RAIN_ALERT_LOG_FILE`: caminho opcional do arquivo de log.
- `RAIN_ALERT_TEST_MODE`: quando `true`, envia uma mensagem de teste sem consultar a previsao.

### Monitor do feed

- `QUIXADA_FEED_URL`: URL do feed. Padrao: `https://www.quixada.ufc.br/feed/`.
- `QUIXADA_FEED_STATE_FILE`: arquivo usado para comparar execucoes. No Actions, fica em `.cache/quixada_feed_state.json`.
- `QUIXADA_FEED_MAX_STORED_ITEMS`: total de itens guardados no estado. Padrao: `40`.
- `QUIXADA_FEED_MAX_ITEMS_IN_MESSAGE`: total maximo de itens por mensagem. Padrao: `6`.

Se o site estiver temporariamente fora do ar, responder com erro HTTP ou retornar
uma pagina de manutencao no lugar do feed, a execucao termina normalmente e
preserva o ultimo estado valido. A proxima execucao agendada tenta novamente.
Erros inesperados da automacao continuam fazendo o workflow falhar.

### HTTP

- `HTTP_TIMEOUT_SECONDS`: timeout das chamadas HTTP.
- `TELEGRAM_TIMEOUT_SECONDS`: timeout especifico do Telegram no monitor do feed.
- `HTTP_RETRIES`: quantidade de tentativas em falhas transitorias.
- `HTTP_BACKOFF_FACTOR`: fator de espera entre tentativas.

## Estado do monitor

O estado do feed e salvo via `actions/cache`. Isso reduz notificacoes duplicadas entre execucoes, mas cache nao e armazenamento permanente: pode expirar ou ser removido pelo GitHub. Se o historico ficar critico, mova o estado para um storage persistente, como uma branch dedicada, banco simples ou bucket.

## TLS do feed UFC Quixada

Todas as requisicoes HTTPS do monitor exigem validacao do certificado, inclusive
durante redirecionamentos. Nao existe fallback com `verify=False` nem variavel de
ambiente para desativar essa protecao.

Em 16/07/2026, o certificado de `https://www.quixada.ufc.br/feed/` estava valido
para `*.quixada.ufc.br`, de 10/10/2025 a 11/11/2026. Entretanto, o servidor
entregava uma cadeia incorreta: omitia a intermediaria que assinou o certificado
e enviava certificados de outra hierarquia. Clientes que completam a cadeia
automaticamente conseguiam acessar o feed, mas OpenSSL/`requests` falhava com
`unable to get local issuer certificate`.

Como compatibilidade temporaria, somente o hostname exato `www.quixada.ufc.br`
usa o bundle confiavel em `certs/quixada-globalsign-chain.pem`, contendo a
intermediaria `GlobalSign RSA OV SSL CA 2018` e a raiz `GlobalSign Root R3`.
Outros hosts, inclusive destinos de redirecionamento, continuam usando a cadeia
padrao do `requests`. A verificacao TLS permanece ativa nos dois casos.

Revisar esta compatibilidade ate **15/10/2026** e remover o bundle assim que o
servidor passar a entregar a cadeia correta.

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
python scripts/alert_rain.py
python scripts/monitor_quixada_feed.py
```
