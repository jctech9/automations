import pytest
import requests
from requests.adapters import HTTPAdapter

import scripts.monitor_quixada_feed as monitor


RSS_SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>UFC Quixada</title>
    <lastBuildDate>Sat, 11 Jul 2026 15:00:00 +0000</lastBuildDate>
    <item>
      <guid>item-1</guid>
      <title>Primeira noticia</title>
      <link>https://www.quixada.ufc.br/noticia</link>
      <pubDate>Sat, 11 Jul 2026 14:00:00 +0000</pubDate>
      <description><![CDATA[<p>Resumo <strong>limpo</strong>.</p>]]></description>
    </item>
  </channel>
</rss>
"""


class FakeResponse:
    def __init__(self, content=RSS_SAMPLE, url="https://www.quixada.ufc.br/feed/"):
        self.content = content
        self.url = url
        self.history = []

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response or FakeResponse()
        self.error = error
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


def assert_tls_verification_was_not_disabled(session):
    assert len(session.calls) == 1
    _, kwargs = session.calls[0]
    assert kwargs.get("verify", True) is not False
    assert kwargs["timeout"] == monitor.HTTP_TIMEOUT


def test_fetch_feed_certificado_valido_mantem_verificacao_tls(
    monkeypatch,
    caplog,
):
    monkeypatch.setattr(
        monitor,
        "FEED_URL",
        "https://www.quixada.ufc.br/feed/",
    )
    session = FakeSession()

    assert monitor.fetch_feed(session) == RSS_SAMPLE
    assert_tls_verification_was_not_disabled(session)
    assert "Compatibilidade TLS temporaria ativa" in caplog.text
    assert monitor.QUIXADA_TLS_HOST in caplog.text


def test_fetch_feed_propaga_falha_ssl_sem_segunda_tentativa(monkeypatch):
    monkeypatch.setattr(
        monitor,
        "FEED_URL",
        "https://www.quixada.ufc.br/feed/",
    )
    session = FakeSession(error=requests.exceptions.SSLError("certificate verify failed"))

    with pytest.raises(requests.exceptions.SSLError):
        monitor.fetch_feed(session)

    assert_tls_verification_was_not_disabled(session)


def test_build_http_session_host_permitido_usa_ca_especifica():
    session = monitor.build_http_session()
    adapter = session.get_adapter("https://www.quixada.ufc.br/feed/")

    assert isinstance(adapter, monitor.SSLContextAdapter)
    assert adapter.ssl_context.check_hostname is True
    assert adapter.ssl_context.verify_mode.name == "CERT_REQUIRED"
    assert adapter.max_retries.total == monitor.HTTP_RETRIES


def test_build_http_session_host_diferente_usa_validacao_padrao():
    session = monitor.build_http_session()
    adapter = session.get_adapter("https://feed.example.net/rss")

    assert type(adapter) is HTTPAdapter
    assert adapter.max_retries.total == monitor.HTTP_RETRIES


def test_redirecionamento_para_outro_host_nao_herda_ca_especifica():
    session = monitor.build_http_session()
    source_adapter = session.get_adapter("https://www.quixada.ufc.br/feed/")
    target_adapter = session.get_adapter("https://cdn.example.net/feed/")

    assert isinstance(source_adapter, monitor.SSLContextAdapter)
    assert type(target_adapter) is HTTPAdapter
    assert target_adapter is not source_adapter


def test_fetch_feed_fallback_inseguro_nao_pode_ser_ativado_por_ambiente(
    monkeypatch,
):
    monkeypatch.setenv("QUIXADA_SSL_FALLBACK_ENABLED", "true")
    monkeypatch.setattr(
        monitor,
        "FEED_URL",
        "https://www.quixada.ufc.br/feed/",
    )
    session = FakeSession(error=requests.exceptions.SSLError("certificate verify failed"))

    with pytest.raises(requests.exceptions.SSLError):
        monitor.fetch_feed(session)

    assert_tls_verification_was_not_disabled(session)


def test_parse_feed_rss_limpa_html_e_gera_hash():
    feed = monitor.parse_feed(RSS_SAMPLE)

    assert feed["title"] == "UFC Quixada"
    assert len(feed["entries"]) == 1
    assert feed["entries"][0]["id"] == "item-1"
    assert feed["entries"][0]["summary"] == "Resumo limpo."
    assert feed["entries"][0]["hash"]


def test_parse_feed_resposta_invalida_gera_erro_de_conteudo():
    with pytest.raises(
        monitor.FeedContentError,
        match="nao e um XML valido",
    ):
        monitor.parse_feed(b"<html>site em manutencao")


def test_detect_changes_separa_novos_e_alterados():
    entry = monitor.parse_feed(RSS_SAMPLE)["entries"][0]
    previous_state = {"entries": {entry["id"]: entry}}

    changed_entry = dict(entry)
    changed_entry["summary"] = "Resumo atualizado."
    changed_entry["hash"] = monitor.entry_hash(changed_entry)

    new_entry = dict(entry)
    new_entry["id"] = "item-2"
    new_entry["title"] = "Segunda noticia"
    new_entry["hash"] = monitor.entry_hash(new_entry)

    new_entries, changed_entries = monitor.detect_changes(
        previous_state,
        [changed_entry, new_entry],
    )

    assert new_entries == [new_entry]
    assert changed_entries[0]["id"] == "item-1"
    assert changed_entries[0]["changed_fields"] == ["summary"]


def test_build_message_formata_nova_publicacao_para_telegram():
    entry = monitor.parse_feed(RSS_SAMPLE)["entries"][0]

    message = monitor.build_message([entry], [])

    assert message.startswith("📰 Nova publicação — UFC Quixadá")
    assert "📌 Primeira noticia" in message
    assert "🗓 Publicado em: 11/07/2026 às 11:00" in message
    assert "📝 Resumo limpo." in message
    assert "🔗 https://www.quixada.ufc.br/noticia" in message
    assert "Feed:" not in message
    assert "Verificado em:" not in message


def test_build_message_diferencia_publicacao_atualizada():
    entry = monitor.parse_feed(RSS_SAMPLE)["entries"][0]
    entry["changed_fields"] = ["title", "summary"]

    message = monitor.build_message([], [entry])

    assert message.startswith("✏️ Publicação atualizada — UFC Quixadá")
    assert "✏️ Alterado: título, resumo/conteúdo" in message
    assert "📝 Resumo limpo." in message
    assert "🔗 https://www.quixada.ufc.br/noticia" in message


def test_split_message_respeita_limite_em_blocos():
    message = ("a" * 20) + "\n\n" + ("b" * 20) + "\n\n" + ("c" * 20)

    assert monitor.split_message(message, limit=25) == [
        "a" * 20,
        "b" * 20,
        "c" * 20,
    ]


def test_modo_teste_envia_sem_consultar_feed_ou_alterar_estado(monkeypatch):
    messages = []
    session = object()
    monkeypatch.setattr(monitor, "TEST_MODE", True)
    monkeypatch.setattr(monitor, "build_http_session", lambda: session)
    monkeypatch.setattr(
        monitor,
        "fetch_feed",
        lambda current_session: pytest.fail("Feed nao deveria ser consultado."),
    )
    monkeypatch.setattr(
        monitor,
        "load_state",
        lambda: pytest.fail("Estado nao deveria ser lido."),
    )
    monkeypatch.setattr(
        monitor,
        "save_state",
        lambda feed: pytest.fail("Estado nao deveria ser alterado."),
    )
    monkeypatch.setattr(
        monitor,
        "send_telegram",
        lambda message, current_session=None: messages.append(
            (message, current_session)
        )
        or True,
    )

    assert monitor.main() == 0
    assert messages == [(monitor.build_test_message(), session)]
    assert "Teste do monitor do feed concluído" in messages[0][0]
    assert "não indica nova publicação" in messages[0][0]


@pytest.mark.parametrize(
    "error",
    [
        requests.exceptions.Timeout("tempo esgotado"),
        requests.exceptions.ConnectionError("site fora do ar"),
        requests.exceptions.HTTPError("HTTP 503"),
    ],
)
def test_main_indisponibilidade_do_site_nao_falha_execucao(
    monkeypatch,
    caplog,
    error,
):
    monkeypatch.setattr(monitor, "build_http_session", lambda: object())
    monkeypatch.setattr(
        monitor,
        "fetch_feed",
        lambda session: (_ for _ in ()).throw(error),
    )
    monkeypatch.setattr(
        monitor,
        "load_state",
        lambda: pytest.fail("Estado nao deveria ser lido."),
    )
    monkeypatch.setattr(
        monitor,
        "save_state",
        lambda feed: pytest.fail("Estado nao deveria ser alterado."),
    )

    assert monitor.main() == 0
    assert "Feed indisponivel nesta verificacao" in caplog.text
    assert "estado anterior foi preservado" in caplog.text


def test_main_resposta_temporaria_invalida_nao_falha_execucao(
    monkeypatch,
    caplog,
):
    monkeypatch.setattr(monitor, "build_http_session", lambda: object())
    monkeypatch.setattr(
        monitor,
        "fetch_feed",
        lambda session: b"<html>site em manutencao",
    )
    monkeypatch.setattr(
        monitor,
        "load_state",
        lambda: pytest.fail("Estado nao deveria ser lido."),
    )
    monkeypatch.setattr(
        monitor,
        "save_state",
        lambda feed: pytest.fail("Estado nao deveria ser alterado."),
    )

    assert monitor.main() == 0
    assert "Feed indisponivel nesta verificacao" in caplog.text
