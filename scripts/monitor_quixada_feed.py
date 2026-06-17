import hashlib
import json
import logging
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

import requests


FEED_URL = os.environ.get("QUIXADA_FEED_URL", "https://www.quixada.ufc.br/feed/")
STATE_FILE = Path(os.environ.get("QUIXADA_FEED_STATE_FILE", "data/quixada_feed_state.json"))
MAX_STORED_ITEMS = int(os.environ.get("QUIXADA_FEED_MAX_STORED_ITEMS", "40"))
MAX_ITEMS_IN_MESSAGE = int(os.environ.get("QUIXADA_FEED_MAX_ITEMS_IN_MESSAGE", "6"))

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_TOKEN"))
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

NAMESPACES = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}

logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
logger = logging.getLogger("QuixadaFeedMonitor")


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def set_github_output(name, value):
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return

    with open(output_path, "a", encoding="utf-8") as file:
        file.write(f"{name}={value}\n")


def clean_text(value):
    if not value:
        return ""

    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", value)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def shorten(value, limit=260):
    value = clean_text(value)
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def element_text(element):
    if element is None:
        return ""
    return clean_text("".join(element.itertext()))


def child_text(parent, tag, namespace=None):
    if namespace:
        element = parent.find(f"{{{namespace}}}{tag}")
    else:
        element = parent.find(tag)
    return element_text(element)


def entry_hash(entry):
    payload = {
        "title": entry.get("title", ""),
        "link": entry.get("link", ""),
        "pub_date": entry.get("pub_date", ""),
        "creator": entry.get("creator", ""),
        "summary": entry.get("summary", ""),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def fetch_feed():
    logger.info(f"Consultando feed: {FEED_URL}")
    response = requests.get(
        FEED_URL,
        headers={"User-Agent": "Mozilla/5.0 (feed monitor)"},
        timeout=20,
    )
    response.raise_for_status()
    return response.content


def parse_rss_channel(root):
    channel = root.find("channel")
    if channel is None:
        return None

    entries = []
    for item in channel.findall("item"):
        description = child_text(item, "description")
        content = child_text(item, "encoded", NAMESPACES["content"])
        entry = {
            "id": child_text(item, "guid") or child_text(item, "link"),
            "title": child_text(item, "title"),
            "link": child_text(item, "link"),
            "pub_date": child_text(item, "pubDate"),
            "creator": child_text(item, "creator", NAMESPACES["dc"]),
            "summary": shorten(content or description, 500),
        }
        if not entry["id"]:
            entry["id"] = f"{entry['title']}|{entry['pub_date']}"
        entry["hash"] = entry_hash(entry)
        entries.append(entry)

    return {
        "title": child_text(channel, "title"),
        "last_build_date": child_text(channel, "lastBuildDate"),
        "entries": entries,
    }


def parse_atom_feed(root):
    entries = []
    for item in root.findall(f"{{{NAMESPACES['atom']}}}entry"):
        link_element = item.find(f"{{{NAMESPACES['atom']}}}link")
        link = link_element.get("href", "") if link_element is not None else ""
        summary = child_text(item, "summary", NAMESPACES["atom"])
        content = child_text(item, "content", NAMESPACES["atom"])
        entry = {
            "id": child_text(item, "id", NAMESPACES["atom"]) or link,
            "title": child_text(item, "title", NAMESPACES["atom"]),
            "link": clean_text(link),
            "pub_date": (
                child_text(item, "updated", NAMESPACES["atom"])
                or child_text(item, "published", NAMESPACES["atom"])
            ),
            "creator": "",
            "summary": shorten(content or summary, 500),
        }
        if not entry["id"]:
            entry["id"] = f"{entry['title']}|{entry['pub_date']}"
        entry["hash"] = entry_hash(entry)
        entries.append(entry)

    return {
        "title": child_text(root, "title", NAMESPACES["atom"]),
        "last_build_date": child_text(root, "updated", NAMESPACES["atom"]),
        "entries": entries,
    }


def parse_feed(xml_content):
    root = ET.fromstring(xml_content)
    feed = parse_rss_channel(root) or parse_atom_feed(root)
    if not feed or not feed["entries"]:
        raise RuntimeError("Feed sem itens para monitorar.")
    return feed


def load_state():
    if not STATE_FILE.exists():
        return None

    with STATE_FILE.open("r", encoding="utf-8") as file:
        return json.load(file)


def build_state(feed):
    entries = feed["entries"][:MAX_STORED_ITEMS]
    return {
        "feed_url": FEED_URL,
        "feed_title": feed.get("title", ""),
        "last_build_date": feed.get("last_build_date", ""),
        "stored_at": now_utc(),
        "entries": {entry["id"]: entry for entry in entries},
    }


def save_state(feed):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state = build_state(feed)
    with STATE_FILE.open("w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)
        file.write("\n")


def detect_changes(previous_state, current_entries):
    previous_entries = previous_state.get("entries", {})
    new_entries = []
    changed_entries = []

    for entry in current_entries:
        previous = previous_entries.get(entry["id"])
        if previous is None:
            new_entries.append(entry)
            continue

        if previous.get("hash") != entry.get("hash"):
            changed_fields = []
            for field in ("title", "link", "pub_date", "creator", "summary"):
                if previous.get(field, "") != entry.get(field, ""):
                    changed_fields.append(field)

            changed_entry = dict(entry)
            changed_entry["changed_fields"] = changed_fields
            changed_entries.append(changed_entry)

    return new_entries, changed_entries


def format_entry(entry):
    lines = [f"- {entry.get('title') or '(sem titulo)'}"]
    if entry.get("pub_date"):
        lines.append(f"  Data: {entry['pub_date']}")
    if entry.get("creator"):
        lines.append(f"  Autor: {entry['creator']}")
    if entry.get("link"):
        lines.append(f"  Link: {entry['link']}")
    if entry.get("summary"):
        lines.append(f"  Resumo: {shorten(entry['summary'])}")
    return "\n".join(lines)


def format_changed_entry(entry):
    labels = {
        "title": "titulo",
        "link": "link",
        "pub_date": "data",
        "creator": "autor",
        "summary": "resumo/conteudo",
    }
    fields = ", ".join(labels.get(field, field) for field in entry.get("changed_fields", []))
    lines = [f"- {entry.get('title') or '(sem titulo)'}"]
    if fields:
        lines.append(f"  Campos alterados: {fields}")
    if entry.get("link"):
        lines.append(f"  Link: {entry['link']}")
    if entry.get("summary"):
        lines.append(f"  Resumo atual: {shorten(entry['summary'])}")
    return "\n".join(lines)


def build_message(new_entries, changed_entries):
    lines = [
        "Atualizacao detectada no site UFC Quixada",
        f"Feed: {FEED_URL}",
        f"Verificado em: {now_utc()}",
    ]

    if new_entries:
        lines.append("")
        lines.append(f"Novas publicacoes ({len(new_entries)}):")
        for entry in new_entries[:MAX_ITEMS_IN_MESSAGE]:
            lines.append(format_entry(entry))
        if len(new_entries) > MAX_ITEMS_IN_MESSAGE:
            lines.append(f"... e mais {len(new_entries) - MAX_ITEMS_IN_MESSAGE} publicacoes.")

    if changed_entries:
        lines.append("")
        lines.append(f"Itens alterados ({len(changed_entries)}):")
        for entry in changed_entries[:MAX_ITEMS_IN_MESSAGE]:
            lines.append(format_changed_entry(entry))
        if len(changed_entries) > MAX_ITEMS_IN_MESSAGE:
            lines.append(f"... e mais {len(changed_entries) - MAX_ITEMS_IN_MESSAGE} itens.")

    return "\n\n".join(lines)


def split_message(message, limit=3900):
    chunks = []
    text = message.strip()

    while len(text) > limit:
        cut = text.rfind("\n\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut].strip())
        text = text[cut:].strip()

    if text:
        chunks.append(text)

    return chunks


def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.error("TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID nao configurado.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for chunk in split_message(message):
        response = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": chunk,
                "disable_web_page_preview": False,
            },
            timeout=10,
        )
        if response.status_code != 200:
            logger.error(f"Telegram retornou HTTP {response.status_code}: {response.text}")
            return False

    logger.info("Notificacao enviada para o Telegram.")
    return True


def main():
    set_github_output("state_updated", "false")

    feed = parse_feed(fetch_feed())
    previous_state = load_state()

    if previous_state is None:
        save_state(feed)
        set_github_output("state_updated", "true")
        logger.info(
            "Estado inicial criado com %s itens. Nenhuma notificacao enviada.",
            len(feed["entries"]),
        )
        return 0

    new_entries, changed_entries = detect_changes(previous_state, feed["entries"])
    if not new_entries and not changed_entries:
        logger.info("Nenhuma alteracao detectada no feed.")
        return 0

    message = build_message(new_entries, changed_entries)
    if not send_telegram(message):
        return 1

    save_state(feed)
    set_github_output("state_updated", "true")
    logger.info(
        "Estado atualizado: %s novos itens, %s itens alterados.",
        len(new_entries),
        len(changed_entries),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
