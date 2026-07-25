import scripts.alert_rain as alert


class FakeResponse:
    def __init__(self, payload=None, status_code=200, text="ok"):
        self.payload = payload or {}
        self.status_code = status_code
        self.text = text

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, *args, **kwargs):
        self.calls.append(("GET", args, kwargs))
        return self.response


def test_consultar_chuva_considera_probabilidade_atual_no_maximo():
    session = FakeSession(
        FakeResponse(
            {
                "hourly": {
                    "time": ["2026-07-11T15:00", "2026-07-11T16:00", "2026-07-11T17:00"],
                    "precipitation_probability": [90, 20, 10],
                }
            }
        )
    )

    dados = alert.consultar_chuva(session)

    assert dados["agora"] == 90
    assert dados["max_prob"] == 90


def test_main_retorna_erro_quando_telegram_falha(monkeypatch):
    monkeypatch.setattr(alert, "criar_sessao_http", lambda: object())
    monkeypatch.setattr(
        alert,
        "consultar_chuva",
        lambda session=None: {
            "agora": 80,
            "prox_1h": 10,
            "prox_2h": 5,
            "max_prob": 80,
            "horarios": [
                "2026-07-11T15:00",
                "2026-07-11T16:00",
                "2026-07-11T17:00",
            ],
        },
    )
    monkeypatch.setattr(alert, "enviar_telegram", lambda mensagem, session=None: False)

    assert alert.main() == 1


def test_main_nao_envia_alerta_abaixo_do_limiar(monkeypatch):
    monkeypatch.setattr(alert, "criar_sessao_http", lambda: object())
    monkeypatch.setattr(
        alert,
        "consultar_chuva",
        lambda session=None: {
            "agora": 10,
            "prox_1h": 20,
            "prox_2h": 30,
            "max_prob": 30,
            "horarios": [],
        },
    )
    monkeypatch.setattr(
        alert,
        "enviar_telegram",
        lambda mensagem, session=None: (_ for _ in ()).throw(AssertionError("nao deveria enviar")),
    )

    assert alert.main() == 0


def test_mensagem_alerta_identifica_local(monkeypatch):
    monkeypatch.setattr(alert, "NOME_LOCAL", "Quixadá sede, CE")

    mensagem = alert.criar_mensagem_alerta(
        {
            "agora": 20,
            "prox_1h": 60,
            "prox_2h": 40,
            "max_prob": 60,
            "horarios": [
                "2026-07-11T15:00",
                "2026-07-11T16:00",
                "2026-07-11T17:00",
            ],
        }
    )

    assert "Local: Quixadá sede, CE." in mensagem
    assert "Probabilidade máxima nas próximas 2 horas: 60%." in mensagem
    assert "15:00: 20%" in mensagem
    assert "16:00: 60%" in mensagem
    assert "17:00: 40%" in mensagem


def test_modo_teste_envia_sem_consultar_previsao(monkeypatch):
    mensagens = []
    monkeypatch.setattr(alert, "MODO_TESTE", True)
    monkeypatch.setattr(alert, "NOME_LOCAL", "Várzea da Onça, Quixadá-CE")
    monkeypatch.setattr(alert, "criar_sessao_http", lambda: object())
    monkeypatch.setattr(
        alert,
        "consultar_chuva",
        lambda session=None: (_ for _ in ()).throw(
            AssertionError("não deveria consultar a previsão")
        ),
    )
    monkeypatch.setattr(
        alert,
        "enviar_telegram",
        lambda mensagem, session=None: mensagens.append(mensagem) or True,
    )

    assert alert.main() == 0
    assert "Teste do alerta de chuva concluído" in mensagens[0]
    assert "Várzea da Onça" in mensagens[0]
    assert "não indica previsão de chuva" in mensagens[0]
