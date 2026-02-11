#!/usr/bin/env python3
"""orto_pedia — Weekly PubMed News Fetcher

Scarica le ultime revisioni sistematiche/meta-analisi da PubMed,
le analizza con Claude Haiku e genera una pagina Markdown settimanale.

Sorgenti dati:
  1. Feed RSS PubMed (ricerche salvate) — via feedparser
  2. Query programmatiche NCBI E-utilities — via urllib (standard library)

Uso:
  python scripts/fetch_news.py                    # genera per oggi
  python scripts/fetch_news.py --dry-run           # preview senza scrivere
  python scripts/fetch_news.py --date 2026-02-10   # data custom
  python scripts/fetch_news.py --threshold 7       # solo score >= 7
"""

import argparse
import json
import logging
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
import feedparser
from bs4 import BeautifulSoup

# ─── Configurazione ──────────────────────────────────────────────────────────

# Feed RSS PubMed (ricerche salvate).
# Per crearne di nuovi: PubMed → Ricerca → Create RSS → Copia URL
FEEDS: list[dict[str, str]] = [
    {
        "name": "Ortopedia - Revisioni Sistematiche",
        "url": (
            "https://pubmed.ncbi.nlm.nih.gov/rss/search/"
            "1pk-02YRTTMOVSA2K6uB0gWkv4RwR0cqCNpYgchfLL10TCPMeY/"
            "?limit=20&utm_campaign=pubmed-2"
        ),
    },
]

# Query PubMed via E-utilities (complemento ai feed RSS).
# Cerca articoli degli ultimi DAYS_BACK giorni.
# Query ampie: tutti i tipi di studio clinicamente rilevanti, non solo review.
QUERIES: list[str] = [
    # Ortopedia chirurgica — artroprotesi, artroscopia, osteosintesi
    (
        "(orthopedic surgery OR orthopaedic surgery OR arthroplasty "
        "OR arthroscopy OR osteosynthesis OR fracture fixation) "
        "AND (outcome OR technique OR comparison OR complication)"
    ),
    # Distretti anatomici — ginocchio, anca, spalla
    (
        "(knee OR hip OR shoulder) "
        "AND (rotator cuff OR ACL OR meniscus OR labrum "
        "OR total replacement OR osteoarthritis) "
        "AND (treatment OR surgery OR rehabilitation)"
    ),
    # Rachide e dolore spinale
    (
        "(spine OR lumbar OR cervical OR disc herniation OR spinal stenosis "
        "OR scoliosis OR spondylolisthesis) "
        "AND (treatment OR surgery OR conservative OR injection)"
    ),
    # Riabilitazione e fisioterapia MSK
    (
        "(physical therapy OR physiotherapy OR exercise therapy "
        "OR rehabilitation) "
        "AND (musculoskeletal OR postoperative OR return to sport "
        "OR tendinopathy OR muscle injury)"
    ),
    # Piede, caviglia, gomito, polso, mano
    (
        "(ankle OR foot OR elbow OR wrist OR hand) "
        "AND (fracture OR ligament OR tendon OR arthroplasty "
        "OR sprain OR instability) "
        "AND (treatment OR outcome OR rehabilitation)"
    ),
    # Pain management MSK
    (
        "(musculoskeletal pain OR chronic pain OR neuropathic pain) "
        "AND (injection OR PRP OR corticosteroid OR NSAID "
        "OR hyaluronic acid OR shockwave)"
    ),
]

RELEVANCE_THRESHOLD = 7
MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS_ANALYSIS = 1000
MAX_TOKENS_TLDR = 500
DAYS_BACK = 7
MAX_RESULTS_PER_QUERY = 20
BATCH_SIZE = 5  # Paper per chiamata API (riduce costi system prompt)
MAX_ARTICLES = 25  # Massimo articoli nel digest finale (top per score)
MAX_TAGS = 10  # Massimo tag aggregati nel frontmatter
CACHE_FILE = Path(__file__).resolve().parent / ".news_cache.json"

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fetch_news")


# ─── Raccolta da RSS ─────────────────────────────────────────────────────────


def fetch_from_rss(
    feeds: list[dict[str, str]], days_back: int = DAYS_BACK
) -> list[dict]:
    """Scarica paper dai feed RSS PubMed, filtrando per data."""
    cutoff = datetime.now() - timedelta(days=days_back)
    papers = []
    for feed_cfg in feeds:
        log.info("RSS: %s", feed_cfg["name"])
        try:
            d = feedparser.parse(feed_cfg["url"])
            if d.bozo:
                log.warning("  Feed parse warning: %s", d.bozo_exception)
            count = 0
            for entry in d.entries:
                paper = _extract_from_rss_entry(entry)
                # Filtra per data: tieni solo articoli recenti
                if _is_recent(paper["date"], cutoff):
                    papers.append(paper)
                    count += 1
            log.info(
                "  %d articoli recenti su %d totali",
                count,
                len(d.entries),
            )
        except Exception as e:
            log.error("  Errore feed RSS: %s", e)
    return papers


def _is_recent(date_str: str, cutoff: datetime) -> bool:
    """Verifica se la data dell'articolo è dopo il cutoff."""
    if not date_str:
        return True  # Se manca la data, includi per sicurezza
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y %b %d", "%Y %b", "%Y"):
        try:
            parsed = datetime.strptime(date_str.strip(), fmt)
            # Rimuovi timezone info per confronto
            return parsed.replace(tzinfo=None) >= cutoff
        except ValueError:
            continue
    return True  # Formato non riconosciuto → includi per sicurezza


def _extract_from_rss_entry(entry) -> dict:
    """Estrae dati strutturati da un entry RSS (basato su feed.py)."""
    if "content" in entry and len(entry["content"]) > 0:
        raw_html = entry["content"][0]["value"]
    else:
        raw_html = entry.get("summary", "")

    soup = BeautifulSoup(raw_html, "html.parser")
    clean_text = soup.get_text(separator=" ", strip=True)

    return {
        "title": entry.get("title", "No Title"),
        "abstract": clean_text,
        "url": entry.get("link", ""),
        "journal": entry.get("dc_source", ""),
        "date": entry.get("published", ""),
        "doi": entry.get("dc_identifier", "").replace("doi:", "").strip(),
    }


# ─── Raccolta da E-utilities ─────────────────────────────────────────────────


def fetch_from_eutils(
    queries: list[str], days_back: int = 7, max_results: int = 15
) -> list[dict]:
    """Scarica paper da PubMed E-utilities con query programmatiche."""
    papers = []
    for query in queries:
        log.info("E-utilities: '%s'", query[:80])
        try:
            pmids = _esearch(query, days_back, max_results)
            if not pmids:
                log.info("  Nessun risultato")
                continue
            log.info("  %d PMID trovati", len(pmids))
            fetched = _efetch(pmids)
            papers.extend(fetched)
            time.sleep(0.4)  # NCBI rate limit: max 3 req/s senza API key
        except Exception as e:
            log.error("  Errore E-utilities: %s", e)
    return papers


def _esearch(query: str, days_back: int, max_results: int) -> list[str]:
    """Cerca su PubMed e ritorna lista di PMID."""
    params = urllib.parse.urlencode({
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "sort": "date",
        "datetype": "pdat",
        "reldate": days_back,
        "retmode": "json",
    })
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?{params}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.loads(resp.read())
    return data.get("esearchresult", {}).get("idlist", [])


def _efetch(pmids: list[str]) -> list[dict]:
    """Scarica dettagli articoli da PubMed dato lista di PMID."""
    params = urllib.parse.urlencode({
        "db": "pubmed",
        "id": ",".join(pmids),
        "rettype": "xml",
        "retmode": "xml",
    })
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?{params}"
    with urllib.request.urlopen(url, timeout=60) as resp:
        xml_data = resp.read()

    root = ET.fromstring(xml_data)
    papers = []
    for article in root.findall(".//PubmedArticle"):
        paper = _parse_pubmed_xml(article)
        if paper:
            papers.append(paper)
    return papers


def _parse_pubmed_xml(article_elem) -> dict | None:
    """Parsa un PubmedArticle XML element in un dict strutturato."""
    medline = article_elem.find(".//MedlineCitation")
    if medline is None:
        return None
    article = medline.find("Article")
    if article is None:
        return None

    # Titolo
    title_elem = article.find("ArticleTitle")
    title = (
        "".join(title_elem.itertext()) if title_elem is not None else "No Title"
    )

    # Abstract
    abstract_parts = []
    abstract_elem = article.find("Abstract")
    if abstract_elem is not None:
        for text_elem in abstract_elem.findall("AbstractText"):
            label = text_elem.get("Label", "")
            content = "".join(text_elem.itertext())
            if label:
                abstract_parts.append(f"{label}: {content}")
            else:
                abstract_parts.append(content)
    abstract = " ".join(abstract_parts)

    # PMID
    pmid_elem = medline.find("PMID")
    pmid = pmid_elem.text if pmid_elem is not None else ""

    # DOI
    doi = ""
    for id_elem in article_elem.findall(".//ArticleId"):
        if id_elem.get("IdType") == "doi":
            doi = id_elem.text or ""
            break

    # Journal
    journal_title = article.find(".//Journal/Title")
    journal = journal_title.text if journal_title is not None else ""

    # Data pubblicazione
    date_elem = article.find(".//PubDate")
    date_str = ""
    if date_elem is not None:
        year = date_elem.findtext("Year", "")
        month = date_elem.findtext("Month", "")
        day = date_elem.findtext("Day", "")
        date_str = f"{year} {month} {day}".strip()

    return {
        "title": title,
        "abstract": abstract,
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
        "journal": journal,
        "date": date_str,
        "doi": doi,
    }


# ─── Deduplicazione ──────────────────────────────────────────────────────────


def deduplicate(papers: list[dict]) -> list[dict]:
    """Rimuove duplicati per DOI (o titolo se DOI mancante)."""
    seen: set[str] = set()
    unique = []
    for p in papers:
        key = p["doi"] if p["doi"] else p["title"].lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


# ─── Cache ───────────────────────────────────────────────────────────────────


def _cache_key(paper: dict) -> str:
    """Chiave univoca per il paper: DOI se disponibile, altrimenti titolo."""
    if paper["doi"]:
        return paper["doi"]
    return f"title:{paper['title'].lower().strip()}"


def load_cache() -> dict:
    """Carica la cache da disco. Ritorna dict vuoto se non esiste."""
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Cache corrotta, reset: %s", e)
    return {}


def save_cache(cache: dict) -> None:
    """Salva la cache su disco."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ─── Triage (screening rapido) ────────────────────────────────────────────────

SYSTEM_PROMPT_TRIAGE = """\
Sei un editor medico per orto_pedia (ortopedia e riabilitazione).
Ti fornisco una lista numerata di titoli di studi scientifici.

Per ciascun titolo, rispondi 1 se è potenzialmente rilevante per la pratica \
clinica ortopedica, fisiatrica o riabilitativa, oppure 0 se chiaramente non \
pertinente (es: oncologia pura, pediatria non MSK, veterinaria, genetica di \
base, etc.).

Nel dubbio, rispondi 1 (includi).

Rispondi SOLO con un array JSON di 0 e 1, nello stesso ordine dei titoli. \
Nessun altro testo."""


def triage_papers(
    client: anthropic.Anthropic, papers: list[dict]
) -> list[dict]:
    """Screening rapido: una sola chiamata AI con solo i titoli.

    Ritorna solo i paper considerati potenzialmente rilevanti.
    """
    if not papers:
        return []

    # Costruisci lista titoli numerata
    titles = "\n".join(
        f"{i}. {p['title']}" for i, p in enumerate(papers, 1)
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=len(papers) * 3 + 50,  # ~"0," per paper + margine
            system=SYSTEM_PROMPT_TRIAGE,
            messages=[{"role": "user", "content": titles}],
        )
        parsed = _parse_ai_response(response.content[0].text)

        if isinstance(parsed, list) and len(parsed) == len(papers):
            kept = [p for p, flag in zip(papers, parsed) if flag == 1]
            log.info(
                "Triage: %d/%d paper passano lo screening",
                len(kept),
                len(papers),
            )
            return kept

        log.warning(
            "Triage: attesi %d flag, ricevuti %d — skip triage",
            len(papers),
            len(parsed) if isinstance(parsed, list) else 0,
        )
    except (json.JSONDecodeError, anthropic.APIError) as e:
        log.warning("Triage fallito (%s) — skip triage", e)

    return papers  # Se il triage fallisce, passa tutto


# ─── Analisi AI ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT_ANALYSIS = """\
Sei un editor medico specializzato per orto_pedia, un sito evidence-based \
di ortopedia e riabilitazione.

Analizza gli abstract degli studi scientifici forniti.

Per CIASCUNO studio, applica questi criteri:

STEP 1 — RILEVANZA:
Se lo studio NON è rilevante per la pratica clinica ortopedica, fisiatrica \
o riabilitativa, rispondi con: {"relevant": false}

STEP 2 — Se È RILEVANTE:
Assegna un punteggio di rilevanza da 1 a 10 (10 = massima rilevanza).
Poi:
1. Traduci il titolo in italiano.
2. Scrivi un riassunto in italiano usando ESATTAMENTE questo formato \
Admonition MkDocs Material:

!!! abstract "Sintesi"
    [2-3 frasi su obiettivo e risultati principali]

!!! info "Evidenze Chiave"
    [Punti chiave con dati numerici se disponibili]

!!! tip "Bottom Line Clinica"
    [1-2 frasi: cosa cambia per il clinico]

3. Estrai al massimo 8 tag anatomici/clinici pertinenti (es: spalla, ginocchio, \
lombare, anca, caviglia, riabilitazione, farmacologia, imaging, chirurgia).

FORMATO RISPOSTA:
- Se ricevi UN solo studio, rispondi con un singolo oggetto JSON.
- Se ricevi PIÙ studi, rispondi con un array JSON nello STESSO ordine.

Oggetto per studio rilevante:
{"relevant": true, "relevance_score": 8, "title_it": "...", \
"markdown_content": "!!! abstract \\"Sintesi\\"\\n    ...\\n\\n\
!!! info \\"Evidenze Chiave\\"\\n    ...\\n\\n\
!!! tip \\"Bottom Line Clinica\\"\\n    ...", "tags": ["spalla"]}

Oggetto per studio NON rilevante:
{"relevant": false}

Rispondi SOLO con JSON valido, senza code fences."""

SYSTEM_PROMPT_TLDR = """\
Sei un editor medico per orto_pedia.
Ti fornisco i titoli e punteggi degli studi rilevanti della settimana.
Scrivi un TL;DR di massimo 3-4 frasi in italiano che sintetizzi i temi \
principali emersi e le implicazioni cliniche più importanti.
Tono professionale ma accessibile. Scrivi in prosa, non usare elenchi puntati."""


def _parse_ai_response(raw: str) -> dict | list | None:
    """Parsa la risposta JSON di Claude, rimuovendo code fences se presenti."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def analyze_paper(client: anthropic.Anthropic, paper: dict) -> dict | None:
    """Analizza un singolo paper con Claude. Fallback per batch falliti."""
    if not paper["abstract"]:
        return None

    user_msg = (
        f"Titolo: {paper['title']}\n"
        f"Journal: {paper['journal']}\n"
        f"Data: {paper['date']}\n\n"
        f"Abstract:\n{paper['abstract']}"
    )
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS_ANALYSIS,
            system=SYSTEM_PROMPT_ANALYSIS,
            messages=[{"role": "user", "content": user_msg}],
        )
        return _parse_ai_response(response.content[0].text)
    except (json.JSONDecodeError, anthropic.APIError) as e:
        log.warning("  Errore singolo per '%s': %s", paper["title"][:50], e)
        return None


def analyze_batch(
    client: anthropic.Anthropic, papers: list[dict]
) -> list[dict | None]:
    """Analizza un batch di paper in una singola chiamata API.

    Ritorna lista di risultati (stessa lunghezza di papers).
    Se il batch fallisce, ritenta uno per uno come fallback.
    """
    # Costruisci messaggio multi-paper
    parts = []
    for idx, p in enumerate(papers, 1):
        parts.append(
            f"### Studio {idx}\n"
            f"Titolo: {p['title']}\n"
            f"Journal: {p['journal']}\n"
            f"Data: {p['date']}\n\n"
            f"Abstract:\n{p['abstract']}"
        )
    user_msg = "\n\n---\n\n".join(parts)

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS_ANALYSIS * len(papers),
            system=SYSTEM_PROMPT_ANALYSIS,
            messages=[{"role": "user", "content": user_msg}],
        )
        parsed = _parse_ai_response(response.content[0].text)

        # Singolo paper nel batch → normalizza a lista
        if isinstance(parsed, dict):
            parsed = [parsed]

        if len(parsed) == len(papers):
            return parsed

        log.warning(
            "  Batch: attesi %d risultati, ricevuti %d — fallback singolo",
            len(papers),
            len(parsed),
        )
    except (json.JSONDecodeError, anthropic.APIError) as e:
        log.warning("  Batch fallito (%s) — fallback singolo", e)

    # Fallback: analisi individuale
    results = []
    for p in papers:
        results.append(analyze_paper(client, p))
        time.sleep(0.3)
    return results


def generate_tldr(client: anthropic.Anthropic, analyses: list[dict]) -> str:
    """Genera un TL;DR settimanale dai paper analizzati."""
    summaries = "\n".join(
        f"- {a['title_it']} (rilevanza: {a['relevance_score']}/10)"
        for a in analyses
    )
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS_TLDR,
            system=SYSTEM_PROMPT_TLDR,
            messages=[
                {
                    "role": "user",
                    "content": f"Studi della settimana:\n{summaries}",
                }
            ],
        )
        return response.content[0].text.strip()
    except anthropic.APIError as e:
        log.error("Errore generazione TL;DR: %s", e)
        return "TL;DR non disponibile questa settimana."


# ─── Generazione Markdown ────────────────────────────────────────────────────


def build_markdown(date_str: str, analyses: list[dict], tldr: str) -> str:
    """Costruisce il contenuto Markdown della rassegna settimanale."""
    # Conta frequenza tag e tieni i più comuni (max MAX_TAGS)
    tag_freq: dict[str, int] = {}
    for a in analyses:
        for tag in a.get("tags", []):
            tag_freq[tag] = tag_freq.get(tag, 0) + 1
    top_tags = [
        t for t, _ in sorted(tag_freq.items(), key=lambda x: -x[1])
    ][:MAX_TAGS]
    tags_yaml = "\n".join(f"  - {t}" for t in ["news"] + top_tags)

    lines = [
        "---",
        "tags:",
        tags_yaml,
        "---",
        "",
        f"# Rassegna Settimanale — {datetime.strptime(date_str, '%Y-%m-%d').strftime('%d-%m-%Y')}",
        "",
        f"> **TL;DR** — {tldr}",
        "",
        (
            f"Questa settimana sono stati individuati **{len(analyses)} studi** "
            "rilevanti per la pratica ortopedica e riabilitativa."
        ),
        "",
    ]

    for i, a in enumerate(analyses, 1):
        score = a.get("relevance_score", "?")
        lines.append("---")
        lines.append("")
        lines.append(f"### {i}. {a['title_it']}")
        lines.append(f"**Rilevanza: {score}/10**")
        lines.append("")
        lines.append(a["markdown_content"])
        lines.append("")

        # Link e DOI
        link_parts = []
        if a.get("url"):
            link_parts.append(f"[Articolo originale]({a['url']})")
        if a.get("doi"):
            link_parts.append(f"DOI: `{a['doi']}`")
        if link_parts:
            lines.append(" | ".join(link_parts))
            lines.append("")

    return "\n".join(lines)


def write_output(date_str: str, content: str, output_dir: Path) -> Path:
    """Scrive il file Markdown nella cartella di output."""
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / f"{date_str}-settimanale.md"
    filepath.write_text(content, encoding="utf-8")
    return filepath


# ─── Main ────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="orto_pedia — Weekly PubMed News Fetcher"
    )
    parser.add_argument(
        "--date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Data per il file di output (default: oggi, formato YYYY-MM-DD)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra risultati senza scrivere file",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=RELEVANCE_THRESHOLD,
        help=f"Soglia minima di rilevanza 1-10 (default: {RELEVANCE_THRESHOLD})",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignora la cache e ri-analizza tutto",
    )
    args = parser.parse_args()

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        log.error("Variabile ANTHROPIC_API_KEY non impostata")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # ── 1. Raccolta paper ────────────────────────────────────────────────
    log.info("=" * 50)
    log.info("RACCOLTA ARTICOLI")
    log.info("=" * 50)

    rss_papers = fetch_from_rss(FEEDS)
    eutils_papers = fetch_from_eutils(QUERIES, DAYS_BACK, MAX_RESULTS_PER_QUERY)
    all_papers = deduplicate(rss_papers + eutils_papers)
    log.info("Totale dopo deduplicazione: %d articoli", len(all_papers))

    if not all_papers:
        log.warning("Nessun articolo trovato. Uscita.")
        sys.exit(0)

    # ── 2. Cache: separa paper già analizzati da quelli nuovi ─────────
    cache = {} if args.no_cache else load_cache()
    to_analyze: list[dict] = []
    cached_results: list[tuple[dict, dict]] = []  # (paper, result)

    for paper in all_papers:
        key = _cache_key(paper)
        if key in cache:
            cached_results.append((paper, cache[key]))
        else:
            to_analyze.append(paper)

    log.info(
        "Cache: %d hit, %d da analizzare (su %d totali)",
        len(cached_results),
        len(to_analyze),
        len(all_papers),
    )

    # ── 3. Triage: screening rapido sui titoli ──────────────────────
    new_results: list[tuple[dict, dict | None]] = []

    if to_analyze:
        # Filtra paper senza abstract
        with_abstract = [p for p in to_analyze if p["abstract"]]
        no_abstract = [p for p in to_analyze if not p["abstract"]]
        for p in no_abstract:
            log.info("Skip (no abstract): %s", p["title"][:60])
            cache[_cache_key(p)] = {"relevant": False}

        log.info("=" * 50)
        log.info("TRIAGE (screening titoli)")
        log.info("=" * 50)

        triaged = triage_papers(client, with_abstract)

        # Segna come non rilevanti i paper scartati dal triage
        triaged_set = {id(p) for p in triaged}
        for p in with_abstract:
            if id(p) not in triaged_set:
                cache[_cache_key(p)] = {"relevant": False}

    # ── 4. Analisi AI a batch (solo paper che passano il triage) ──
        log.info("=" * 50)
        log.info("ANALISI AI (batch da %d)", BATCH_SIZE)
        log.info("=" * 50)

        # Processa a batch solo i paper che hanno passato il triage
        for batch_start in range(0, len(triaged), BATCH_SIZE):
            batch = triaged[batch_start : batch_start + BATCH_SIZE]
            batch_num = batch_start // BATCH_SIZE + 1
            total_batches = (len(triaged) + BATCH_SIZE - 1) // BATCH_SIZE
            log.info(
                "Batch %d/%d (%d paper)",
                batch_num,
                total_batches,
                len(batch),
            )

            results = analyze_batch(client, batch)

            for paper, result in zip(batch, results):
                key = _cache_key(paper)
                cache[key] = result if result else {"relevant": False}
                new_results.append((paper, result))

                if result and result.get("relevant"):
                    log.info(
                        "  [%d] %s -> score %d",
                        result.get("relevance_score", 0),
                        paper["title"][:50],
                        result.get("relevance_score", 0),
                    )
                else:
                    log.info("  [-] %s -> skip", paper["title"][:50])

            time.sleep(0.5)  # Rate limiting tra batch

        # Salva cache aggiornata
        save_cache(cache)
        log.info("Cache salvata (%d voci totali)", len(cache))

    # ── 5. Aggrega risultati (cached + nuovi) ─────────────────────────
    analyses: list[dict] = []
    all_results = cached_results + new_results

    for paper, result in all_results:
        if result is None:
            continue
        if not result.get("relevant"):
            continue
        if result.get("relevance_score", 0) < args.threshold:
            continue
        result["url"] = paper["url"]
        result["doi"] = paper["doi"]
        analyses.append(result)

    analyses.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

    if len(analyses) > MAX_ARTICLES:
        log.info(
            "Cap a %d articoli (scartati %d sotto il cutoff score %d)",
            MAX_ARTICLES,
            len(analyses) - MAX_ARTICLES,
            analyses[MAX_ARTICLES - 1].get("relevance_score", 0),
        )
        analyses = analyses[:MAX_ARTICLES]

    log.info("Articoli nel digest: %d/%d", len(analyses), len(all_papers))

    if not analyses:
        log.warning("Nessun articolo rilevante. Uscita.")
        sys.exit(0)

    # ── 6. TL;DR ─────────────────────────────────────────────────────────
    log.info("=" * 50)
    log.info("GENERAZIONE TL;DR")
    log.info("=" * 50)

    tldr = generate_tldr(client, analyses)
    log.info("TL;DR: %s", tldr[:120])

    # ── 7. Output ─────────────────────────────────────────────────────────
    content = build_markdown(args.date, analyses, tldr)

    if args.dry_run:
        log.info("DRY RUN — output su stdout:")
        print(content)
    else:
        project_root = Path(__file__).resolve().parent.parent
        output_dir = project_root / "docs" / "news"
        filepath = write_output(args.date, content, output_dir)
        log.info("File scritto: %s", filepath)


if __name__ == "__main__":
    main()
