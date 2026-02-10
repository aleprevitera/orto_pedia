# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**orto_pedia** is an evidence-based knowledge repository for orthopedic and physiatric conditions, built with Material for MkDocs. Content is written in Italian.

## Build & Serve Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Local development server (hot-reload)
mkdocs serve

# Build static site
mkdocs build --strict

# Deploy manually to GitHub Pages (normally handled by CI)
mkdocs gh-deploy
```

## Project Structure

- `mkdocs.yml` — MkDocs configuration (theme, plugins, nav, extensions)
- `docs/` — All site content (Markdown pages)
  - `docs/rachide/`, `docs/spalla/`, etc. — Anatomical district sections
  - `docs/farmacologia/`, `docs/riabilitazione/`, etc. — Cross-cutting sections
  - `docs/includes/abbreviations.md` — Medical abbreviation glossary (auto-appended)
  - `docs/assets/extra.css` — Custom CSS for table responsiveness
- `elicit.js` — Browser script for Elicit.com AG-Grid data extraction + Claude TLDR generation
  - Supports tables with any number of columns (handles AG-Grid column virtualization via horizontal scrolling)
  - Uses `col-id` attributes to map cells to the correct column across scroll positions
  - Waits up to 10s for rows to render before starting capture (handles slow grid loading)
  - Scrolls both vertically (rows) and horizontally (virtualized columns) to capture all data
- `.github/workflows/deploy.yml` — CI/CD: auto-deploy to GitHub Pages on push to main

## Content Format

Each clinical page uses Material for MkDocs admonitions:

- `!!! question` — Research question
- `!!! abstract` — Brief answer
- `!!! info` — Key evidence with paper counts
- `!!! tip` — Clinical bottom line

Pages must have YAML frontmatter with `tags` for cross-referencing.

## Language

All clinical/medical content should be written in Italian unless otherwise specified.

## Security

Never commit API keys. The `elicit.js` file has a placeholder for the Anthropic API key — it must be filled in at runtime and never pushed to the repo.
