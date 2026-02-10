# orto_pedia

Repo destinata alla raccolta di informazioni relative alle principali condizioni ortopedico-fisiatriche con un approccio evidence-based.

Sito live: costruito con [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/), deploy automatico via GitHub Pages.

## Struttura

- `docs/` — Contenuti clinici in Markdown, organizzati per distretto anatomico e tema trasversale
- `mkdocs.yml` — Configurazione MkDocs (tema, plugin, navigazione, estensioni)
- `elicit.js` — Script browser per estrarre tabelle da [Elicit.com](https://elicit.com) e generare schede cliniche con Claude

## elicit.js

Bookmarklet da incollare nella console del browser su una pagina Elicit con tabella AG-Grid visibile.

**Cosa fa:**

1. Rileva automaticamente colonne e header dalla griglia AG-Grid
2. Scrolla verticalmente e orizzontalmente per catturare tutte le righe e colonne (gestisce la virtualizzazione AG-Grid)
3. Genera una tabella Markdown con link ai paper
4. Chiama l'API Claude per produrre un TLDR clinico in formato Material for MkDocs admonitions
5. Mostra un popup con il Markdown pronto da copiare

**Requisiti:** API key Anthropic (da inserire nello script prima dell'uso, mai committare).

## Comandi

```bash
pip install -r requirements.txt   # Dipendenze
mkdocs serve                      # Server locale con hot-reload
mkdocs build --strict             # Build statica
```
