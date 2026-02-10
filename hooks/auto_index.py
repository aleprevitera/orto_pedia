"""MkDocs hook: auto-genera la lista di schede nelle pagine index.md.

Nelle pagine index.md, il marker <!-- AUTO-INDEX --> viene sostituito
con una lista di link a tutti i file .md nella stessa directory
(escluso index.md stesso). Il titolo viene letto dal primo heading #.
"""

import os
import re


def on_page_markdown(markdown, page, config, files, **kwargs):
    if "<!-- AUTO-INDEX -->" not in markdown:
        return markdown

    docs_dir = config["docs_dir"]
    page_dir = os.path.dirname(os.path.join(docs_dir, page.file.src_path))

    links = []
    for fname in sorted(os.listdir(page_dir)):
        if not fname.endswith(".md") or fname == "index.md":
            continue

        filepath = os.path.join(page_dir, fname)
        with open(filepath, "r", encoding="utf-8") as fh:
            content = fh.read()

        title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if title_match:
            title = title_match.group(1).strip()
        else:
            title = fname.replace(".md", "").replace("-", " ").title()

        links.append(f"- [{title}]({fname})")

    if links:
        replacement = "\n".join(links)
    else:
        replacement = "*Nessuna scheda ancora disponibile. In costruzione.*"

    return markdown.replace("<!-- AUTO-INDEX -->", replacement)
