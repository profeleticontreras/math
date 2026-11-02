# -*- coding: utf-8 -*-
"""Handout Generator screen for Canelita's instructor view.

app.py calls render_handout_generator(client) for the signed-in instructor.
Generation, review, LaTeX, and PDF logic live in handout_core.py.
Session keys start with "hg_" so they never collide with the tutor's state.
"""
import datetime
import io
import re
import zipfile

import anthropic
import streamlit as st

import handout_archive as ha
import handout_core as hc

TYPE_LABEL = {"skill": "Skill", "conceptual": "Conceptual", "interpretation": "Interpretation"}
VLABEL = hc.LABELS["en"]


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


TYPE_BADGE = {  # color + icon so the type is obvious without opening
    "preparation": ("#1565c0", "📘"), "quest1": ("#00695c", "📗"), "quest2": ("#00695c", "📗"),
    "quest3": ("#00695c", "📗"), "ticket": ("#e65100", "📙"),
}


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
    st.markdown('<p class="app-sub">Preparation &nbsp;·&nbsp; Quest 1, 2, 3 &nbsp;·&nbsp; Reassessment Ticket'
                ' &nbsp;·&nbsp; Claude writes the problems, checks every number with a calculator, and a '
                'second independent review checks the math, scope, and realism. Skim before printing.</p>',
                unsafe_allow_html=True)
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
            warn = "  ⚠️" if p.get("warnings") else ("  🛠" if p.get("repaired_from") else "")
            with st.expander(head + warn):
                st.caption(f"Subskill {p['subskill_code']}: {p['subskill']}"
                           + (f" · context: {p['context']}" if p.get("context") else ""))
                st.markdown(_preview_md(p["statement"]))
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
                                new = hc.regenerate_problem(*args)
                            else:
                                new = hc.duplicate_problem(*args, new_id=max(q["id"] for q in r["problems"]) + 1)
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

        with st.expander("✏️ Edit the LaTeX and recompile (optional)"):
            tex_name = out["base"] + ".tex"
            edited = st.text_area("LaTeX source", out["files"][tex_name], height=380, key=f"hg_edit_{e['id']}")
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


def _render_archive(archive):
    if archive.kind == "github":
        st.caption(f"📚 Every handout is saved permanently in your private GitHub repository "
                   f"**{archive.repo}**, in one folder per learning standard.")
    else:
        st.info("Handouts are being saved in the app's own folder (handout_archive). On Streamlit Cloud "
                "that folder is erased whenever the app restarts or updates. To keep them permanently, "
                "connect a private GitHub repository by adding HANDOUT_ARCHIVE_REPO and "
                "HANDOUT_ARCHIVE_TOKEN to the app's secrets.")
    if "hg_arch_index" not in st.session_state:
        try:
            st.session_state.hg_arch_index = archive.list()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Couldn't open the archive: {exc}")
            return
    entries = st.session_state.hg_arch_index
    c1, c2, c3 = st.columns([2, 3, 1])
    courses = sorted({e["course_code"] for e in entries}) or ["MAT 3A"]
    course = c1.radio("Course", courses, horizontal=True, key="hg_arch_course")
    types = c2.multiselect("Show", ha.VERSION_ORDER, default=ha.VERSION_ORDER, key="hg_arch_types",
                           format_func=lambda v: f"{TYPE_BADGE[v][1]} {ha.VERSION_LABEL[v]}")
    if c3.button("↻ Refresh", key="hg_arch_refresh", width="stretch"):
        st.session_state.pop("hg_arch_index", None)
        st.rerun()
    shown = [e for e in entries if e["course_code"] == course and e["version"] in types]
    if not shown:
        st.caption("No archived handouts yet for this selection. Every handout you generate is saved here "
                   "automatically.")
        return
    st.markdown(
        " &nbsp; ".join(f'<span style="background:{c};color:#fff;border-radius:6px;padding:2px 9px;'
                        f'font-size:0.8rem;font-weight:600;">{i} {ha.VERSION_LABEL[v]}</span>'
                        for v, (c, i) in TYPE_BADGE.items() if v in ("preparation", "quest1", "ticket"))
        .replace("Quest 1", "Quest 1 · 2 · 3"), unsafe_allow_html=True)
    by_std = {}
    for e in shown:
        by_std.setdefault(e["std_code"], []).append(e)
    for code in sorted(by_std, key=ha.std_sort_key):
        items = sorted(by_std[code], key=lambda e: (ha.VERSION_ORDER.index(e["version"]), e["created"]),
                       reverse=False)
        counts = {}
        for e in items:
            counts[e["version"]] = counts.get(e["version"], 0) + 1
        summary = " · ".join(f"{TYPE_BADGE[v][1]} {ha.VERSION_LABEL[v]} ×{n}"
                             for v, n in sorted(counts.items(), key=lambda kv: ha.VERSION_ORDER.index(kv[0])))
        with st.expander(f"**{code} — {items[0]['std_title']}**   ·   {summary}"):
            for e in sorted(items, key=lambda e: (ha.VERSION_ORDER.index(e["version"]), e["created"])):
                _render_archive_row(archive, e)


def _render_archive_row(archive, e):
    color, icon = TYPE_BADGE[e["version"]]
    when = e["created"][:16].replace("T", " ")
    rv = e.get("review", {})
    flag = f" · ⚠️ {rv['unresolved']} flagged" if rv.get("unresolved") else ""
    cols = st.columns([5, 1.3, 1.3, 0.8])
    cols[0].markdown(
        f'<span style="background:{color};color:#fff;border-radius:6px;padding:3px 10px;font-weight:700;">'
        f'{icon} {e["version_label"]}</span> &nbsp; {ha.LANG_LABEL.get(e["lang"], e["lang"])} · {when} · '
        f'{e.get("n_problems", "?")} problems{flag}', unsafe_allow_html=True)
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
            cols[1].download_button("⬇️ PDF", cache[key]["pdf"], file_name=f"{e['std_code']} {base}.pdf",
                                    mime="application/pdf", key=f"hg_a_pdf_{key}", width="stretch")
        if cache[key].get("tex"):
            cols[2].download_button("⬇️ .tex", cache[key]["tex"], file_name=f"{e['std_code']} {base}.tex",
                                    mime="application/x-tex", key=f"hg_a_tex_{key}", width="stretch")
    elif cols[1].button("📥 Get files", key=f"hg_a_get_{key}", width="stretch"):
        try:
            cache[key] = {k: archive.read(e["files"][k]) for k in ("pdf", "tex")}
        except Exception as exc:  # noqa: BLE001
            st.error(f"Couldn't fetch the files: {exc}")
        st.rerun()
    with cols[3].popover("🗑", help="Delete from the archive"):
        st.markdown(f"Delete **{e['std_code']} {e['version_label']}** ({when}) permanently?")
        if st.button("Delete", type="primary", key=f"hg_a_del_{key}"):
            try:
                archive.delete(e)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Couldn't delete: {exc}")
            st.session_state.pop("hg_arch_index", None)
            st.rerun()
