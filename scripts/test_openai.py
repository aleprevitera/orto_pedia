"""Test reale: fetch 6 paper da PubMed + analisi batch con OpenAI SDK."""
import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from openai import OpenAI

# ─── Fetch 6 paper reali da PubMed ──────────────────────────────────────────

def fetch_papers():
    query = "(knee OR hip OR shoulder) AND (arthroplasty OR arthroscopy)"
    params = urllib.parse.urlencode({
        "db": "pubmed",
        "term": query,
        "retmax": 6,
        "sort": "date",
        "datetype": "pdat",
        "reldate": 7,
        "retmode": "json",
        "email": "orto_pedia_bot@github.com",
    })
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?{params}"
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "orto_pedia/1.0")
    with urllib.request.urlopen(req, timeout=30) as resp:
        pmids = json.loads(resp.read())["esearchresult"]["idlist"]

    print(f"PMID trovati: {pmids}")

    params = urllib.parse.urlencode({
        "db": "pubmed",
        "id": ",".join(pmids),
        "rettype": "xml",
        "retmode": "xml",
        "email": "orto_pedia_bot@github.com",
    })
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?{params}"
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "orto_pedia/1.0")
    with urllib.request.urlopen(req, timeout=60) as resp:
        root = ET.fromstring(resp.read())

    papers = []
    for art in root.findall(".//PubmedArticle"):
        mc = art.find(".//MedlineCitation")
        a = mc.find("Article") if mc is not None else None
        if a is None:
            continue
        title_el = a.find("ArticleTitle")
        title = "".join(title_el.itertext()) if title_el is not None else ""
        abstract_parts = []
        ab = a.find("Abstract")
        if ab is not None:
            for t in ab.findall("AbstractText"):
                label = t.get("Label", "")
                content = "".join(t.itertext())
                abstract_parts.append(f"{label}: {content}" if label else content)
        journal_el = a.find(".//Journal/Title")
        papers.append({
            "title": title,
            "abstract": " ".join(abstract_parts),
            "journal": journal_el.text if journal_el is not None else "",
        })
    return papers


# ─── System prompt (identico allo script) ───────────────────────────────────

SYSTEM_PROMPT = """\
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
2. Scrivi un riassunto in italiano (2-3 frasi).
3. Estrai al massimo 8 tag.

FORMATO RISPOSTA: array JSON nello STESSO ordine.
{"relevant": true, "relevance_score": 8, "title_it": "...", "tags": ["spalla"]}
{"relevant": false}

Rispondi SOLO con JSON valido, senza code fences."""

# ─── Main ────────────────────────────────────────────────────────────────────

print("=== Fetch paper da PubMed ===")
t0 = time.time()
papers = fetch_papers()
print(f"Fetch: {time.time() - t0:.1f}s — {len(papers)} paper\n")

for p in papers:
    print(f"  - {p['title'][:80]}")

# Costruisci prompt batch
parts = []
for i, p in enumerate(papers, 1):
    parts.append(
        f"### Studio {i}\n"
        f"Titolo: {p['title']}\n"
        f"Journal: {p['journal']}\n\n"
        f"Abstract:\n{p['abstract']}"
    )
user_msg = "\n\n---\n\n".join(parts)

print(f"\n=== Analisi batch {len(papers)} paper con OpenAI SDK ===")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

t0 = time.time()
resp = client.responses.create(
    model="gpt-5-nano-2025-08-07",
    instructions=SYSTEM_PROMPT,
    input=user_msg,
)
elapsed = time.time() - t0
5
print(f"Tempo: {elapsed:.1f}s")
print(f"\nRisposta:\n{resp.output_text[:1000]}")
