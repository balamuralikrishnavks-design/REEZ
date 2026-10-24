"""REEZ locker: encrypted private storage for notes, photos and files."""

import base64
import hashlib
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

BASE_DIR = Path(__file__).parent
LOCKER_DIR = BASE_DIR / "data" / "locker"
HEADER_FILE = LOCKER_DIR / "vault.json"
INDEX_FILE = LOCKER_DIR / "index.enc"
ITEMS_DIR = LOCKER_DIR / "items"

SCRYPT_N = 2 ** 16
MAX_ITEM_MB = 200
IDLE_SECONDS = 300
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}


def normalize(text):
    """Lowercase, letters and digits only, single spaces."""
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _b64(data):
    return base64.b64encode(data).decode("ascii")


def _unb64(text):
    return base64.b64decode(text)


def _derive(word, salt, n=SCRYPT_N):
    return Scrypt(salt=salt, length=32, n=n, r=8, p=1).derive(word.encode("utf-8"))


def _seal(key, data):
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, data, None)


def _open(key, blob):
    return AESGCM(key).decrypt(blob[:12], blob[12:], None)


def _write_atomic(path, data):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _hash_name(salt, phrase):
    return hashlib.sha256(salt + phrase.encode("utf-8")).hexdigest()


class Locker:
    def __init__(self):
        self._key = None
        self.is_master = False
        self._index = []
        self._fails = 0
        self._locked_until = 0.0
        self._last_activity = time.time()

    # ---------- state ----------
    @staticmethod
    def exists():
        return HEADER_FILE.exists()

    @property
    def is_open(self):
        return self._key is not None

    def touch(self):
        self._last_activity = time.time()

    def check_idle(self, seconds=IDLE_SECONDS):
        """Lock automatically after a quiet period. Returns True if it locked."""
        if self.is_open and time.time() - self._last_activity > seconds:
            self.lock()
            return True
        return False

    def lock(self):
        self._key = None
        self.is_master = False
        self._index = []

    def _need_open(self):
        if not self.is_open:
            raise PermissionError("The locker is locked.")
        self.touch()

    def _need_master(self):
        self._need_open()
        if not self.is_master:
            raise PermissionError("Master word needed.")

    # ---------- header ----------
    def _load_header(self):
        return json.loads(HEADER_FILE.read_text(encoding="utf-8"))

    def _save_header(self, header):
        _write_atomic(HEADER_FILE, json.dumps(header, indent=2).encode("utf-8"))

    def _opens(self, header, role, text):
        """True if this text would open the given wrap."""
        try:
            key = _derive(text, _unb64(header[role + "_salt"]), header["scrypt_n"])
            _open(key, _unb64(header[role + "_wrap"]))
            return True
        except InvalidTag:
            return False

    # ---------- first-time setup ----------
    def setup(self, code_word, master_word, folder_name):
        if self.exists():
            raise FileExistsError("A locker already exists.")
        code = normalize(code_word)
        master = master_word.strip()
        folder = normalize(folder_name)
        if len(code) < 6:
            raise ValueError("The code word needs at least 6 letters or digits.")
        if len(master) < 12:
            raise ValueError("The master word needs at least 12 characters.")
        if code == normalize(master):
            raise ValueError("The code word and master word must be different.")
        if not 1 <= len(folder.split()) <= 4:
            raise ValueError("The folder name must be 1 to 4 words.")
        LOCKER_DIR.mkdir(parents=True, exist_ok=True)
        ITEMS_DIR.mkdir(parents=True, exist_ok=True)
        data_key = os.urandom(32)
        code_salt, master_salt, name_salt = os.urandom(16), os.urandom(16), os.urandom(16)
        header = {
            "version": 1,
            "scrypt_n": SCRYPT_N,
            "code_salt": _b64(code_salt),
            "code_wrap": _b64(_seal(_derive(code, code_salt), data_key)),
            "master_salt": _b64(master_salt),
            "master_wrap": _b64(_seal(_derive(master, master_salt), data_key)),
            "name_salt": _b64(name_salt),
            "name_hash": _hash_name(name_salt, folder),
        }
        self._save_header(header)
        _write_atomic(INDEX_FILE, _seal(data_key, b"[]"))

    # ---------- opening ----------
    def is_trigger(self, text):
        """True if the text contains the secret folder name."""
        if not self.exists():
            return False
        header = self._load_header()
        salt = _unb64(header["name_salt"])
        words = normalize(text).split()
        for size in range(1, 5):
            for i in range(len(words) - size + 1):
                if _hash_name(salt, " ".join(words[i:i + size])) == header["name_hash"]:
                    return True
        return False

    def unlock(self, word):
        """Returns ("open", "code" or "master"), ("wait", seconds) or ("wrong", 0)."""
        now = time.time()
        if now < self._locked_until:
            return "wait", int(self._locked_until - now) + 1
        header = self._load_header()
        for role, text in (("code", normalize(word)), ("master", word.strip())):
            try:
                key = _derive(text, _unb64(header[role + "_salt"]), header["scrypt_n"])
                data_key = _open(key, _unb64(header[role + "_wrap"]))
            except InvalidTag:
                continue
            self._key = data_key
            self.is_master = role == "master"
            self._fails = 0
            self._index = json.loads(_open(self._key, INDEX_FILE.read_bytes()))
            self.touch()
            return "open", role
        self._fails += 1
        self._locked_until = time.time() + min(2 ** self._fails, 300)
        return "wrong", 0

    # ---------- items ----------
    def _save_index(self):
        _write_atomic(INDEX_FILE, _seal(self._key, json.dumps(self._index).encode("utf-8")))

    def _find(self, name):
        target = normalize(name)
        for item in self._index:
            if normalize(item["name"]) == target:
                return item
        return None

    def _add(self, name, kind, data, filename):
        self._need_open()
        name = name.strip()
        if not name:
            raise ValueError("Give it a name.")
        if self._find(name):
            raise ValueError("An item with that name already exists.")
        item_id = uuid.uuid4().hex
        ITEMS_DIR.mkdir(parents=True, exist_ok=True)
        _write_atomic(ITEMS_DIR / (item_id + ".enc"), _seal(self._key, data))
        self._index.append({
            "id": item_id, "name": name, "kind": kind, "filename": filename,
            "size": len(data), "created": time.strftime("%Y-%m-%d %H:%M"),
        })
        self._save_index()

    def add_note(self, name, text):
        self._add(name, "note", text.encode("utf-8"), "")

    def add_file(self, path, name=None):
        p = Path(path.strip().strip('"'))
        if not p.is_file():
            raise FileNotFoundError("I can't find that file.")
        if p.stat().st_size > MAX_ITEM_MB * 1024 * 1024:
            raise ValueError("That file is bigger than " + str(MAX_ITEM_MB) + " MB.")
        ext = p.suffix.lower()
        kind = "image" if ext in IMAGE_EXT else "pdf" if ext == ".pdf" else "file"
        self._add(name or p.stem, kind, p.read_bytes(), p.name)

    def list_items(self):
        self._need_open()
        return [dict(item) for item in self._index]

    def get_bytes(self, name):
        self._need_open()
        item = self._find(name)
        if not item:
            raise KeyError(name)
        blob = (ITEMS_DIR / (item["id"] + ".enc")).read_bytes()
        return dict(item), _open(self._key, blob)

    def export(self, name, folder):
        item, data = self.get_bytes(name)
        folder = Path(folder.strip().strip('"'))
        folder.mkdir(parents=True, exist_ok=True)
        base = re.sub(r'[<>:"/\\|?*]', "_", item["filename"] or (item["name"] + ".txt"))
        target = folder / base
        counter = 1
        while target.exists():
            target = folder / (Path(base).stem + "_" + str(counter) + Path(base).suffix)
            counter += 1
        target.write_bytes(data)
        return target

    def delete(self, name):
        self._need_open()
        item = self._find(name)
        if not item:
            raise KeyError(name)
        path = ITEMS_DIR / (item["id"] + ".enc")
        if path.exists():
            path.unlink()
        self._index = [i for i in self._index if i["id"] != item["id"]]
        self._save_index()

    # ---------- asking the notes ----------
    def ask(self, question):
        self._need_open()
        import io
        from pypdf import PdfReader
        from langchain_ollama import ChatOllama
        parts, unread = [], []
        for item in self._index:
            blob = (ITEMS_DIR / (item["id"] + ".enc")).read_bytes()
            data = _open(self._key, blob)
            text = ""
            if item["kind"] == "note":
                text = data.decode("utf-8", errors="ignore")
            elif item["kind"] == "pdf":
                try:
                    reader = PdfReader(io.BytesIO(data))
                    text = "\n".join((p.extract_text() or "") for p in reader.pages)
                except Exception:
                    text = ""
            elif item["filename"].lower().endswith((".txt", ".md", ".csv")):
                text = data.decode("utf-8", errors="ignore")
            if text.strip():
                parts.append("[" + item["kind"] + ": " + item["name"] + "]\n" + text.strip()[:2500])
            else:
                unread.append(item["name"] + " (" + item["kind"] + ")")
        context = "\n\n".join(parts)[:4500] or "(nothing readable)"
        prompt = (
            "You are REEZ. Answer using ONLY the private documents below. "
            "Keep it short and sweet: one sentence, under 20 words. "
            "If the answer is not written there, say you don't know. Never guess.\n\n"
            "Documents:\n" + context
            + "\n\nItems REEZ cannot read: " + (", ".join(unread) or "none")
            + "\n\nQuestion: " + question + "\nAnswer:"
        )
        llm = ChatOllama(num_ctx=4096, keep_alive="30m", model="gemma3:4b", temperature=0)
        return llm.invoke(prompt).content.strip()
    # ---------- master mode ----------
    def change_code(self, new_code):
        self._need_master()
        code = normalize(new_code)
        if len(code) < 6:
            raise ValueError("The code word needs at least 6 letters or digits.")
        header = self._load_header()
        if self._opens(header, "master", code):
            raise ValueError("The code word must be different from the master word.")
        salt = os.urandom(16)
        header["code_salt"] = _b64(salt)
        header["code_wrap"] = _b64(_seal(_derive(code, salt, header["scrypt_n"]), self._key))
        self._save_header(header)

    def change_master(self, new_master):
        self._need_master()
        master = new_master.strip()
        if len(master) < 12:
            raise ValueError("The master word needs at least 12 characters.")
        header = self._load_header()
        if self._opens(header, "code", normalize(master)):
            raise ValueError("The master word must be different from the code word.")
        salt = os.urandom(16)
        header["master_salt"] = _b64(salt)
        header["master_wrap"] = _b64(_seal(_derive(master, salt, header["scrypt_n"]), self._key))
        self._save_header(header)

    def rename_folder(self, new_name):
        self._need_master()
        folder = normalize(new_name)
        if not 1 <= len(folder.split()) <= 4:
            raise ValueError("The folder name must be 1 to 4 words.")
        header = self._load_header()
        salt = os.urandom(16)
        header["name_salt"] = _b64(salt)
        header["name_hash"] = _hash_name(salt, folder)
        self._save_header(header)

    def reset(self):
        self._need_master()
        self.lock()
        shutil.rmtree(LOCKER_DIR, ignore_errors=True)







