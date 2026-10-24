"""REEZ brain: answers from the files in docs/, thinks for itself, and handles file requests."""

import hashlib
from difflib import SequenceMatcher
import html
import re
from pathlib import Path

from pypdf import PdfReader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings, ChatOllama
from langchain_chroma import Chroma

BASE_DIR = Path(__file__).parent
DOCS_DIR = BASE_DIR / "docs"
DB_DIR = BASE_DIR / "chroma_db"
SIG_FILE = BASE_DIR / "chroma_sig.txt"

CHAT_MODEL = "gemma3:4b"
EMBED_MODEL = "nomic-embed-text"
FULL_LIMIT = 7500
GENERIC = {"resume", "updated", "final", "copy", "document", "docs", "file", "latest", "new"}
STOP = {
    "this", "that", "have", "with", "from", "there", "their", "which", "about",
    "according", "mentioned", "listed", "found", "appears", "include", "includes",
    "also", "only", "document", "documents", "resume", "resumes", "name", "what",
    "where", "when", "your", "than", "they", "them", "been", "were", "does", "into",
    "these", "those", "would", "could", "should", "called", "named", "none",
    "nothing", "neither", "both", "several", "multiple", "zero", "one", "two",
    "three", "four", "five", "six", "seven", "eight", "nine", "ten", "know",
}
READABLE = (".pdf", ".txt", ".md", ".csv", ".json", ".html", ".htm", ".xml", ".log", ".py", ".js",
            ".java", ".c", ".cpp", ".sql", ".yaml", ".yml", ".docx", ".pptx", ".xlsx")

embeddings = OllamaEmbeddings(model=EMBED_MODEL)
llm = ChatOllama(num_ctx=4096, keep_alive="30m", model=CHAT_MODEL, temperature=0, num_predict=120)
think_llm = ChatOllama(num_ctx=4096, keep_alive="30m", model=CHAT_MODEL, temperature=0.4, num_predict=150)

_db = None
_cache = {"sig": None, "pages": [], "texts": {}}


def _open_db():
    global _db
    if _db is None:
        _db = Chroma(persist_directory=str(DB_DIR), embedding_function=embeddings)
    return _db


def _all_files():
    return sorted(p for p in DOCS_DIR.glob("**/*") if p.is_file())


def _doc_files():
    return sorted(p for p in DOCS_DIR.glob("**/*") if p.is_file() and p.suffix.lower() in READABLE)


def _signature():
    parts = []
    for p in _doc_files():
        s = p.stat()
        parts.append(p.name + str(s.st_size) + str(int(s.st_mtime)))
    return hashlib.md5("|".join(parts).encode()).hexdigest()


def _read_other(path):
    """Plain text out of text, HTML, Word, PowerPoint and Excel files."""
    suffix = path.suffix.lower()
    try:
        if suffix in (".docx", ".pptx", ".xlsx"):
            import zipfile
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                if suffix == ".docx":
                    parts = ["word/document.xml"]
                elif suffix == ".pptx":
                    parts = sorted((n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                                   key=lambda n: int(re.findall(r"\d+", n)[0]))
                else:
                    parts = ["xl/sharedStrings.xml"]
                raw = "\n".join(z.read(n).decode("utf-8", "ignore") for n in parts if n in names)
            raw = re.sub(r"</(w:p|a:p|si)>", "\n", raw)
            raw = html.unescape(re.sub(r"<[^>]+>", "", raw))
        else:
            raw = path.read_bytes()[:2000000].decode("utf-8", "ignore")
            if suffix in (".html", ".htm"):
                raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
                raw = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    except Exception:
        return ""
    return "\n".join(" ".join(line.split()) for line in raw.splitlines() if line.strip())


def _read_docs():
    pages = []
    for path in _doc_files():
        if path.suffix.lower() != ".pdf":
            body = _read_other(path)
            if body:
                pages.append(Document(page_content=body, metadata={"source": str(path), "page": 1}))
            continue
        try:
            reader = PdfReader(str(path))
        except Exception:
            continue
        for number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            links = []
            for annot in page.get("/Annots") or []:
                try:
                    action = annot.get_object().get("/A")
                    uri = action.get_object().get("/URI") if action else None
                except Exception:
                    uri = None
                if uri:
                    links.append(str(uri))
            if links:
                text += "\nLinks on this page: " + ", ".join(sorted(set(links)))
            if text.strip():
                pages.append(Document(page_content=text, metadata={"source": str(path), "page": number}))
    return pages


def _load():
    """File text, read once and kept in memory until a file changes."""
    sig = _signature()
    if sig != _cache["sig"]:
        pages = _read_docs()
        texts = {}
        for page in pages:
            name = Path(page.metadata["source"]).name
            texts[name] = texts.get(name, "") + page.page_content + "\n"
        _cache.update(sig=sig, pages=pages, texts=texts)
    return _cache["pages"], _cache["texts"]


def ingest():
    global _db
    pages = _load()[0]
    if not pages:
        return 0
    chunks = RecursiveCharacterTextSplitter(chunk_size=600, chunk_overlap=100).split_documents(pages)
    try:
        _open_db().delete_collection()
    except Exception:
        pass
    _db = Chroma.from_documents(chunks, embeddings, persist_directory=str(DB_DIR))
    SIG_FILE.write_text(_signature())
    return len(chunks)


def _ensure_db():
    try:
        fresh = DB_DIR.exists() and SIG_FILE.exists() and SIG_FILE.read_text() == _signature()
    except Exception:
        fresh = False
    if not fresh:
        ingest()


def prepare():
    """Called once at start: loads the files, the search index and the model."""
    _load()
    _ensure_db()
    llm.invoke("Reply with the word ok.")


def _search(question, k=6):
    try:
        _ensure_db()
        return _open_db().similarity_search(question, k=k)
    except Exception:
        return []


def retrieve(question, k=8):
    return _search(question, k)


FILE_QUESTION = re.compile(
    r"(which|what|list|show|how many)\s+(pdfs?|files|documents)\b"
    r"|(pdf|file|document)s?\s+(named|called)"
    r"|(is there|are there|do you have|can you find).{0,40}(pdfs?|file|document)",
    re.IGNORECASE,
)


def _matching_files(question, names):
    words = [w for w in re.findall(r"[a-z]+", question.lower()) if len(w) >= 4]
    hits = []
    for name in names:
        tokens = [t for t in re.findall(r"[a-z]+", Path(name).stem.lower()) if len(t) >= 4 and t not in GENERIC]
        for t in tokens:
            if any(t == w or (len(w) >= 5 and (t.startswith(w) or w.startswith(t)))
                   or SequenceMatcher(None, t, w).ratio() >= 0.85 for w in words):
                hits.append(name)
                break
    return hits

def _file_reply(question):
    if not FILE_QUESTION.search(question):
        return None
    names = sorted(p.name for p in _all_files())
    if not names:
        return "There are no files in the docs folder yet."
    found = _matching_files(question, names)
    asked_for_one = re.search(r"named|called|find|is there|do you have", question, re.IGNORECASE)
    if found:
        return "Yes, I found " + ", ".join(found) + "."
    if asked_for_one:
        return "No file with that name is in the docs folder. I have: " + ", ".join(names) + "."
    return "I have " + str(len(names)) + " files: " + ", ".join(names) + "."


def _context_for(question):
    """What the AI reads: whole documents when one is named, otherwise the best matching chunks."""
    pages, texts = _load()
    if not texts:
        return "", [], False
    chosen = _matching_files(question, list(texts))
    if chosen:
        per = FULL_LIMIT // len(chosen)
        parts = ["[Document: " + n + "]\n" + texts[n][:per] for n in chosen]
        return "\n\n".join(parts), chosen, True
    results = _search(question)
    if results:
        parts, sources = [], set()
        for doc in results:
            name = Path(doc.metadata.get("source", "")).name
            sources.add(name)
            parts.append("[Document: " + name + "]\n" + doc.page_content)
        return "\n\n".join(parts), sorted(sources), False
    per = FULL_LIMIT // len(texts)
    return "\n\n".join("[Document: " + n + "]\n" + t[:per] for n, t in texts.items()), sorted(texts), False


def _stem(word):
    return word[:-1] if word.endswith("s") and len(word) > 4 else word


def _supported(reply, context, question):
    ctx = {_stem(w) for w in re.findall(r"[a-z0-9]+", context.lower())}
    known = {_stem(w) for w in re.findall(r"[a-z0-9]+", question.lower())}
    words = [_stem(w) for w in re.findall(r"[a-z]{4,}", reply.lower()) if w not in STOP]
    words = [w for w in words if w not in known]
    if not words:
        return True
    return sum(w in ctx for w in words) / len(words) >= 0.6


ANALYZE = re.compile(
    r"\b(score|rate|rating|review|evaluate|evaluation|feedback|suggest\w*|improv\w*|better|"
    r"opinion|think|compare|comparison|strengths?|weakness\w*|advice|recommend\w*|critique|"
    r"ats|impressive|worth)\b", re.IGNORECASE)


def _analyse(question, context):
    """Thinking mode: use the document as facts, then give a real judgement."""
    prompt = (
        "You are REEZ, a sharp, honest personal AI assistant and career reviewer.\n"
        "Use the document below as your facts, but think for yourself and give a clear judgement, not just a quote.\n"
        "If asked for a score, give a number out of 10, then two or three short reasons "
        "(one strength, one weakness, one fix).\n"
        "Be specific and use only facts from the document. Plain text only, no markdown, at most 60 words.\n\n"
        "Document:\n" + context + "\n\nRequest: " + question + "\nReply:"
    )
    text = re.sub(r"[*#_`]", "", think_llm.invoke(prompt).content)
    return " ".join(text.split()) or "I could not form an opinion on that."


def general(question, history=None):
    """Questions that are not about the stored files: REEZ answers from its own knowledge."""
    recent = "\n".join("User: " + q + "\nREEZ: " + a for q, a in (history or [])[-2:])
    prompt = (
        "You are REEZ, a clear and helpful personal AI assistant. Answer the question directly "
        "in at most three short sentences. If you are not sure, say so briefly. Plain text, no markdown.\n"
        + (("\nRecent conversation:\n" + recent + "\n") if recent else "")
        + "\nQuestion: " + question + "\nAnswer:"
    )
    text = re.sub(r"[*#_`]", "", think_llm.invoke(prompt).content)
    return " ".join(text.split()) or "I am not sure about that."


BULLET = "\u2022"
FLAT = ("skills", "certificates", "achievements", "languages", "interests")
TITLES = {"skills": "Skills", "certificates": "Certificates", "education": "Education", "projects": "Projects",
          "experience": "Experience", "achievements": "Achievements", "languages": "Languages",
          "interests": "Interests", "summary": "Summary", "contact": "Contact"}
SECTIONS = {
    "skills": r"(?:technical |key |core |soft |professional )?skills?(?: ?(?:and|&) ?(?:tools|technologies|abilities))?|tools(?: ?(?:and|&) ?technologies)?|technologies|core competenc(?:y|ies)",
    "certificates": r"certifications?(?: ?(?:and|&) ?(?:courses|achievements|awards|licen[sc]es))?|certificates?(?: ?(?:and|&) ?\w+)?|licen[sc]es(?: ?(?:and|&) ?certifications?)?|courses(?: ?(?:and|&) ?certifications?)?",
    "education": r"education(?:al)?(?: (?:details|background|qualifications?))?|academic(?: (?:details|background|qualifications?|profile))?|qualifications?",
    "projects": r"(?:academic |personal |key |major |mini )?projects?(?: work)?",
    "experience": r"(?:work |professional |industrial )?experience|internships?(?: ?(?:and|&) ?\w+)?|employment(?: history)?|work history",
    "achievements": r"achievements?|awards?(?: ?(?:and|&) ?(?:honou?rs|achievements|recognitions?))?|honou?rs|accomplishments|extra ?curricular(?: activities)?",
    "summary": r"(?:career |professional )?(?:summary|objective|profile)|about me",
    "languages": r"languages?(?: known)?",
    "interests": r"interests?|hobbies(?: ?(?:and|&) ?interests?)?",
    "contact": r"contact(?: (?:details|information|info))?|personal (?:details|information)",
}
_HEADS = {key: re.compile(r"^(?:" + pat + r")$", re.IGNORECASE) for key, pat in SECTIONS.items()}
ASKED = [
    ("skills", r"\bskills?\b|\bskillset\b"),
    ("certificates", r"\bcertificat\w*|\blicen[sc]es?\b"),
    ("projects", r"\bprojects?\b"),
    ("education", r"\beducation\b|\bdegree\b|\bqualifications?\b|\bacademics?\b|\bcgpa\b"),
    ("experience", r"\binternships?\b|\bexperience\b"),
    ("achievements", r"\bachievements?\b|\bawards?\b|\bhonou?rs\b"),
    ("languages", r"\blanguages? known\b|\bspoken languages?\b"),
    ("interests", r"\binterests?\b|\bhobbies\b"),
    ("summary", r"\bsummary\b|\bobjective\b"),
]
YESNO = re.compile(r"^\s*(does|do|is|are|has|have|can|did|was|were)\b", re.IGNORECASE)
ORDINALS = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3, "last": -1}
_BUL = re.compile(r"^[\u2022\u25cf\u25aa\u2023\u25e6\u00b7*\u2013\u2014-]+\s*(.*)$")
_LAB = re.compile(r"^[A-Za-z][A-Za-z &/+().-]{1,38}:\s*\S")


def display_name(item, text=None):
    """A friendly name for a file: 'Balamurali resume', or the file name without its type."""
    name = item.name if hasattr(item, "name") else str(item)
    stem = Path(name).stem
    if text is None:
        text = _load()[1].get(name, "")
    resume = len(re.findall(r"(?i)\b(education|skills|experience|projects|internships?|certifications?)\b", text)) >= 2
    tokens = [t for t in re.findall(r"[A-Za-z]{3,}", stem) if t.lower() not in GENERIC]
    if resume and tokens:
        return tokens[0].title() + " resume"
    return " ".join(stem.replace("_", " ").split())


def _heading_of(line):
    """(section, rest of the line) if the line starts a known section, ("other", "") for another heading."""
    raw = line.strip()
    if not raw or len(raw) > 160:
        return None, None
    head, rest = raw, ""
    m = re.match(r"^([A-Za-z][A-Za-z &/]{2,38}?)\s*[:\u2013\u2014-]\s*(.*)$", raw)
    if m:
        head, rest = m.group(1).strip(), m.group(2).strip()
    head = head.strip(" :-\u2013\u2014")
    for key, pat in _HEADS.items():
        if pat.match(head):
            return key, rest
    for key, pat in SECTIONS.items():
        m2 = re.match(r"^(" + pat + r")\b\s*(.*)$", raw)
        if m2 and m2.group(1).isupper() and len(m2.group(1)) >= 4:
            return key, m2.group(2).strip(" :-\u2013\u2014")
    if not rest and 1 <= len(head.split()) <= 4 and re.fullmatch(r"[A-Z][A-Z &/]+", head):
        return "other", ""
    return None, None


def _split_sections(text):
    """Cut a resume into its sections: skills, certificates, education, projects and so on."""
    sections, current = {}, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        key, rest = _heading_of(line)
        if key and key != "other":
            if rest and current is not None and (key == current or key in ("languages", "interests", "contact")):
                if current == key or current == "skills":
                    sections[current].append(line)
                    continue
            current = key
            sections.setdefault(key, [])
            if rest:
                sections[key].append(rest)
            continue
        if key == "other":
            current = "other"
            continue
        if current and current != "other":
            sections[current].append(line)
    return sections


def _entries(lines):
    cleaned = [l.strip() for l in lines if l.strip()]
    structured = any(_BUL.match(l) or _LAB.match(l) for l in cleaned)
    entries = []
    for line in cleaned:
        m = _BUL.match(line)
        text = (m.group(1) if m else line).strip()
        starts = bool(m) or bool(_LAB.match(line))
        if entries and structured and not starts:
            entries[-1] += ("" if entries[-1].endswith("-") else " ") + text
        else:
            entries.append(text)
    return [e for e in entries if e]


def _items(entry):
    label = ""
    m = re.match(r"^([A-Za-z][A-Za-z &/+().-]{1,38}):\s*(.*)$", entry)
    if m:
        label, entry = m.group(1).strip(), m.group(2).strip()
    items, depth, buf = [], 0, ""
    for ch in entry:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if depth == 0 and ch in ",;|\u2022":
            if buf.strip():
                items.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        items.append(buf.strip())
    return label, [i.strip(" .") for i in items if i.strip(" .")]


def _groups(key, lines):
    groups = []
    for entry in _entries(lines):
        if key in ("skills", "languages", "interests"):
            label, items = _items(entry)
        else:
            label, items = "", [entry]
        if items:
            groups.append((label, items))
    return groups


def _section_of(question):
    best, pos = None, 10 ** 6
    for key, pat in ASKED:
        m = re.search(pat, question, re.IGNORECASE)
        if m and m.start() < pos:
            best, pos = key, m.start()
    return best


def _ordinal(question):
    for word, index in ORDINALS.items():
        if re.search(r"\b" + word + r"\b", question, re.IGNORECASE):
            return index
    return None


def _section_answer(question):
    """List or count one section of the resumes. The document name comes first, then bullets."""
    key = _section_of(question)
    if key is None or ANALYZE.search(question):
        return None
    count_mode = bool(re.search(r"\bhow many\b|\bcount\b|\bnumber of\b", question, re.IGNORECASE))
    ordinal = _ordinal(question)
    if (YESNO.match(question) and not count_mode) or ((count_mode or ordinal is not None) and key not in FLAT):
        return None
    pages, texts = _load()
    names = _matching_files(question, list(texts)) or list(texts)
    blocks, used = [], []
    for name in names:
        lines = _split_sections(texts[name]).get(key)
        groups = _groups(key, lines) if lines else []
        if not groups:
            continue
        label = display_name(name, texts[name])
        flat = [item for _l, items in groups for item in items]
        if ordinal is not None:
            if not -len(flat) <= ordinal < len(flat):
                continue
            blocks.append(label + "\n" + BULLET + " " + flat[ordinal])
        else:
            out = [label]
            if count_mode:
                out.append(TITLES[key] + ": " + str(len(flat)))
            for group_label, items in groups:
                if group_label:
                    out.append(group_label)
                out.extend(BULLET + " " + item for item in items)
            blocks.append("\n".join(out))
        used.append(name)
    if not blocks:
        return None
    return "\n\n".join(blocks), used


def answer(question, spoken=False):
    reply = _file_reply(question)
    if reply:
        return reply, []
    found = _section_answer(question)
    if found:
        return found
    context, sources, named = _context_for(question)
    if not context:
        return "I have no documents yet. Add files to the docs folder.", []
    label = display_name(sources[0]) + "\n" if named and len(sources) == 1 else ""
    if ANALYZE.search(question):
        return label + _analyse(question, context), sources
    key = _section_of(question)
    note = ("The question is only about the " + key + " section. Do not include items from other sections "
            "(certificates are not skills, projects are not experience).\n") if key else ""
    style = "Use plain spoken English with no bullet points or symbols.\n" if spoken else ""
    prompt = (
        "You are REEZ, a personal AI assistant. Answer using ONLY the context below.\n"
        "Each part starts with the document it came from; say which document when more than one is present.\n"
        "Give the complete answer in at most two short sentences. For a list, name every item separated by commas. "
        "For how many, list the items first and then give the count.\n"
        "Only if the context truly does not contain the answer, reply with exactly: NOT FOUND\n"
        + note + style + "\nContext:\n" + context + "\n\nQuestion: " + question + "\nAnswer:"
    )
    text = " ".join(re.sub(r"[*#_`]", "", llm.invoke(prompt).content).split())
    text = re.sub(r"(?i)^answer:\s*", "", text)
    if not text or text.upper().startswith("NOT FOUND"):
        where = (" in " + sources[0]) if named and len(sources) == 1 else " in your documents"
        return "I could not find that" + where + ".", []
    if not named and not _supported(text, context, question):
        return "I could not find that in your documents.", []
    return label + text, sources

OPEN_WORDS = re.compile(r"\b(open|launch)\b", re.IGNORECASE)
SHOW_WORDS = re.compile(r"\b(give|show|print|display|paste|send|get|see|view|read)\b", re.IGNORECASE)
CODE_WORDS = re.compile(r"\b(code|source|html|markup|script)\b", re.IGNORECASE)
REF_WORDS = re.compile(r"\b(it|that|this|the file|that file|this file|the document)\b", re.IGNORECASE)
QUESTIONY = re.compile(
    r"^\s*(what|who|which|how|give|show|tell|explain|summari[sz]e|read|list|describe|is|does|can|rate|review|score)\b",
    re.IGNORECASE)


def named_file(question):
    files = _all_files()
    hits = _matching_files(question, [p.name for p in files])
    if not hits:
        return None
    for p in files:
        if p.name == hits[0]:
            return p
    return None


def refers_to_last(question):
    return bool(REF_WORDS.search(question)) and bool(QUESTIONY.search(question))


def tanglish_commands(text):
    """open pannu means open it, delete pannu means delete it."""
    return re.sub(r"\b(\w+)\s+(pannu|pannunga|pannidu|pannidunga)\b", r"\1 it", text, flags=re.IGNORECASE)


def file_command(question, last=None):
    """Direct file requests: show the code of a file, or open it. No AI needed."""
    target = named_file(question)
    if target is None and last is not None and last.exists() and REF_WORDS.search(question):
        target = last
    if target is None:
        return None
    if OPEN_WORDS.search(question):
        return ("open", target)
    if CODE_WORDS.search(question) and SHOW_WORDS.search(question):
        return ("code", target)
    return None


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "ingest":
        count = ingest()
        print("Done. Stored " + str(count) + " chunks." if count else "No readable files found.")
    else:
        print("REEZ brain test. Type exit to quit.")
        while True:
            q = input("\nYou: ").strip()
            if q.lower() in ("exit", "quit"):
                break
            if q:
                print("REEZ:", answer(q)[0])

