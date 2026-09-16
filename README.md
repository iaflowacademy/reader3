# reader3

![reader3](reader3.png)

A lightweight, self-hosted EPUB reader for reading books together with an LLM. Get an EPUB
(e.g. from [Project Gutenberg](https://www.gutenberg.org/)), open it up here, and either
select any passage to ask a question about it, or ask for a chapter summary — no more
switching tabs and manually copy-pasting text into a chatbot.

This is a fork of [karpathy/reader3](https://github.com/karpathy/reader3), which the
original author released as a 90%-vibe-coded illustration and explicitly said he wouldn't
maintain. 488 forks and 24 unmerged PRs later, the most-requested feature — actually talking
to an LLM about what you're reading — still didn't exist. This fork adds it, plus the other
things people kept asking for: reading progress, highlights, and a copy button that doesn't
require selecting text by hand.

## What's new in this fork

- **Ask AI** — select any passage and ask a question about it, or ask about the whole
  chapter. Streamed responses via the Anthropic API.
- **Summarize chapter** — one click, no selection needed.
- **Highlights** — select text → Highlight. Persisted in SQLite, rendered on every visit,
  click a highlight to remove it.
- **Reading progress** — automatically remembers your last chapter per book; the library
  shows a progress bar and "Continue Reading" instead of always starting at chapter 1.
- **Copy buttons** — copy a selection or the whole chapter in one click.
- **Keyboard navigation** — ← / → to move between chapters.
- **Mobile-responsive** — the sidebar collapses behind a menu button below ~820px.
- A real `LICENSE` file (the original repo only mentioned MIT in prose).

Still true to the original's spirit: no auth, no multi-user, no database server — just
SQLite and pickle files, one process, `uv run`.

## Usage

The project uses [uv](https://docs.astral.sh/uv/).

1. Download an EPUB (e.g. [Dracula](https://www.gutenberg.org/ebooks/345)) to this
   directory as `dracula.epub`, then process it:

   ```bash
   uv run reader3.py dracula.epub
   ```

   This creates `dracula_data/`, which registers the book to your local library.

2. (Optional, but you want this) Set your Anthropic API key to enable the AI chat panel:

   ```bash
   cp .env.example .env
   # then edit .env and paste your key from https://console.anthropic.com/
   ```

   Without a key, the reader still works fully as an EPUB viewer — the chat panel just
   shows a message telling you to set one.

3. Run the server:

   ```bash
   uv run server.py
   ```

   Visit [localhost:8123](http://localhost:8123/) to see your library. Add more books by
   repeating step 1; remove one by deleting its `_data` folder.

## Architecture

- `reader3.py` — parses an EPUB into a `Book` object (metadata, spine, TOC, images),
  pickled to `<name>_data/book.pkl`. Unchanged from upstream.
- `server.py` — FastAPI app: library/reader routes, plus `/api/chat` (streaming),
  `/api/highlights` (CRUD), and progress tracking.
- `db.py` — SQLite persistence for reading progress and highlights. No ORM.
- `llm.py` — thin streaming wrapper around the Anthropic API. Bring your own key.
- `templates/` — Jinja2 + vanilla JS, no frontend framework or build step.

## License

MIT — see [LICENSE](LICENSE). Original reader3 by Andrej Karpathy.
