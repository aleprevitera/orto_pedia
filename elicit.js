// ⚠️ INSERISCI QUI LA TUA API KEY ANTHROPIC
// ⚠️ INCOLLA QUI LA TUA API KEY PRIMA DI ESEGUIRE — NON committare mai questo file con la key!
const ANTHROPIC_API_KEY = "INSERISCI_QUI_LA_TUA_API_KEY";

async function scrapeAndShowPopup() {
    console.log("🚀 Inizio estrazione... NON toccare nulla finché non appare il popup!");

    // --- 1. Funzioni di supporto ---
    const cleanText = (text) => {
        if (!text) return "";
        return text
            .replace(/\|/g, "\\|") // Escape pipe per Markdown
            .replace(/DOI|Abstract only|PDF link available/gi, "")
            .replace(/\s+/g, " ")
            .replace(/\s*,\s*/g, ", ")
            .replace(/(, ?){2,}/g, ", ")
            .replace(/^[\s,]+|[\s,]+$/g, "")
            .trim();
    };

    const cleanCellText = (text) => {
        if (!text) return "";
        return text
            .replace(/\|/g, "\\|")
            // Fix punteggiatura staccata (rimuove spazi/newline prima di ; , . : )
            .replace(/\s+([;,.:!?])/g, "$1")
            // Rimuove newline e li sostituisce con spazio
            .replace(/\n+/g, " ")
            // Fix spazi multipli
            .replace(/\s{2,}/g, " ")
            // Mette <br> dove serve: prima di "- " per liste
            .replace(/\s*-\s+/g, "<br>- ")
            // Rimuove <br> iniziale
            .replace(/^<br>/, "")
            .trim();
    };

    const viewport = document.querySelector('.ag-body-viewport');
    if (!viewport) {
        alert("Errore: Impossibile trovare la griglia. Riprova ricaricando la pagina.");
        return;
    }

    // --- 2. Rilevamento dinamico delle colonne dall'header ---
    const headerCells = document.querySelectorAll('.ag-header-row-column .ag-header-cell');
    const columnNames = [];
    headerCells.forEach(cell => {
        // Cerca il testo visibile dell'header (escludendo icone/bottoni)
        const labelEl = cell.querySelector('.truncate.flex-shrink') 
            || cell.querySelector('[class*="font-medium"]');
        let name = "";
        if (labelEl) {
            name = labelEl.innerText.trim();
        }
        // La prima colonna è sempre "Paper" (ha struttura diversa)
        if (columnNames.length === 0) {
            name = "Paper / Fonte";
        }
        if (name) columnNames.push(name);
    });

    const numCols = columnNames.length;
    console.log(`📊 Rilevate ${numCols} colonne:`, columnNames);

    if (numCols < 2) {
        alert("Errore: Rilevata solo 1 colonna. Assicurati che la tabella sia visibile.");
        return;
    }

    // --- 3. Logica di Scroll e Cattura ---

    // Raccogli col-id ordinati dagli header per ricostruire l'ordine delle colonne
    const headerColIds = [];
    headerCells.forEach(cell => {
        const colId = cell.getAttribute('col-id');
        if (colId) headerColIds.push(colId);
    });
    console.log(`🔑 Col-IDs header (${headerColIds.length}):`, headerColIds);

    // rowsMap: rowIndex → { paperData, cellTexts: Map<colId, string> }
    const rowsMap = new Map();
    const hViewport = document.querySelector('.ag-center-cols-viewport');
    const scrollHeight = viewport.scrollHeight;
    let currentScroll = 0;

    // Reset scroll
    viewport.scrollTo(0, 0);
    if (hViewport) hViewport.scrollTo(0, 0);
    await new Promise(r => setTimeout(r, 800));

    // Attendi che la griglia abbia almeno una riga renderizzata (max 10s)
    console.log("⏳ Attendo che la griglia carichi le righe...");
    for (let wait = 0; wait < 20; wait++) {
        if (document.querySelector('.ag-row[row-index]')) break;
        await new Promise(r => setTimeout(r, 500));
    }
    if (!document.querySelector('.ag-row[row-index]')) {
        alert("Errore: Nessuna riga trovata nella griglia dopo 10 secondi.");
        return;
    }
    console.log("✅ Righe trovate nel DOM, inizio cattura.");

    while (currentScroll <= scrollHeight) {
        // --- Scroll orizzontale: cattura tutte le colonne virtualizzate ---
        const hScrollWidth = hViewport ? hViewport.scrollWidth : 0;
        const hClientWidth = hViewport ? hViewport.clientWidth : 1;
        let hScroll = 0;
        if (hViewport) hViewport.scrollTo(0, 0);
        await new Promise(r => setTimeout(r, 300));

        do {
            const allRowEls = document.querySelectorAll('.ag-row[row-index]');
            const seenIndices = new Set();

            allRowEls.forEach(rowEl => {
                const rowIndex = parseInt(rowEl.getAttribute('row-index'));
                if (isNaN(rowIndex) || seenIndices.has(rowIndex)) return;
                seenIndices.add(rowIndex);

                if (!rowsMap.has(rowIndex)) {
                    rowsMap.set(rowIndex, { paperData: null, cellTexts: new Map() });
                }
                const rowData = rowsMap.get(rowIndex);

                // Raccogli celle da TUTTI i container per questo row-index
                document.querySelectorAll(`.ag-row[row-index="${rowIndex}"]`).forEach(part => {
                    part.querySelectorAll('.ag-cell').forEach(cell => {
                        const colId = cell.getAttribute('col-id');
                        if (!colId) return;

                        // Paper column (primo col-id): estrai dati strutturati
                        if (colId === headerColIds[0] && !rowData.paperData) {
                            const titleEl = cell.querySelector('a');
                            if (!titleEl) return;
                            let title = cleanText(titleEl.innerText);
                            let link = titleEl.getAttribute('href') || "";
                            if (link.startsWith('/')) link = 'https://elicit.com' + link;

                            const metaGrid = cell.querySelector('.grid');
                            let meta = "";
                            if (metaGrid) {
                                const authorEl = metaGrid.querySelector('.col-span-2');
                                const authors = authorEl ? cleanText(authorEl.innerText) : "";
                                const infoDivs = metaGrid.querySelectorAll(':scope > div:not(.col-span-2):not(.justify-self-center)');
                                const infoParts = [];
                                infoDivs.forEach(d => {
                                    const t = cleanText(d.innerText);
                                    if (t) infoParts.push(t);
                                });
                                meta = [authors, ...infoParts].filter(Boolean).join(", ");
                            } else {
                                const metaEl = cell.querySelector('.text-secondary');
                                meta = metaEl ? cleanText(metaEl.innerText) : "";
                            }
                            rowData.paperData = { title, link, meta };
                        }
                        // Colonne dati: salva testo se non già catturato
                        else if (!rowData.cellTexts.has(colId)) {
                            rowData.cellTexts.set(colId, cleanCellText(cell.innerText));
                        }
                    });
                });
            });

            // Avanza scroll orizzontale (overlap 20% per sicurezza)
            if (!hViewport || hScroll >= hScrollWidth - hClientWidth) break;
            hScroll += Math.floor(hClientWidth * 0.8);
            hViewport.scrollTo(hScroll, 0);
            await new Promise(r => setTimeout(r, 300));
        } while (true);

        // Reset scroll orizzontale per il prossimo step verticale
        if (hViewport) hViewport.scrollTo(0, 0);

        if (currentScroll >= scrollHeight - viewport.clientHeight) break;
        currentScroll += viewport.clientHeight;
        viewport.scrollTo(0, currentScroll);
        console.log(`...Catturate ${rowsMap.size} righe (scroll V ${currentScroll}/${scrollHeight})...`);
        await new Promise(r => setTimeout(r, 800));
    }

    // --- 4. Costruzione Markdown Finale (tabella) ---

    // Ricostruisci righe nell'ordine corretto delle colonne, filtra righe senza Paper
    const finalRows = new Map();
    rowsMap.forEach((rowData, rowIndex) => {
        if (!rowData.paperData) return;
        const { title, link, meta } = rowData.paperData;
        const col0 = `**[${title}](${link})**<br>_${meta}_`;
        const dataCols = [col0];
        for (let i = 1; i < headerColIds.length; i++) {
            dataCols.push(rowData.cellTexts.get(headerColIds[i]) || "");
        }
        while (dataCols.length < numCols) dataCols.push("");
        finalRows.set(rowIndex, dataCols);
    });
    console.log(`📊 Righe valide: ${finalRows.size} (col-id usati per ${headerColIds.length} colonne)`);

    const sortedIndices = Array.from(finalRows.keys()).sort((a, b) => a - b);

    // Header
    const headerRow = "| " + columnNames.join(" | ") + " |";
    const separatorRow = "| " + columnNames.map(() => ":---").join(" | ") + " |";

    // Body
    let tableMarkdown = headerRow + "\n" + separatorRow + "\n";
    sortedIndices.forEach(index => {
        const cols = finalRows.get(index);
        tableMarkdown += "| " + cols.join(" | ") + " |\n";
    });

    // --- 5. Generazione TLDR con Claude API ---
    console.log("🤖 Generazione TLDR in corso...");

    // Prepara un testo pulito (senza markdown pesante) per il prompt
    const plainRows = sortedIndices.map(index => {
        const cols = finalRows.get(index);
        return columnNames.map((name, i) => {
            let val = cols[i] || "";
            // Rimuovi markdown/html per il prompt
            val = val.replace(/<br>/g, " ").replace(/\*\*/g, "").replace(/\[([^\]]+)\]\([^)]+\)/g, "$1").replace(/_/g, "");
            return `${name}: ${val}`;
        }).join("\n");
    }).join("\n---\n");

    let tldr = "";
    try {
        // Usa un iframe sandbox per bypassare gli interceptor di Elicit su fetch/XHR
        const apiResult = await new Promise((resolve, reject) => {
            const iframe = document.createElement('iframe');
            iframe.style.display = 'none';
            iframe.srcdoc = '<html><body></body></html>';
            document.body.appendChild(iframe);

            iframe.onload = () => {
                const cleanFetch = iframe.contentWindow.fetch.bind(iframe.contentWindow);
                cleanFetch("https://api.anthropic.com/v1/messages", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "x-api-key": ANTHROPIC_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "anthropic-dangerous-direct-browser-access": "true"
                    },
                    body: JSON.stringify({
                        model: "claude-haiku-4-5-20251001",
                        max_tokens: 1024,
                        messages: [{
                            role: "user",
                            content: `Sei un ricercatore esperto. Ti viene data una tabella estratta da Elicit con ${finalRows.size} papers (colonne: ${columnNames.join(", ")}).

Il tuo compito è generare un output in italiano (~300 parole) in formato Material for MkDocs, che risponda CHIARAMENTE alla domanda di ricerca implicita nei dati.

Struttura OBBLIGATORIA (usa ESATTAMENTE questo formato con indentazione di 4 spazi):

BLOCCO 1 — Frontmatter YAML (all'inizio):
---
tags:
  - [distretto anatomico, es: rachide, spalla, ginocchio, anca, piede-caviglia]
  - [temi trasversali pertinenti tra: farmacologia, riabilitazione, imaging, pain-management]
---

BLOCCO 2 — Titolo:
# [Titolo descrittivo della scheda]

BLOCCO 3 — Admonitions Material (ATTENZIONE: ogni riga di contenuto deve avere 4 spazi di indentazione):

!!! question "Domanda"
    [Deduci e formula in 1 frase la domanda di ricerca]

!!! abstract "Risposta breve"
    [2-3 frasi nette, come spiegare la conclusione a un collega in 30 secondi]

!!! info "Evidenze chiave"
    - **Punto** (X/Y paper concordano): dettaglio
    - **Punto** (X/Y paper concordano): dettaglio
    - :warning: **Punto debole**: dettaglio dove evidenza è debole o controversa

!!! tip "Bottom line clinica"
    **Raccomandazione.** Dettagli operativi: cosa fare, in che ordine, cosa evitare.

REGOLE:
- Sii diretto e assertivo, non diplomatico
- Se i paper concordano, dillo chiaramente
- Se c'è disaccordo, spiega chi dice cosa e perché
- Non ripetere informazioni tra le sezioni
- CRITICO: rispetta l'indentazione di 4 spazi dentro ogni admonition, altrimenti il rendering si rompe
- NON usare ## heading dentro le admonitions
- Usa :warning: (emoji shortcode) invece di ⚠️ per i punti deboli

DATI:
${plainRows}`
                        }]
                    })
                })
                .then(res => {
                    if (!res.ok) return res.text().then(t => { throw new Error(`API ${res.status}: ${t}`); });
                    return res.json();
                })
                .then(data => {
                    iframe.remove();
                    resolve(data);
                })
                .catch(err => {
                    iframe.remove();
                    reject(err);
                });
            };
        });

        tldr = apiResult.content
            .filter(b => b.type === "text")
            .map(b => b.text)
            .join("\n");
        console.log("✅ TLDR generato con successo.");
    } catch (err) {
        console.error("❌ Errore TLDR:", err);
        tldr = `> ⚠️ Impossibile generare il TLDR automatico: ${err.message}\n> Puoi copiare la tabella e chiedere un riassunto manualmente a Claude.`;
    }

    // --- 6. Assemblaggio output finale ---
    const mdOutput = `${tldr}\n\n---\n\n${tableMarkdown}`;

    // --- 7. Creazione Interfaccia Popup (Overlay) ---
    const oldPopup = document.getElementById('elicit-md-popup');
    if (oldPopup) oldPopup.remove();

    const overlay = document.createElement('div');
    overlay.id = 'elicit-md-popup';
    overlay.style.cssText = `
        position: fixed; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(0,0,0,0.8); z-index: 10000;
        display: flex; justify-content: center; align-items: center;
    `;

    const modal = document.createElement('div');
    modal.style.cssText = `
        background: white; padding: 20px; border-radius: 8px;
        width: 85%; max-width: 900px; height: 70%;
        display: flex; flex-direction: column; gap: 10px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.5);
    `;

    const heading = document.createElement('h3');
    heading.innerText = `Markdown Generato (${finalRows.size} righe × ${numCols} colonne)`;
    heading.style.margin = "0 0 10px 0";
    heading.style.color = "#333";

    const textarea = document.createElement('textarea');
    textarea.value = mdOutput;
    textarea.style.cssText = `
        flex: 1; padding: 10px; border: 1px solid #ccc;
        font-family: monospace; font-size: 12px; resize: none;
    `;

    const btnContainer = document.createElement('div');
    btnContainer.style.cssText = "display: flex; gap: 10px; justify-content: flex-end;";

    const closeBtn = document.createElement('button');
    closeBtn.innerText = "Chiudi";
    closeBtn.onclick = () => overlay.remove();
    closeBtn.style.cssText = "padding: 8px 16px; cursor: pointer;";

    const copyBtn = document.createElement('button');
    copyBtn.innerText = "📋 COPIA NEGLI APPUNTI";
    copyBtn.style.cssText = "padding: 8px 16px; background: #007bff; color: white; border: none; font-weight: bold; cursor: pointer; border-radius: 4px;";

    copyBtn.onclick = () => {
        textarea.select();
        document.execCommand('copy');
        copyBtn.innerText = "✅ Copiato!";
        setTimeout(() => copyBtn.innerText = "📋 COPIA NEGLI APPUNTI", 2000);
    };

    btnContainer.appendChild(closeBtn);
    btnContainer.appendChild(copyBtn);
    modal.appendChild(heading);
    modal.appendChild(textarea);
    modal.appendChild(btnContainer);
    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    console.log(`✅ Estrazione completata: ${finalRows.size} righe, ${numCols} colonne.`);
}

scrapeAndShowPopup();