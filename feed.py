import feedparser
from bs4 import BeautifulSoup # Ti servirà: pip install beautifulsoup4

feed = 'https://pubmed.ncbi.nlm.nih.gov/rss/search/1pk-02YRTTMOVSA2K6uB0gWkv4RwR0cqCNpYgchfLL10TCPMeY/?limit=20&utm_campaign=pubmed-2&fc=20260211034757'

d = feedparser.parse(feed)

def extract_paper_data(entry):
    # 1. Estrazione del contenuto HTML completo (priorità rispetto a 'summary')
    raw_html = ""
    if 'content' in entry and len(entry['content']) > 0:
        raw_html = entry['content'][0]['value']
    else:
        # Fallback se content è vuoto
        raw_html = entry.get('summary', '')

    # 2. Pulizia HTML con BeautifulSoup
    # Rimuoviamo i tag HTML per dare a Haiku solo il testo puro
    soup = BeautifulSoup(raw_html, "html.parser")
    clean_text = soup.get_text(separator=" ", strip=True)

    # 3. Costruzione oggetto per Claude
    paper_data = {
        "title": entry.get('title', 'No Title'),
        "abstract": clean_text,  # Ora è testo pulito
        "url": entry.get('link', ''),
        "journal": entry.get('dc_source', ''),
        "date": entry.get('published', ''),
        "doi": entry.get('dc_identifier', '').replace('doi:', '').strip()
    }
    
    return paper_data

# Questo oggetto 'clean_data' è quello che poi passi nel prompt a Claude Haiku
# Prompt: "Analizza questo paper: {clean_data['title']} \n {clean_data['abstract']}..."

clean_data = [extract_paper_data(entry) for entry in d.entries]
print(clean_data[0])