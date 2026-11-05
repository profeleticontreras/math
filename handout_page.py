# -*- coding: utf-8 -*-
"""Handout Generator screen for Canelita's instructor view.

app.py calls render_handout_generator(client) for the signed-in instructor.
Generation, review, LaTeX, and PDF logic live in handout_core.py.
Session keys start with "hg_" so they never collide with the tutor's state.
"""
import datetime
import hashlib
import io
import re
import zipfile

import anthropic
import streamlit as st

import handout_archive as ha
import handout_core as hc

TYPE_LABEL = {"skill": "Skill", "conceptual": "Conceptual", "interpretation": "Interpretation"}
VLABEL = hc.LABELS["en"]
QUICK_TAG = {"mc": "multiple choice", "blank": "word bank", "match": "matching"}


def _quick_md(p):
    """Rough preview of a quick-answer problem's choices, word bank, or matching lists."""
    q = p.get("quick")
    if q == "mc":
        return "\n".join(f"**({chr(65 + i)})** " + _preview_md(c) + "  " for i, c in enumerate(p.get("choices", [])))
    if q == "blank":
        return "**Word bank:** " + " · ".join(_preview_md(w) for w in p.get("bank", []))
    if q == "match":
        left = "\n".join(f"{i + 1}. " + _preview_md(x) + "  " for i, x in enumerate(p.get("left", [])))
        right = "\n".join(f"**({chr(65 + i)})** " + _preview_md(x) + "  " for i, x in enumerate(p.get("right", [])))
        return left + "\n\n" + right
    return ""


@st.cache_data
def _catalog(course):
    return hc.load_standards(course)


def _preview_md(text):
    """Rough Markdown preview of LaTeX (the PDF is the real output)."""
    if not text:
        return ""
    text = re.sub(r"(\\begin\{center\}\s*)?\\begin\{tikzpicture\}.*?\\end\{tikzpicture\}(\s*\\end\{center\})?",
                  "\n\n*(graph — see PDF)*\n\n", text, flags=re.S)
    text = re.sub(r"(\\begin\{center\}\s*)?\\begin\{tabular\}.*?\\end\{tabular\}(\s*\\end\{center\})?",
                  "\n\n*(table — see PDF)*\n\n", text, flags=re.S)
    text = re.sub(r"\\\[(.*?)\\\]", lambda m: "\n\n$$" + m.group(1).strip() + "$$\n\n", text, flags=re.S)
    text = re.sub(r"\\textbf\{([^{}]*)\}", r"**\1**", text)
    text = re.sub(r"\\textit\{([^{}]*)\}|\\emph\{([^{}]*)\}", lambda m: "*" + (m.group(1) or m.group(2)) + "*", text)
    return text.replace(r"\%", "%").replace(r"\$", "＄").replace("``", '"').replace("''", '"')


# Archive groups: Preparation and Reassessment Ticket are student handouts and are listed together;
# each Quest is an instructor handout listed on its own row.
ARCH_GROUPS = [
    ("student", ("preparation", "ticket"), "Preparation + Reassessment Ticket"),
    ("quest1", ("quest1",), "Quest 1"),
    ("quest2", ("quest2",), "Quest 2"),
    ("quest3", ("quest3",), "Quest 3"),
]
ARCH_CSS = """<style>
.ar-head{display:flex;align-items:center;gap:0.9rem;margin:0.1rem 0 0.2rem;}
.ar-std{background:#f1efe9;border:1px solid #dedad0;border-radius:999px;padding:4px 14px;
  font-weight:700;font-size:1.02rem;color:#333;white-space:nowrap;}
.ar-title{font-size:1.2rem;font-weight:700;line-height:1.2;}
.ar-sub{font-size:0.9rem;opacity:0.7;margin-top:0.1rem;}
.ar-pill{display:inline-block;border-radius:999px;padding:3px 12px;font-size:0.86rem;font-weight:600;
  margin:0 6px 4px 0;border:1px solid transparent;}
.ar-lang{background:#fff;border-color:#dcdcdc;color:#333;}
.ar-type{background:#ebe9e4;color:#333;}
.ar-stu{background:#e6f6ea;border-color:#b7e1c1;color:#1b5e20;}
.ar-off{background:#f1f1f1;border-color:#d6d6d6;color:#555;}
.ar-ins{background:#fff4d6;border-color:#f0d184;color:#8a4b00;}
.ar-rule{border-top:1px solid rgba(0,0,0,0.10);margin:0.15rem 0 0.35rem;}
.ar-latest{font-size:0.88rem;opacity:0.72;}
.ar-set{font-size:0.95rem;padding-left:0.4rem;}
.ar-set .ar-when{opacity:0.65;}
</style>"""


def _fmt_when(iso):
    try:
        d = datetime.datetime.fromisoformat(iso)
        return f"{d:%b} {d.day}, {d.year}, {d.strftime('%I:%M %p').lstrip('0')}"
    except (TypeError, ValueError):
        return str(iso)[:16].replace("T", " ")


def _get_archive():
    if "hg_archive" not in st.session_state:
        st.session_state.hg_archive = ha.get_archive(st.secrets)
    return st.session_state.hg_archive


def _archive_save(e):
    """Save (or re-save) one handout in the permanent archive."""
    r, out = e["result"], e["out"]
    meta = e.get("archive_entry") or ha.make_entry(r, hc.COURSES[r["course"]]["code"])
    meta.update(n_problems=len(r["problems"]),
                review={k: r.get("review", {}).get(k, 0) for k in ("checked", "fixed", "unresolved")})
    try:
        _get_archive().save(meta, out["files"], r)
        e["archive_entry"], e["archive_error"] = meta, ""
    except Exception as exc:  # noqa: BLE001 -- shown, never blocks the handout
        e["archive_error"] = str(exc)
    st.session_state.pop("hg_arch_index", None)
    _visible_index.clear()


def _library():
    return st.session_state.setdefault("hg_library", [])


def _add_to_library(result, instructions):
    result["instructions"] = instructions
    entry = {"id": f"h{len(_library()) + 1}_{datetime.datetime.now().strftime('%H%M%S')}",
             "made": datetime.datetime.now().strftime("%I:%M %p").lstrip("0"),
             "result": result}
    entry["out"] = hc.build_files(result)
    _archive_save(entry)
    _library().insert(0, entry)


def _entry_title(e):
    r = e["result"]
    lang = "English" if r["lang"] == "en" else "Español"
    return (f"{r['std']['code']} · {VLABEL[r['version']]} — {hc.COURSES[r['course']]['code']}, "
            f"{lang} · made {e['made']}")


def render_handout_generator(client):
    st.markdown('<p class="app-title">Handout Generator</p>', unsafe_allow_html=True)
    if not hc.find_pdflatex():
        st.warning("LaTeX isn't installed where the app is running, so you'll get .tex files only "
                   "(open them in TeXstudio to make the PDF).")

    archive = _get_archive()
    tab_make, tab_arch = st.tabs(["Make handouts", "Archive — by learning standard"])
    with tab_arch:
        _render_archive(archive)
    with tab_make:
        _render_make(client)


def _render_make(client):
    # ── Controls (above the list of handouts) ─────────────────────────────
    courses = [c for c in hc.COURSES if hc.course_available(c)]
    c1, c2 = st.columns([2, 1])
    course = c1.radio("Course", courses, horizontal=True, key="hg_course",
                      format_func=lambda c: f"{hc.COURSES[c]['name']} ({hc.COURSES[c]['code']})")
    lang = c2.radio("Handout language", ["en", "es"], horizontal=True, key="hg_lang",
                    format_func={"en": "English", "es": "Español"}.get)

    catalog = _catalog(course)
    by_code = {s["code"]: s for s in catalog}
    code = st.selectbox("Learning standard", list(by_code), key=f"hg_std_{course}",
                        format_func=lambda c: f"{c} — {by_code[c]['title']}  (Sec. {by_code[c]['sections']})")
    std = by_code[code]
    with st.expander(f"Subskills for {code}", expanded=False):
        for i, s in enumerate(std["subskills"], 1):
            st.markdown(f"**{code}.{i}** {s}")

    versions = st.multiselect(
        "Handout version", hc.VERSIONS, default=["preparation"], key="hg_versions",
        format_func=VLABEL.get,
        help="Pick one. Add more versions to make a batch for this standard.")

    with st.expander("Problem counts and instructions"):
        a, b = st.columns(2)
        n_pt = a.number_input("Preparation & Reassessment Ticket — problems of each type "
                              "(skill, conceptual, interpretation)", 1, 4, 3, key="hg_n_pt")
        n_q = b.number_input("Quests — problems of each type", 1, 4, 2, key="hg_n_q")
        st.caption("Answer space: 1 in after each question, 0.5 in after each lettered part. "
                   "Preparation's space is fitted so the questions fill two pages and the answer key "
                   "starts on page 3. Print stays 12 pt.")
        instr = {}
        for v in versions:
            instr[v] = st.text_area(f"Instructions — {VLABEL[v]}", hc.default_instructions(lang, v),
                                    key=f"hg_instr_{v}_{lang}", height=110)

    counts = {v: (n_q if v in hc.QUESTS else n_pt) for v in versions}
    n_total = sum(counts[v] * 3 for v in versions)
    label = (f"Generate {VLABEL[versions[0]]}" if len(versions) == 1 else f"Generate {len(versions)} versions") \
        if versions else "Choose a handout version"
    go = st.button(f"{label}  ({n_total} problems)" if versions else label, type="primary",
                   disabled=not versions, key="hg_go")

    if st.session_state.pop("hg_cancel_requested", False):
        st.info("Handout request cancelled. Nothing was saved. Any Claude call already in progress "
                "finishes in the background and is discarded; no new calls are made.")

    if go:
        with st.status(f"Making {len(versions)} handout(s) for {code}… usually 2–4 minutes.",
                       expanded=True) as status:
            st.button("✖  Cancel this request", key="hg_cancel",
                      on_click=lambda: st.session_state.update(hg_cancel_requested=True))
            lines = {v: st.empty() for v in versions}
            stages = {v: "Waiting" for v in versions}
            t0 = datetime.datetime.now()

            def draw(v):
                secs = int((datetime.datetime.now() - t0).total_seconds())
                stage = stages[v]
                icon = "✅" if stage == "Done" else ("❌" if stage.startswith(("Failed", "Cancelled")) else "⏳")
                lines[v].markdown(f"{icon} **{VLABEL[v]}** — {stage}  ·  {secs // 60}:{secs % 60:02d}")

            def on_event(v, stage):
                stages[v] = stage
                draw(v)

            def on_tick():  # keeps the clock moving; lets Cancel stop the run right away
                for v in versions:
                    if stages[v] != "Done":
                        draw(v)

            for v in versions:
                draw(v)
            try:
                results = hc.generate_batch(client, course, std, catalog, versions, counts, lang,
                                            on_event, on_tick=on_tick)
            except anthropic.APIError as e:
                status.update(label="Claude couldn't generate the handouts.", state="error")
                st.error(str(e))
                return
            ok = 0
            for v in versions:
                r = results.get(v)
                if isinstance(r, hc.Cancelled):
                    continue
                if isinstance(r, Exception):
                    st.error(f"{VLABEL[v]} failed: {r}. Nothing was saved for this version.")
                    continue
                on_event(v, "Typesetting the PDF")
                on_tick()
                _add_to_library(r, instr.get(v))
                on_event(v, "Done")
                ok += 1
            status.update(label=f"Finished: {ok} of {len(versions)} handout(s) ready below.",
                          state="complete" if ok == len(versions) else "error", expanded=False)

    # ── Handouts made this session ────────────────────────────────────────
    lib = _library()
    st.divider()
    st.subheader("Handouts made this session")
    if not lib:
        st.caption("Nothing yet. Generated handouts appear here, newest first. Download the PDF or "
                   ".tex to keep them; this list clears when you sign out or the app restarts.")
        return
    if len(lib) > 1:
        zbuf = io.BytesIO()
        with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
            for e in lib:
                for name, data in e["out"]["files"].items():
                    z.writestr(name, data)
        st.download_button(f"⬇️ Download all {len(lib)} handouts (.zip)", zbuf.getvalue(),
                           file_name=f"handouts_{datetime.date.today().isoformat()}.zip",
                           mime="application/zip", key="hg_zip_all")

    for idx, e in enumerate(lib):
        _render_entry(client, e, catalog_for=_catalog, first=(idx == 0))


def _render_entry(client, e, catalog_for, first):
    r, out = e["result"], e["out"]
    rv = r.get("review", {})
    unresolved = rv.get("unresolved", 0) + sum(1 for p in r["problems"] if any("LaTeX error" in w for w in p.get("warnings", [])))
    flag = "  ⚠️" if unresolved or out["error"] else ""
    with st.expander(_entry_title(e) + flag, expanded=first):
        st.caption(f"Math review: {rv.get('checked', 0)} problems checked, {rv.get('fixed', 0)} fixed after "
                   f"review, {rv.get('unresolved', 0)} still flagged."
                   + (f"  Preparation answer space fitted at {out['scale']:.0%} to keep the questions on two pages."
                      if r["version"] == "preparation" else ""))
        t = r.get("timings", {})
        if t:
            fmt = lambda x: f"{int(x) // 60}:{int(x) % 60:02d}"
            st.caption("Time: " + " · ".join(f"{k} {fmt(v)}" for k, v in t.items())
                       + f" · total {fmt(sum(t.values()))}")
        if e.get("archive_error"):
            st.warning(f"Not saved to the archive: {e['archive_error'][:200]}")
        elif e.get("archive_entry"):
            st.caption(f"📚 Saved to the archive: {e['archive_entry']['folder']}")
        for n in r.get("notes", []):
            st.warning(n)
        if out["error"]:
            st.error("The PDF didn't compile. The .tex file is still available. LaTeX said:")
            st.code(out["error"], language="text")

        cols = st.columns(3)
        for col, (name, data) in zip(cols, out["files"].items()):
            pdf = name.endswith(".pdf")
            col.download_button(f"⬇️ {'PDF' if pdf else 'LaTeX (.tex)'}", data, file_name=name,
                                mime="application/pdf" if pdf else "application/x-tex",
                                width="stretch", key=f"hg_dl_{e['id']}_{name}")
        if cols[2].button("🗑 Remove from list", key=f"hg_rm_{e['id']}", width="stretch"):
            _library().remove(e)
            st.rerun()

        pdf_name = out["base"] + ".pdf"
        if pdf_name in out["files"] and st.toggle("Show the pages", key=f"hg_pages_{e['id']}", value=first):
            imgs = hc.pdf_page_images(out["files"][pdf_name])
            if imgs:
                pcols = st.columns(min(3, len(imgs)))
                for i, img in enumerate(imgs):
                    pcols[i % len(pcols)].image(img, caption=f"Page {i + 1}", width="stretch")
            else:
                st.caption("Page preview isn't available here; download the PDF to view it.")

        st.markdown("**Review the problems**")
        st.caption("Tables and graphs show only in the PDF. 🔄 replaces a problem, ➕ adds another on the same "
                   "skill with a different type of function, 🗑 removes one. New problems are reviewed too.")
        for p in r["problems"]:
            head = f"{p.get('num', p['id'])}. [{TYPE_LABEL[p['type']]} · {p['subskill_code']}] {p.get('title') or '(no label)'}"
            if p.get("quick"):
                head += f" · {QUICK_TAG[p['quick']]}"
            if p.get("added") == "instructor":
                head += " · your question"
            warn = "  ⚠️" if p.get("warnings") else ("  🛠" if p.get("repaired_from") else "")
            with st.expander(head + warn):
                st.caption(f"Subskill {p['subskill_code']}: {p['subskill']}"
                           + (f" · context: {p['context']}" if p.get("context") else ""))
                st.markdown(_preview_md(p["statement"].replace("[[blank]]", "\\_\\_\\_\\_\\_\\_")))
                if p.get("quick"):
                    st.markdown(_quick_md(p))
                for letter, part in zip("abcd", p.get("parts", [])):
                    st.markdown(f"**({letter})** " + _preview_md(part))
                if st.toggle("Show answer and solution", key=f"hg_sol_{e['id']}_{p['id']}"):
                    st.markdown("**Answer:** " + _preview_md(p.get("answer", "")))
                    st.markdown(_preview_md(p.get("solution", "")))
                if p.get("repaired_from"):
                    st.caption("🛠 Fixed after review: " + "; ".join(p["repaired_from"])[:400])
                for w in p.get("warnings", []):
                    st.caption(f"⚠️ {w}")
                b1, b2, b3 = st.columns(3)
                regen = b1.button("🔄 Regenerate", key=f"hg_regen_{e['id']}_{p['id']}", width="stretch",
                                  help="Replace this problem with a new one on the same skill "
                                       "(new function, numbers, and context).")
                dup = b2.button("➕ Duplicate", key=f"hg_dup_{e['id']}_{p['id']}", width="stretch",
                                help="Add one more problem on the same skill, using a different type "
                                     "of function. It goes right after this one.")
                with b3.popover("🗑 Delete", width="stretch", help="Remove this problem from the handout."):
                    st.markdown(f"Remove problem {p.get('num', p['id'])} from this handout? "
                                "The remaining problems are renumbered.")
                    delete = st.button("Delete problem", type="primary", key=f"hg_del_{e['id']}_{p['id']}")
                if regen or dup:
                    with st.spinner("Writing and reviewing a new problem…"):
                        try:
                            args = (client, r["course"], r["std"], catalog_for(r["course"]), p, r["lang"],
                                    r["version"])
                            if regen:
                                new = hc.regenerate_problem(*args, existing=r["problems"])
                            else:
                                new = hc.duplicate_problem(*args, new_id=max(q["id"] for q in r["problems"]) + 1,
                                                   existing=r["problems"])
                        except Exception as exc:  # noqa: BLE001
                            st.error(str(exc))
                        else:
                            i = r["problems"].index(p)
                            if regen:
                                r["problems"][i] = new
                            else:
                                r["problems"].insert(i + 1, new)
                            e["out"] = hc.build_files(r)
                            _archive_save(e)
                            st.rerun()
                if delete:
                    if len(r["problems"]) <= 1:
                        st.warning("A handout needs at least one problem.")
                    else:
                        r["problems"].remove(p)
                        e["out"] = hc.build_files(r)
                        _archive_save(e)
                        st.rerun()

        _render_add_question(client, e, catalog_for)

        with st.expander("✏️ Edit the LaTeX and recompile (optional)"):
            tex_name = out["base"] + ".tex"
            # The widget key includes a fingerprint of the current source, so the box always shows the
            # handout as it is now (after deleting, adding, or regenerating problems), never a stale copy.
            fp = hashlib.md5(out["files"][tex_name].encode("utf-8")).hexdigest()[:10]
            st.caption("This is the current handout, including any problems you removed or added. "
                       "Deleting, adding, or regenerating a problem afterward rebuilds the handout "
                       "from the problems, so finish those changes first and edit the LaTeX last.")
            edited = st.text_area("LaTeX source", out["files"][tex_name], height=380, key=f"hg_edit_{e['id']}_{fp}")
            if st.button("Compile my edits", key=f"hg_cmp_{e['id']}"):
                pdf, err = hc.compile_pdf(edited)
                if pdf:
                    out["files"][tex_name] = edited
                    out["files"][pdf_name] = pdf
                    out["error"] = ""
                    _archive_save(e)
                    st.success("Compiled. The downloads above and the archive now use your edited version.")
                    st.rerun()
                else:
                    st.error("LaTeX error:")
                    st.code(err, language="text")


def _render_add_question(client, e, catalog_for):
    """Add one more question to a finished handout: Claude writes it, or the instructor types it."""
    r = e["result"]
    std, eid = r["std"], e["id"]
    done = st.session_state.pop(f"hg_added_{eid}", "")
    if done:
        st.success(done)
    with st.expander("➕ Add a question to this handout"):
        how = st.radio("How would you like to add it?",
                       ["Claude writes it", "I'll type my own"], horizontal=True, key=f"hg_add_how_{eid}")
        c1, c2 = st.columns(2)
        qtype = c1.selectbox("Question type", hc.QUESTION_TYPES, format_func=lambda t: TYPE_LABEL[t],
                             key=f"hg_add_type_{eid}")
        own = how == "I'll type my own"
        sub_opts = [-1] + list(range(len(std["subskills"])))
        sub = c2.selectbox("Subskill", sub_opts, key=f"hg_add_sub_{eid}",
                           format_func=lambda i: ("Let Claude choose the best match" if own else "Any subskill")
                           if i < 0 else f"{std['code']}.{i + 1}: {std['subskills'][i]}"[:90])
        if own:
            text = st.text_area(
                "Type your question", height=170, key=f"hg_add_text_{eid}",
                placeholder="Type math the way you'd write it, for example x^2 + y^2 = 25, sqrt(x), "
                            "(3x+1)/(x-2), f'(x), e^(2x).\nPut each part on its own line: (a) ..., (b) ...")
            st.caption("Claude typesets your math in LaTeX and writes the answer and worked solution. "
                       "Your question, numbers, and wording stay the same. If the check finds a problem "
                       "with it, you'll see a note instead of a silent change.")
        else:
            text = st.text_area(
                "Anything specific? (optional)", height=90, key=f"hg_add_note_{eid}",
                placeholder="For example: a ladder sliding down a wall; use a trigonometric function; "
                            "a farmworker's water budget.")
            st.caption("Claude writes a new problem that's different from the ones already on the "
                       "handout, checks the math, and makes sure it typesets.")
        if st.button("Add to handout", type="primary", key=f"hg_add_go_{eid}"):
            if own and not text.strip():
                st.warning("Type your question first.")
                return
            with st.spinner("Typesetting and checking your question…" if own else
                            "Writing and checking a new question…"):
                try:
                    new_id = max(q["id"] for q in r["problems"]) + 1
                    args = (client, r["course"], std, catalog_for(r["course"]))
                    idx = None if sub < 0 else sub
                    if own:
                        new = hc.format_own_problem(*args, text, qtype, r["lang"], r["version"], new_id,
                                                    subskill_index=idx)
                    else:
                        new = hc.add_problem(*args, r["problems"], qtype, r["lang"], r["version"], new_id,
                                             subskill_index=idx, note=text)
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Couldn't add the question: {exc}")
                    return
            r["problems"].insert(hc.insert_position(r["problems"], qtype), new)
            e["out"] = hc.build_files(r)
            _archive_save(e)
            for k in (f"hg_add_text_{eid}", f"hg_add_note_{eid}"):
                st.session_state.pop(k, None)
            n = new.get("num", r["problems"].index(new) + 1)
            st.session_state[f"hg_added_{eid}"] = (
                f"Added as problem {n} ({TYPE_LABEL[qtype]}). The PDF and the archive are updated."
                + (" It has a review note; open it below to check." if new.get("warnings") else ""))
            st.rerun()


def _render_archive(archive):
    if archive.kind == "github":
        st.caption(f"Every handout is saved permanently in your private GitHub repository "
                   f"**{archive.repo}**, in one folder per learning standard.")
    else:
        st.warning("**The archive isn't permanent yet.** Handouts are saved inside the app for now, and "
                   "Streamlit Cloud erases them whenever the app restarts or updates, including handouts "
                   "you've made visible to students. To keep them, connect a private GitHub repository.")
        with st.expander("How to connect the private repository"):
            st.markdown(
                "1. On github.com, create a **private** repository, for example `canelita-handouts`.\n"
                "2. Make a fine-grained token: your picture → **Settings** → **Developer settings** → "
                "**Personal access tokens** → **Fine-grained tokens** → **Generate new token**. Choose "
                "*Only select repositories* → `canelita-handouts`, and set **Contents** to *Read and write*. "
                "Copy the token (it starts with `github_pat_`).\n"
                "3. On share.streamlit.io, open this app's **⋮ → Settings → Secrets**. Keep what's there and "
                "add these two lines at the bottom, with your own token. The quotation marks are required:")
            st.code('HANDOUT_ARCHIVE_REPO = "profeleticontreras/canelita-handouts"\n'
                    'HANDOUT_ARCHIVE_TOKEN = "github_pat_paste_your_token_here"', language="toml")
            st.caption("Click Save. The app restarts, and this message is replaced by the name of your "
                       "repository.")
    if "hg_arch_index" not in st.session_state:
        try:
            st.session_state.hg_arch_index = archive.list()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Couldn't open the archive: {exc}")
            return
    entries = st.session_state.hg_arch_index
    st.markdown(ARCH_CSS, unsafe_allow_html=True)
    st.caption("After you've checked a Preparation or Reassessment Ticket, turn on **Visible to students**. "
               "Students then find its PDF on the home page under *What would you like to do? → "
               "Get a handout*. Quests are never shown to students.")
    if st.session_state.get("hg_vis_error"):
        st.error(st.session_state.pop("hg_vis_error"))
    c1, c2, c3 = st.columns([2, 3, 1])
    courses = sorted({e["course_code"] for e in entries}) or ["MAT 3A"]
    course = c1.radio("Course", courses, horizontal=True, key="hg_arch_course")
    show = c2.radio("Show", ["All handouts", "Student handouts", "Instructor handouts (Quests)"],
                    horizontal=True, key="hg_arch_show")
    if c3.button("↻ Refresh", key="hg_arch_refresh", width="stretch"):
        st.session_state.pop("hg_arch_index", None)
        st.rerun()
    keep = {"All handouts": ha.VERSION_ORDER,
            "Student handouts": ["preparation", "ticket"],
            "Instructor handouts (Quests)": ["quest1", "quest2", "quest3"]}[show]
    shown = [e for e in entries if e["course_code"] == course and e["version"] in keep]
    if not shown:
        st.caption("No archived handouts yet for this selection. Every handout you generate is saved here "
                   "automatically.")
        return
    by_std = {}
    for e in shown:
        by_std.setdefault(e["std_code"], []).append(e)
    for code in sorted(by_std, key=ha.std_sort_key):
        _render_archive_standard(archive, code, by_std[code])


def _render_archive_standard(archive, code, items):
    """One card per learning standard, with one row per (language, handout group)."""
    rows = []
    for lang in sorted({e["lang"] for e in items}, key=lambda l: (l != "en", l)):
        for gkey, versions, glabel in ARCH_GROUPS:
            sets = sorted((e for e in items if e["lang"] == lang and e["version"] in versions),
                          key=lambda e: e["created"], reverse=True)
            if sets:
                rows.append((lang, gkey, glabel, sets))
    with st.container(border=True, key=f"hg_arch_std_{code}"):
        n = len(items)
        st.markdown(
            f'<div class="ar-head"><span class="ar-std">{code}</span><div>'
            f'<div class="ar-title">{items[0]["std_title"]}</div>'
            f'<div class="ar-sub">{n} saved set{"s" if n != 1 else ""} · '
            f'{len(rows)} handout{"s" if len(rows) != 1 else ""}</div></div></div>',
            unsafe_allow_html=True)
        for lang, gkey, glabel, sets in rows:
            st.markdown('<div class="ar-rule"></div>', unsafe_allow_html=True)
            student = gkey == "student"
            n_vis = sum(1 for e in sets if e.get("visible"))
            if not student:
                aud = '<span class="ar-pill ar-ins">Instructor only</span>'
            elif n_vis:
                aud = (f'<span class="ar-pill ar-stu">Visible to students'
                       f'{f" ({n_vis})" if len(sets) > 1 else ""}</span>')
            else:
                aud = '<span class="ar-pill ar-off">Not visible to students</span>'

            info = (f'<span class="ar-pill ar-lang">{ha.LANG_LABEL.get(lang, lang)}</span>'
                    f'<span class="ar-pill ar-type">{glabel if len(sets) > 1 else sets[0]["version_label"]}</span>{aud}'
                    f'<div class="ar-latest">Latest: {_fmt_when(sets[0]["created"])}</div>')
            if len(sets) == 1:
                cols = st.columns([3.3, 1.75, 1.45, 1.45, 0.6], vertical_alignment="center")
                cols[0].markdown(info, unsafe_allow_html=True)
                _render_set_actions(archive, sets[0], cols[1:])
            else:
                st.markdown(info, unsafe_allow_html=True)
                with st.expander(f"Manage {len(sets)} sets"):
                    for i, e in enumerate(sets, 1):
                        cols = st.columns([3.2, 1.75, 1.4, 1.4, 0.6], vertical_alignment="center")
                        rv = e.get("review", {})
                        flag = f' · <b style="color:#b45309;">{rv["unresolved"]} flagged</b>' if rv.get("unresolved") else ""
                        cols[0].markdown(
                            f'<div class="ar-set">Set {i} · <b>{e["version_label"]}</b> '
                            f'<span class="ar-when">· {_fmt_when(e["created"])} · '
                            f'{e.get("n_problems", "?")} problems</span>{flag}</div>',
                            unsafe_allow_html=True)
                        _render_set_actions(archive, e, cols[1:])


def _toggle_visible(archive, e, key):
    try:
        archive.set_visible(e["id"], bool(st.session_state.get(key)))
    except Exception as exc:  # noqa: BLE001
        st.session_state.hg_vis_error = f"Couldn't change who can see {e['std_code']} {e['version_label']}: {exc}"
    st.session_state.pop("hg_arch_index", None)
    _visible_index.clear()


def _render_set_actions(archive, e, cols):
    """Visible-to-students switch, PDF and LaTeX downloads, and delete, for one saved set."""
    if e["version"] in ha.STUDENT_VERSIONS:
        vis = bool(e.get("visible"))
        key = f"hg_a_vis_{e['id']}_{int(vis)}"
        cols[0].toggle("Visible to students", value=vis, key=key,
                       on_change=_toggle_visible, args=(archive, e, key),
                       help="Turn this on after you've checked the PDF. Students can then download "
                            "the PDF (never the LaTeX) from the home page. Editing or regenerating "
                            "a problem hides it again until you turn it back on.")
    cols = cols[1:]
    when = _fmt_when(e["created"])
    cache = st.session_state.setdefault("hg_arch_files", {})
    key = e["id"]
    if archive.kind == "local" and key not in cache:
        try:
            cache[key] = {k: archive.read(e["files"][k]) for k in ("pdf", "tex")}
        except Exception:  # noqa: BLE001
            cache[key] = {}
    if key in cache:
        base = e["files"]["pdf"].rsplit("/", 1)[-1][:-4]
        if cache[key].get("pdf"):
            cols[0].download_button("Download PDF", cache[key]["pdf"], file_name=f"{e['std_code']} {base}.pdf",
                                    mime="application/pdf", key=f"hg_a_pdf_{key}", width="stretch")
        if cache[key].get("tex"):
            cols[1].download_button("Download LaTeX", cache[key]["tex"], file_name=f"{e['std_code']} {base}.tex",
                                    mime="application/x-tex", key=f"hg_a_tex_{key}", width="stretch")
    elif cols[0].button("Get files", key=f"hg_a_get_{key}", width="stretch",
                        help="Fetch this set's PDF and LaTeX from the archive"):
        try:
            cache[key] = {k: archive.read(e["files"][k]) for k in ("pdf", "tex")}
        except Exception as exc:  # noqa: BLE001
            st.error(f"Couldn't fetch the files: {exc}")
        st.rerun()
    with cols[2].popover("🗑", help="Delete from the archive"):
        st.markdown(f"Delete **{e['std_code']} {e['version_label']}** ({when}) permanently?")
        if st.button("Delete", type="primary", key=f"hg_a_del_{key}"):
            try:
                archive.delete(e)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Couldn't delete: {exc}")
            st.session_state.pop("hg_arch_index", None)
            st.rerun()


# ── Student side: download handouts the instructor marked "Visible to students" ──
@st.cache_data(ttl=300, show_spinner=False)
def _visible_index():
    try:
        entries = ha.get_archive(st.secrets).list()
    except Exception:  # noqa: BLE001
        return None
    return [e for e in entries if e.get("visible") and e.get("version") in ha.STUDENT_VERSIONS]


@st.cache_data(ttl=3600, show_spinner=False, max_entries=64)
def _student_pdf(path, stamp):
    """PDF bytes for one visible handout (stamp = visible_at, so a re-posted file is re-read)."""
    return ha.get_archive(st.secrets).read(path)


def render_student_handouts(tl, selected_std=None, course="calc1"):
    """Handout picker + Download PDF button for the student home page."""
    items = _visible_index()
    if items is None:
        st.warning(tl("Handouts can't be loaded right now. Please try again in a few minutes.",
                      "No se pueden cargar las hojas ahora. Intenta de nuevo en unos minutos."))
        return
    items = [e for e in items if e.get("course") == course and e.get("files", {}).get("pdf")]
    if not items:
        st.info(tl("No handouts have been posted yet. Check back soon.",
                   "Todavía no hay hojas publicadas. Vuelve pronto."))
        return
    items.sort(key=lambda e: (ha.std_sort_key(e["std_code"]), ha.VERSION_ORDER.index(e["version"]),
                              e["lang"] != "en", e["created"]))
    if selected_std:
        mine = [e for e in items if ha.std_sort_key(e["std_code"]) == ha.std_sort_key(selected_std)]
        if mine:
            items = mine
        else:
            st.caption(tl(f"No handouts posted for {selected_std} yet. Here is everything available:",
                          f"Aún no hay hojas para {selected_std}. Esto es lo que hay disponible:"))
    by_id = {e["id"]: e for e in items}
    vlabel = {"preparation": tl("Preparation (with worked solutions)", "Preparación (con soluciones)"),
              "ticket": tl("Reassessment Ticket", "Ticket de reevaluación")}

    def _label(i):
        e = by_id[i]
        return (f"{e['std_code']} · {e['std_title']} — {vlabel[e['version']]} "
                f"({ha.LANG_LABEL.get(e['lang'], e['lang'])})")

    pick = st.selectbox(tl("Choose a handout", "Elige una hoja"), list(by_id), format_func=_label,
                        key="stu_handout_pick")
    e = by_id[pick]
    try:
        pdf = _student_pdf(e["files"]["pdf"], e.get("visible_at", ""))
    except Exception:  # noqa: BLE001
        st.error(tl("That handout couldn't be opened. Please try again later.",
                    "No se pudo abrir esa hoja. Intenta de nuevo más tarde."))
        return
    st.download_button(tl("Download PDF", "Descargar PDF"), pdf,
                       file_name=f"{e['std_code']} {e['version_label']} ({ha.LANG_LABEL.get(e['lang'], e['lang'])}).pdf",
                       mime="application/pdf", type="primary", use_container_width=True,
                       key="stu_handout_dl")
