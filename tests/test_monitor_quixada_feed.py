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


def test_parse_feed_rss_limpa_html_e_gera_hash():
    feed = monitor.parse_feed(RSS_SAMPLE)

    assert feed["title"] == "UFC Quixada"
    assert len(feed["entries"]) == 1
    assert feed["entries"][0]["id"] == "item-1"
    assert feed["entries"][0]["summary"] == "Resumo limpo."
    assert feed["entries"][0]["hash"]


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


def test_split_message_respeita_limite_em_blocos():
    message = ("a" * 20) + "\n\n" + ("b" * 20) + "\n\n" + ("c" * 20)

    assert monitor.split_message(message, limit=25) == [
        "a" * 20,
        "b" * 20,
        "c" * 20,
    ]
