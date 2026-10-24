"""REEZ understanding: routing, mistake fixing, follow-ups, Tanglish."""

import json
import re
import time
from difflib import SequenceMatcher
from pathlib import Path

from langchain_ollama import ChatOllama

import brain
from brain import CHAT_MODEL, DOCS_DIR

json_llm = ChatOllama(num_ctx=4096, keep_alive="30m", model=CHAT_MODEL, temperature=0, format="json", num_predict=100)
chat_llm = ChatOllama(num_ctx=4096, keep_alive="30m", model=CHAT_MODEL, temperature=0.3, num_predict=70)

MAX_HISTORY = 4
GREETINGS = {"hi", "hello", "hey", "thanks", "thank you", "ok", "okay"}
EXIT_PATTERN = re.compile(r"\b(goodbye|exit|quit|stop listening)\b", re.IGNORECASE)
TANGLISH = re.compile(
    r"\b(enna|epdi|eppadi|irukku|iruku|irukken|illa|illai|pannu|panra|pandra|solra|sollu|"
    r"sollunga|venum|venam|theriyala|puriyala|nalla|romba|konjam|ippo|appuram|apram|seri|"
    r"aama|da|di|machan|bhai|oi|dei|ennaku|enakku|unakku|naan|neenga|nee|pathi|achu|aachu|"
    r"mudinjidhu|iruka|irukka|irukkaa|enga|yaaru|yen|evlo|edhu|sapteengala|vanakkam|nandri|"
    r"paaru|paarunga|kaattu|kaattunga|thedu|vidu|podhum)\b", re.IGNORECASE)
DOC_WORDS = re.compile(
    r"\b(resume|cv|skills?|projects?|degree|education|college|school|experience|internships?|"
    r"certificat\w*|linkedin|github|portfolio|email|phone|contact|address|achievements?|"
    r"languages?|summary|objective|pdfs?|documents?|files?|marks|cgpa|gpa|percentage)\b", re.IGNORECASE)
SMALL_TALK = re.compile(
    r"\b(how are you|who are you|what'?s up|whats up|your name|thank(s| you)|"
    r"good (morning|afternoon|evening|night)|are you there|can you hear)\b", re.IGNORECASE)
FOLLOW_UP = re.compile(
    r"\b(it|its|that|this|those|these|he|his|she|her|they|their|them|him|the second|"
    r"the first|the last|same|also|more)\b", re.IGNORECASE)

_files = {}
_state = {"docs": False, "at": 0.0}


def _read_lines(name):
    path = Path(__file__).parent / name
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return []
    cached = _files.get(name)
    if not cached or cached[0] != stamp:
        text = path.read_text(encoding="utf-8-sig")
        _files[name] = (stamp, [l.strip() for l in text.splitlines() if l.strip()])
    return _files[name][1]


def _tokens(text):
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _pick_words(text):
    toks = _tokens(text)
    out = []
    for line in _read_lines("tanglish.txt"):
        key = line.split("=", 1)[0].strip()
        if key and _tokens(key) & toks:
            out.append(line)
    return "\n".join(out[:25])


def _pick_examples(text, n=10):
    toks = _tokens(text)
    scored = []
    for line in _read_lines("replies.txt"):
        head = line.split("|", 1)[0].replace("You:", "").strip()
        overlap = len(_tokens(head) & toks)
        if overlap:
            scored.append((overlap, line))
    scored.sort(key=lambda item: -item[0])
    return "\n".join(line for _, line in scored[:n])


def _hints():
    names = sorted({p.stem for p in DOCS_DIR.glob("**/*.*")})
    return ", ".join(names)[:300] if names else "none"


def _carry_name(question, history):
    """If the question names no file but the last questions did, add that file's name."""
    try:
        if re.search(r"\b(all|every|each|both|documents|files|resumes)\b", question, re.IGNORECASE):
            return question
        names = [p.name for p in brain._all_files()]
        if brain._matching_files(question, names):
            return question
        for q, _answer in reversed(history[-3:]):
            hit = brain._matching_files(q, names)
            if hit:
                return question + " (file: " + Path(hit[0]).stem + ")"
    except Exception:
        pass
    return question


def _mark(intent):
    _state["docs"] = intent == "documents"
    _state["at"] = time.time()


ASR_NOTE = ("The message comes from speech recognition, so words and especially names may be misheard "
            "(for example Bahramulillah or Balambar may be Balamurali, and how many countries may be how many certificates). "
            "Fix the mishearings using the stored file names and the kinds of questions people ask about resumes: "
            "skills, projects, internships, certificates, education.")


def snap_names(text):
    """Replace badly misheard names with the closest name from the stored file names."""
    try:
        known = set()
        for p in brain._all_files():
            for token in re.findall(r"[A-Za-z]{5,}", p.stem):
                if token.lower() not in ("resume", "updated", "final", "latest", "surprise", "document"):
                    known.add(token)
    except Exception:
        return text
    if not known:
        return text
    lowered = {k.lower() for k in known}

    def fix(match):
        word = match.group(0)
        if len(word) < 5 or word.lower() in lowered:
            return word
        best, score = None, 0.0
        for k in known:
            if k[0].lower() != word[0].lower():
                continue
            ratio = SequenceMatcher(None, word.lower(), k.lower()).ratio()
            if ratio > score:
                best, score = k, ratio
        return best if best and score >= 0.55 else word

    return re.sub(r"[A-Za-z]+", fix, text)


def _llm_route(text, history, force=None, asr=False):
    recent = "\n".join("User: " + q + "\nREEZ: " + a for q, a in history[-MAX_HISTORY:]) or "none"
    prompt = "\n".join([
        "You help a personal assistant called REEZ understand a message. The user may make spelling mistakes or mix Tamil and English.",
        "Files the user has stored: " + _hints(),
        ASR_NOTE if asr else "",
        "Tanglish word meanings:",
        _pick_words(text),
        "",
        "Recent conversation:",
        recent,
        "",
        "User message: " + text,
        "",
        "Do two things.",
        "1. Rewrite the message as ONE complete, self-contained English question. If the message is short or refers to",
        "   something earlier (second, name them, all, it, his, that one, more), use the recent conversation to say exactly",
        "   what is being asked, and include the person or file name. Do not answer it.",
        '2. Intent: "documents" if it asks about the stored files (a person\'s resume, skills, projects, education,',
        '   certificates, internships, a file); "general" if it is a factual or how-to question unrelated to the stored files;',
        '   "chat" for greetings, feelings, thanks and small talk.',
        "",
        "Examples:",
        'Recent: User: what certificates are in Balamurali\'s resume / REEZ: He has two certificates. Message: name them',
        '-> {"question": "Name the certificates in Balamurali\'s resume.", "intent": "documents"}',
        'Recent: none. Message: what is machine learning',
        '-> {"question": "What is machine learning?", "intent": "general"}',
        "Recent: an answer about the first internship in Balamurali's resume. Message: second",
        '-> {"question": "What is the second internship in Balamurali\'s resume?", "intent": "documents"}',
        "",
        'Reply with JSON only: {"question": "...", "intent": "documents or general or chat"}',
    ])
    try:
        data = json.loads(json_llm.invoke(prompt).content)
        question = str(data.get("question", "")).strip() or text
        intent = data.get("intent") if data.get("intent") in ("documents", "general", "chat") else "chat"
    except Exception:
        question, intent = text, "chat"
    if force:
        intent = force
    if intent == "documents":
        question = _carry_name(question, history)
    return {"intent": intent, "question": question}


def process(text, history, skip=False, tanglish_ok=True):
    """Return {"intent": ..., "question": ...}. Short follow-ups use the last answer as context."""
    text = text.strip()
    if skip or not text:
        return {"intent": "documents", "question": text}
    if EXIT_PATTERN.search(text):
        _mark("exit")
        return {"intent": "exit", "question": text}
    if text.lower().strip(" .!?") in GREETINGS or SMALL_TALK.search(text):
        return {"intent": "chat", "question": text}
    if not tanglish_ok:
        text = snap_names(text)
        recent_voice = _state["docs"] and time.time() - _state["at"] < 300
        forced = "documents" if (history and recent_voice and len(text.split()) <= 6) else None
        if not forced and len(text.split()) <= 3 and not DOC_WORDS.search(text):
            return {"intent": "chat", "question": text}
        result = _llm_route(text, history, force=forced, asr=True)
        _mark(result["intent"])
        return result
    docs = bool(DOC_WORDS.search(text))
    tanglish = tanglish_ok and bool(TANGLISH.search(text))
    follow = bool(history) and bool(FOLLOW_UP.search(text))
    words = len(text.split())
    recent_docs = _state["docs"] and time.time() - _state["at"] < 300
    if docs and not tanglish and not follow:
        _mark("documents")
        return {"intent": "documents", "question": text}
    if history and recent_docs and words <= 6 and not (tanglish and not docs):
        result = _llm_route(text, history, force="documents")
        _mark("documents")
        return result
    if not docs and (tanglish or words <= 3):
        return {"intent": "chat", "question": text}
    result = _llm_route(text, history)
    _mark(result["intent"])
    return result


def small_talk(text, history=None):
    SHORT_OK = {"hi", "ok", "no", "yes", "yo", "da", "di", "oi"}
    if len(re.findall(r"[A-Za-z0-9]", text)) <= 2 and text.lower().strip(" .!?") not in SHORT_OK:
        return "I did not catch that. Could you say it again?"
    recent = "\n".join("User: " + q + "\nREEZ: " + a for q, a in (history or [])[-2:]) or "none"
    prompt = "\n".join([
        "You are REEZ, a warm, friendly personal AI assistant.",
        "The user writes Tanglish: Tamil in English letters. Word meanings:",
        _pick_words(text),
        "",
        "Rules:",
        "- Reply to the LATEST message only. Earlier conversation is background and never changes what the latest message means.",
        "- Reply in English only, in one or two short sentences. Never repeat any Tanglish word from the user's message in your reply.",
        "- Never say that you will check, look up or find something. If you cannot tell what the user means, ask what they mean in one short sentence.",
        "- If the user is unwell, sleepy or upset, respond with care. Never make things up.",
        "",
        "Examples of good replies (match this style):",
        _pick_examples(text),
        "",
        "Earlier conversation (background only):",
        recent,
        "",
        "Latest message: " + text,
        "REEZ:",
    ])
    reply = chat_llm.invoke(prompt).content.strip()
    reply = re.sub(r"^(oi|dei|da|di|bhai)\b[\s,!.:-]*", "", reply, flags=re.IGNORECASE)
    return reply or "Sorry, can you say that again?"


def remember(history, question, reply):
    history.append((question, reply[:300]))
    del history[:-MAX_HISTORY]


