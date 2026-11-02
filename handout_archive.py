# -*- coding: utf-8 -*-
"""Permanent archive of generated handouts, organized by course and learning standard.

Two storage options, same interface:
  GitHubArchive -- a PRIVATE GitHub repository (durable on Streamlit Cloud).
                   Enabled by Streamlit secrets HANDOUT_ARCHIVE_REPO ("owner/name")
                   and HANDOUT_ARCHIVE_TOKEN (fine-grained token, Contents: read and write).
  LocalArchive  -- a folder next to the app (durable when running on your own computer;
                   Streamlit Cloud erases it when the app restarts).

Layout (same in both):
  MAT3A/S-03 Derivative at a Point and as a Function/
      2026-11-02 1532 Quest 2 (English).pdf
      2026-11-02 1532 Quest 2 (English).tex
      2026-11-02 1532 Quest 2 (English).json   <- problems, answers, review notes
  index.json                                  <- one line per handout, for fast listing
"""
import base64
import datetime
import json
import pathlib
import re
import urllib.parse

APP_DIR = pathlib.Path(__file__).resolve().parent
LOCAL_ROOT = APP_DIR / "handout_archive"
VERSION_ORDER = ["preparation", "quest1", "quest2", "quest3", "ticket"]
VERSION_LABEL = {"preparation": "Preparation", "quest1": "Quest 1", "quest2": "Quest 2",
                 "quest3": "Quest 3", "ticket": "Reassessment Ticket"}
LANG_LABEL = {"en": "English", "es": "Español"}


def _now():
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo("America/Los_Angeles"))
    except Exception:  # noqa: BLE001
        return datetime.datetime.now()


def _safe(text):
    text = str(text).replace("&", "and").replace("/", "-")
    text = re.sub(r"[^A-Za-z0-9 ,.()'\-áéíóúñÁÉÍÓÚÑ]", "", text)
    return re.sub(r"\s+", " ", text).strip()[:80]


def std_sort_key(code):
    m = re.search(r"(\d+)", code or "")
    return int(m.group(1)) if m else 0


def make_entry(result, course_code):
    """Index entry + archive paths for one generated handout (result from handout_core)."""
    now = _now()
    std, version = result["std"], result["version"]
    code = std["code"]
    folder = f"{course_code.replace(' ', '')}/S-{std_sort_key(code):02d} {_safe(std['title'])}"
    base = f"{now:%Y-%m-%d %H%M} {VERSION_LABEL[version]} ({LANG_LABEL.get(result['lang'], result['lang'])})"
    rv = result.get("review", {})
    return {
        "id": f"{now:%Y%m%d%H%M%S%f}",
        "created": now.isoformat(timespec="seconds"),
        "course": result["course"], "course_code": course_code,
        "std_code": code, "std_title": std["title"],
        "version": version, "version_label": VERSION_LABEL[version], "lang": result["lang"],
        "n_problems": len(result.get("problems", [])),
        "review": {k: rv.get(k, 0) for k in ("checked", "fixed", "unresolved")},
        "folder": folder,
        "files": {"pdf": f"{folder}/{base}.pdf", "tex": f"{folder}/{base}.tex", "json": f"{folder}/{base}.json"},
    }


def _payloads(entry, files, result):
    pdf = next((v for k, v in files.items() if k.endswith(".pdf")), None)
    tex = next((v for k, v in files.items() if k.endswith(".tex")), None)
    out = {}
    if pdf is not None:
        out[entry["files"]["pdf"]] = pdf
    if tex is not None:
        out[entry["files"]["tex"]] = tex.encode("utf-8") if isinstance(tex, str) else tex
    if result is not None:
        out[entry["files"]["json"]] = json.dumps(result, ensure_ascii=False, indent=1, default=str).encode("utf-8")
    return out


class LocalArchive:
    kind = "local"

    def __init__(self, root=LOCAL_ROOT):
        self.root = pathlib.Path(root)

    def _index_path(self):
        return self.root / "index.json"

    def list(self):
        try:
            return json.loads(self._index_path().read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _write_index(self, entries):
        self.root.mkdir(parents=True, exist_ok=True)
        self._index_path().write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")

    def save(self, entry, files, result=None):
        for path, data in _payloads(entry, files, result).items():
            f = self.root / path
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
        entries = [e for e in self.list() if e["id"] != entry["id"]] + [entry]
        self._write_index(entries)

    def read(self, path):
        return (self.root / path).read_bytes()

    def delete(self, entry):
        for path in entry["files"].values():
            try:
                (self.root / path).unlink()
            except FileNotFoundError:
                pass
        self._write_index([e for e in self.list() if e["id"] != entry["id"]])


class GitHubArchive:
    kind = "github"
    API = "https://api.github.com"

    def __init__(self, repo, token, http=None):
        import requests
        self.repo = repo.strip().strip("/")
        self.http = http or requests.Session()
        self.headers = {"Authorization": f"Bearer {token.strip()}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28"}

    def _url(self, path):
        return f"{self.API}/repos/{self.repo}/contents/{urllib.parse.quote(path)}"

    def _get(self, path, raw=False):
        h = dict(self.headers, Accept="application/vnd.github.raw") if raw else self.headers
        r = self.http.get(self._url(path), headers=h, timeout=30)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.content if raw else r.json()

    def _put(self, path, data, message, sha=None):
        body = {"message": message, "content": base64.b64encode(data).decode("ascii")}
        if sha:
            body["sha"] = sha
        r = self.http.put(self._url(path), headers=self.headers, json=body, timeout=60)
        r.raise_for_status()

    def check(self):
        """Raises if the repository can't be reached with this token."""
        r = self.http.get(f"{self.API}/repos/{self.repo}", headers=self.headers, timeout=20)
        r.raise_for_status()
        return r.json().get("private", False)

    def _index(self):
        meta = self._get("index.json")
        if not meta:
            return [], None
        return json.loads(base64.b64decode(meta["content"]).decode("utf-8")), meta["sha"]

    def list(self):
        return self._index()[0]

    def _update_index(self, change, message):
        for _ in range(3):  # retry if the index changed underneath us
            entries, sha = self._index()
            try:
                self._put("index.json", json.dumps(change(entries), ensure_ascii=False, indent=1).encode("utf-8"),
                          message, sha)
                return
            except Exception as exc:  # noqa: BLE001
                if getattr(getattr(exc, "response", None), "status_code", None) not in (409, 422):
                    raise
        raise RuntimeError("The archive index kept changing; try again.")

    def save(self, entry, files, result=None):
        label = f"{entry['std_code']} {entry['version_label']}"
        for path, data in _payloads(entry, files, result).items():
            meta = self._get(path)
            self._put(path, data, f"Archive {label}", meta["sha"] if meta else None)
        self._update_index(lambda es: [e for e in es if e["id"] != entry["id"]] + [entry], f"Index {label}")

    def read(self, path):
        data = self._get(path, raw=True)
        if data is None:
            raise FileNotFoundError(path)
        return data

    def delete(self, entry):
        for path in entry["files"].values():
            meta = self._get(path)
            if meta:
                r = self.http.delete(self._url(path), headers=self.headers, timeout=30,
                                     json={"message": f"Delete {path}", "sha": meta["sha"]})
                r.raise_for_status()
        self._update_index(lambda es: [e for e in es if e["id"] != entry["id"]],
                           f"Remove {entry['std_code']} {entry['version_label']}")


def get_archive(secrets):
    """GitHub archive when both secrets are set; otherwise the local folder."""
    try:
        repo, token = secrets.get("HANDOUT_ARCHIVE_REPO"), secrets.get("HANDOUT_ARCHIVE_TOKEN")
    except Exception:  # noqa: BLE001 -- no secrets file at all
        repo = token = None
    if repo and token:
        return GitHubArchive(str(repo), str(token))
    return LocalArchive()
