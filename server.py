import os
import pickle
from functools import lru_cache
from typing import Optional


def _load_dotenv(path: str = ".env"):
    """Tiny .env loader — no extra dependency for one file."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

from contextlib import asynccontextmanager

from bs4 import BeautifulSoup, NavigableString
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import db
from reader3 import Book, BookMetadata, ChapterContent, TOCEntry
from llm import stream_chat, LLMNotConfigured, LLMError


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")

# Where are the book folders located?
BOOKS_DIR = "."


def _is_safe_path_segment(value: str) -> bool:
    """
    Rejects anything that could escape BOOKS_DIR: path separators, '..',
    absolute paths, or the bare '.' / '..' segments. book_id and image_name
    both come straight from the URL and are used to build filesystem paths,
    so this must run before either ever touches os.path.join/os.listdir.
    """
    if not value or value in (".", ".."):
        return False
    if "/" in value or "\\" in value or ".." in value:
        return False
    if os.path.isabs(value):
        return False
    return True


@lru_cache(maxsize=10)
def load_book_cached(folder_name: str) -> Optional[Book]:
    """
    Loads the book from the pickle file.
    Cached so we don't re-read the disk on every click.
    """
    if not _is_safe_path_segment(folder_name):
        return None

    file_path = os.path.join(BOOKS_DIR, folder_name, "book.pkl")
    if not os.path.exists(file_path):
        return None

    try:
        with open(file_path, "rb") as f:
            book = pickle.load(f)
        return book
    except Exception as e:
        print(f"Error loading book {folder_name}: {e}")
        return None


def apply_highlights(html: str, highlights) -> str:
    """Wraps the first occurrence of each highlight's text in a <mark> tag."""
    if not highlights:
        return html
    soup = BeautifulSoup(html, "html.parser")
    for h in highlights:
        needle = h.text.strip()
        if not needle:
            continue
        match = soup.find(string=lambda s: isinstance(s, NavigableString) and needle in s)
        if not match:
            continue
        idx = str(match).find(needle)
        before, after = str(match)[:idx], str(match)[idx + len(needle):]
        mark = soup.new_tag("mark")
        mark["class"] = "hl"
        mark["data-highlight-id"] = str(h.id)
        mark.string = needle
        new_nodes = ([NavigableString(before)] if before else []) + [mark] + ([NavigableString(after)] if after else [])
        match.replace_with(*new_nodes)
    return str(soup)


@app.get("/", response_class=HTMLResponse)
async def library_view(request: Request):
    """Lists all available processed books, with reading progress."""
    books = []
    progress = db.get_all_progress()

    if os.path.exists(BOOKS_DIR):
        for item in os.listdir(BOOKS_DIR):
            if item.endswith("_data") and os.path.isdir(item):
                book = load_book_cached(item)
                if book:
                    chapter_index = progress.get(item)
                    books.append({
                        "id": item,
                        "title": book.metadata.title,
                        "author": ", ".join(book.metadata.authors),
                        "chapters": len(book.spine),
                        "progress_index": chapter_index,
                        "progress_pct": round((chapter_index + 1) / len(book.spine) * 100) if chapter_index is not None and book.spine else None,
                    })

    return templates.TemplateResponse("library.html", {"request": request, "books": books})


@app.get("/read/{book_id}", response_class=HTMLResponse)
async def redirect_to_first_chapter(request: Request, book_id: str):
    """Jumps to saved progress if any, otherwise chapter 0."""
    saved = db.get_progress(book_id)
    return await read_chapter(request=request, book_id=book_id, chapter_index=saved or 0)


@app.get("/read/{book_id}/{chapter_index}", response_class=HTMLResponse)
async def read_chapter(request: Request, book_id: str, chapter_index: int):
    """The main reader interface."""
    book = load_book_cached(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    if chapter_index < 0 or chapter_index >= len(book.spine):
        raise HTTPException(status_code=404, detail="Chapter not found")

    current_chapter = book.spine[chapter_index]
    db.set_progress(book_id, chapter_index)

    highlights = db.get_highlights(book_id, chapter_index)
    rendered_content = apply_highlights(current_chapter.content, highlights)

    prev_idx = chapter_index - 1 if chapter_index > 0 else None
    next_idx = chapter_index + 1 if chapter_index < len(book.spine) - 1 else None

    return templates.TemplateResponse("reader.html", {
        "request": request,
        "book": book,
        "current_chapter": current_chapter,
        "rendered_content": rendered_content,
        "highlights": highlights,
        "chapter_index": chapter_index,
        "book_id": book_id,
        "prev_idx": prev_idx,
        "next_idx": next_idx
    })


@app.get("/read/{book_id}/images/{image_name}")
async def serve_image(book_id: str, image_name: str):
    """
    Serves images specifically for a book.
    The HTML contains <img src="images/pic.jpg">.
    The browser resolves this to /read/{book_id}/images/pic.jpg.
    """
    if not _is_safe_path_segment(book_id) or not _is_safe_path_segment(image_name):
        raise HTTPException(status_code=404, detail="Image not found")

    img_path = os.path.join(BOOKS_DIR, book_id, "images", image_name)

    if not os.path.exists(img_path):
        raise HTTPException(status_code=404, detail="Image not found")

    return FileResponse(img_path)


# --- Highlights API ---

class HighlightIn(BaseModel):
    book_id: str
    chapter_index: int
    text: str


@app.post("/api/highlights")
async def create_highlight(payload: HighlightIn):
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty highlight text")
    if len(text) > 2000:
        raise HTTPException(status_code=400, detail="Highlight too long")
    highlight_id = db.add_highlight(payload.book_id, payload.chapter_index, text)
    return {"id": highlight_id}


@app.delete("/api/highlights/{highlight_id}")
async def remove_highlight(highlight_id: int):
    db.delete_highlight(highlight_id)
    return {"ok": True}


# --- Chat API (streaming) ---

class ChatIn(BaseModel):
    book_id: str
    chapter_index: int
    question: str
    selection: Optional[str] = None
    history: Optional[list] = None


MAX_QUESTION_LEN = 4000
MAX_HISTORY_TURNS = 20


@app.post("/api/chat")
async def chat(payload: ChatIn):
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Empty question")
    if len(question) > MAX_QUESTION_LEN:
        raise HTTPException(status_code=400, detail=f"Question too long (max {MAX_QUESTION_LEN} chars)")
    if payload.history is not None and len(payload.history) > MAX_HISTORY_TURNS:
        raise HTTPException(status_code=400, detail=f"Too much history (max {MAX_HISTORY_TURNS} turns)")

    book = load_book_cached(payload.book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    if payload.chapter_index < 0 or payload.chapter_index >= len(book.spine):
        raise HTTPException(status_code=404, detail="Chapter not found")

    chapter = book.spine[payload.chapter_index]
    context = payload.selection.strip() if payload.selection else chapter.text
    # Cap context length so we don't blow the context window on a giant chapter.
    context = context[:12000]

    def gen():
        try:
            for chunk in stream_chat(
                question=question,
                context=context,
                title=book.metadata.title,
                authors=", ".join(book.metadata.authors),
                chapter_title=chapter.title,
                history=payload.history,
            ):
                yield chunk
        except LLMNotConfigured as e:
            yield f"⚠️ {e}"
        except LLMError as e:
            yield f"⚠️ {e}"

    return StreamingResponse(gen(), media_type="text/plain")


if __name__ == "__main__":
    import uvicorn
    print("Starting server at http://127.0.0.1:8123")
    uvicorn.run(app, host="127.0.0.1", port=8123)
