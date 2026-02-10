---
hide:
  - navigation
---

# OrtoPedia

**Repository evidence-based per condizioni ortopedico-fisiatriche.**

OrtoPedia raccoglie schede cliniche sintetiche basate sulla letteratura scientifica, con un approccio diretto e orientato alla pratica.

## Come sono strutturate le schede

Ogni scheda segue un formato standard:

!!! question "Domanda"
    La domanda clinica a cui la scheda risponde, formulata in modo chiaro e specifico.

!!! abstract "Risposta breve"
    Sintesi in 2-3 frasi — la conclusione che daresti a un collega in 30 secondi.

!!! info "Evidenze chiave"
    I 3-5 punti più importanti dalla letteratura, con indicazione di quanti paper supportano ciascun punto.

!!! tip "Bottom line clinica"
    Cosa fare nella pratica, in che ordine, cosa evitare.

Ogni scheda include anche una **tabella dei paper** con link alle fonti originali.

## Navigazione

### Distretti anatomici

- [Rachide](rachide/index.md) — Patologie e trattamenti del rachide
- [Spalla](spalla/index.md) — Patologie e trattamenti della spalla
- [Ginocchio](ginocchio/index.md) — Patologie e trattamenti del ginocchio
- [Anca](anca/index.md) — Patologie e trattamenti dell'anca
- [Piede & Caviglia](piede-caviglia/index.md) — Patologie e trattamenti del piede e della caviglia

### Sezioni trasversali

- [Farmacologia](farmacologia/index.md) — Evidenze farmacologiche across distretti
- [Riabilitazione](riabilitazione/index.md) — Protocolli riabilitativi e esercizio terapeutico
- [Imaging & Diagnostica](imaging-diagnostica/index.md) — Indicazioni e interpretazione imaging
- [Pain Management](pain-management/index.md) — Gestione del dolore acuto e cronico

## Workflow

Le schede vengono generate con il seguente processo:

1. Formulare una domanda clinica specifica
2. Cercare i paper su [Elicit](https://elicit.com)
3. Eseguire `elicit.js` nella console del browser per estrarre dati e generare il TLDR
4. Revisionare e pubblicare la scheda
