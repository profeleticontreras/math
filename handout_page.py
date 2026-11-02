# -*- coding: utf-8 -*-
"""Handout Generator screen for Canelita's instructor view.

app.py calls render_handout_generator(client) when the signed-in instructor
opens the generator. Generation, LaTeX, and PDF logic live in handout_core.py.
Session keys start with "hg_" so they never collide with the tutor's state.
"""
import datetime
import io
import re
import zipfile

import anthropic
import streamlit as st

import handout_core as hc

TYPE_NAMES = {"preparation": "Preparation", "quest": "Quest", "ticket": "Ticket for Reassessment"}
TYPE_LABEL = {"skill": "Skill", "conceptual": "Conceptual", "interpretation": "Interpretation"}


@st.cache_data
def _standards():
    return hc.load_standards()


def _preview_md(text):
    """Rough Markdown preview of LaTeX (the PDF is the real output)."""
    if not text:
        return ""
    text = re.sub(r"\\begin\{center\}\s*\\begin\{tikzpicture\}.*?\\end\{tikzpicture\}\s*\\end\{center\}",
                  "\n\n*(graph -- see PDF)*\n\n", text, flags=re.S)
    text = re.sub(r"\\begin\{tikzpicture\}.*?\\end\{tikzpicture\}", "*(graph -- see PDF)*", text, flags=re.S)
    text = re.sub(r"(\\begin\{center\}\s*)?\\begin\{tabular\}.*?\\end\{tabular\}(\s*\\end\{center\})?",
                  "\n\n*(table -- see PDF)*\n\n", text, flags=re.S)
    text = re.sub(r"\\\[(.*?)\\\]", lambda m: "\n\n$$" + m.group(1).strip() + "$$\n\n", text, flags=re.S)
    text = re.sub(r"\\textbf\{([^{}]*)\}", r"**\1**", text)
    text = re.sub(r"\\textit\{([^{}]*)\}|\\emph\{([^{}]*)\}", lambda m: "*" + (m.group(1) or m.group(2)) + "*", text)
    return text.replace(r"\%", "%").replace(r"\$", "＄").replace("``", '"').replace("''", '"')


def _build_outputs():
    """Build .tex (and PDFs when pdflatex is available) for the current handout."""
    h = st.session_state.hg_handout
    base = hc.base_name(h, datetime.date.today().isoformat())
    out = {"base": base, "errors": {}, "files": {}}
    versions = ["student"] + (["teacher"] if h["type"] != "preparation" and h.get("teacher_key") else [])
    for v in versions:
        suffix = "" if h["type"] == "preparation" else f"_{v}"
        tex = hc.build_tex(h, v)
        out["files"][f"{base}{suffix}.tex"] = tex
        if hc.find_pdflatex():
            pdf, err = hc.compile_pdf(tex)
            if pdf:
                out["files"][f"{base}{suffix}.pdf"] = pdf
            else:
                out["errors"][v] = err
    st.session_state.hg_outputs = out


def render_handout_generator(client):
    st.markdown('<p class="app-title">📝 Handout Generator</p>', unsafe_allow_html=True)
    st.markdown('<p class="app-sub">Preparation &nbsp;·&nbsp; Quest &nbsp;·&nbsp; Ticket for Reassessment'
                ' &nbsp;·&nbsp; built from the 24 MAT 3A learning standards. Claude writes the problems; '
                'skim them before they go to students.</p>', unsafe_allow_html=True)

    if not hc.find_pdflatex():
        st.warning("LaTeX isn't installed where the app is running, so you'll get .tex files only "
                   "(open them in TeXstudio to make the PDF).")

    stds = _standards()
    by_code = {s["code"]: s for s in stds}

    c1, c2 = st.columns([3, 1])
    with c1:
        htype = st.radio("Handout type", hc.HANDOUT_ORDER, format_func=TYPE_NAMES.get,
                         horizontal=True, key="hg_type")
    with c2:
        lang = st.radio("Language", ["en", "es"], format_func={"en": "English", "es": "Español"}.get,
                        horizontal=True, key="hg_lang")

    codes = st.multiselect("Learning standard(s)", list(by_code),
                           format_func=lambda c: f"{c} — {by_code[c]['title']}", key="hg_codes",
                           placeholder="Choose one or more standards (each starts on its own page)")

    st.markdown("**Problems per standard** — each problem uses a randomly chosen subskill")
    n1, n2, n3, n4 = st.columns(4)
    d = hc.DEFAULT_COUNTS[htype]
    counts = {
        "skill": n1.number_input("Skill", 0, 6, d, key=f"hg_n_skill_{htype}"),
        "conceptual": n2.number_input("Conceptual", 0, 6, d, key=f"hg_n_conc_{htype}"),
        "interpretation": n3.number_input("Interpretation", 0, 6, d, key=f"hg_n_interp_{htype}"),
    }
    work = n4.selectbox("Work space after each problem", list(hc.WORK_SPACE),
                        index=0 if htype == "preparation" else 1, key=f"hg_ws_{htype}")

    teacher_key = False
    if htype == "preparation":
        st.info("Preparations include worked solutions at the end of the handout.")
    else:
        teacher_key = st.checkbox("Also make a teacher version with the answer key", value=True,
                                  key=f"hg_tk_{htype}")

    with st.expander("Heading and instructions"):
        course = st.text_input("Course", "MAT 3A: Calculus 1", key="hg_course")
        instructions = st.text_area("Instructions", hc.default_instructions(lang, htype),
                                    key=f"hg_instr_{htype}_{lang}", height=130)

    n_total = sum(counts.values()) * len(codes)
    go = st.button(f"Generate {TYPE_NAMES[htype]}" + (f"  ({n_total} problems)" if n_total else ""),
                   type="primary", disabled=(not codes or n_total == 0), key="hg_go")

    if go:
        bar = st.progress(0.0, text=f"Writing problems for {len(codes)} standard(s)… about a minute.")
        try:
            results = hc.generate_handout(
                client, [by_code[c] for c in codes], counts, lang, htype,
                progress=lambda done, total: bar.progress(done / total,
                                                          text=f"Finished {done} of {total} standard(s)…"))
        except anthropic.APIError as e:
            bar.empty()
            st.error(f"Claude couldn't generate the problems: {e}")
            return
        bar.progress(1.0, text="Compiling…")
        st.session_state.hg_handout = {
            "type": htype, "lang": lang, "course": course,
            "course_code": course.split(":")[0].strip() or "MAT 3A",
            "instructions": instructions, "work_space": work, "teacher_key": teacher_key,
            "results": results,
        }
        _build_outputs()
        bar.empty()

    h = st.session_state.get("hg_handout")
    out = st.session_state.get("hg_outputs")
    if not (h and out):
        return

    st.divider()
    st.subheader(f"{TYPE_NAMES[h['type']]} — " + ", ".join(r["std"]["code"] for r in h["results"]))
    for r in h["results"]:
        for note in r["notes"]:
            st.warning(f"{r['std']['code']}: {note}")
    for v, err in out["errors"].items():
        st.error(f"The {v} PDF didn't compile. The .tex file is still available. LaTeX said:")
        st.code(err, language="text")

    files = out["files"]
    cols = st.columns(len(files) + 1)
    for col, (name, data) in zip(cols, files.items()):
        is_pdf = name.endswith(".pdf")
        who = "Teacher" if "_teacher" in name else "Student" if "_student" in name else "Handout"
        col.download_button(f"⬇️ {who} {'PDF' if is_pdf else '.tex'}", data=data, file_name=name,
                            mime="application/pdf" if is_pdf else "application/x-tex",
                            use_container_width=True, key=f"hg_dl_{name}")
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    cols[-1].download_button("⬇️ All files (.zip)", data=zbuf.getvalue(), file_name=out["base"] + ".zip",
                             mime="application/zip", use_container_width=True, key="hg_dl_zip")

    st.markdown("#### Review the problems")
    st.caption("Tables and graphs show only in the PDF. Use 🔄 to replace any problem you don't like.")
    tabs = st.tabs([r["std"]["code"] for r in h["results"]])
    for tab, r in zip(tabs, h["results"]):
        with tab:
            for p in r["problems"]:
                head = f"{p.get('num', p['id'])}. [{TYPE_LABEL[p['type']]} · {p['subskill_code']}] {p['title']}"
                with st.expander(head + ("  ⚠️" if p.get("warnings") else "")):
                    st.caption(f"Subskill {p['subskill_code']}: {p['subskill']}")
                    st.markdown(_preview_md(p["statement"]))
                    for letter, part in zip("abcd", p.get("parts", [])):
                        st.markdown(f"**({letter})** " + _preview_md(part))
                    if st.toggle("Show answer and solution", key=f"hg_sol_{r['std']['code']}_{p['id']}"):
                        st.markdown("**Answer:** " + _preview_md(p["answer"]))
                        st.markdown(_preview_md(p["solution"]))
                    for w in p.get("warnings", []):
                        st.caption(f"⚠️ {w}")
                    if st.button("🔄 Regenerate this problem", key=f"hg_regen_{r['std']['code']}_{p['id']}"):
                        with st.spinner("Writing a new problem…"):
                            try:
                                new = hc.regenerate_problem(client, r["std"], p, h["lang"], h["type"])
                            except Exception as e:  # noqa: BLE001
                                st.error(str(e))
                            else:
                                r["problems"][r["problems"].index(p)] = new
                                _build_outputs()
                                st.rerun()

    with st.expander("✏️ Edit the LaTeX directly (optional)"):
        st.caption("Edits here change only this file. For the teacher version, edit it separately "
                   "or regenerate the problem above.")
        tex_names = [n for n in files if n.endswith(".tex")]
        which = st.selectbox("File", tex_names, key="hg_edit_which")
        edited = st.text_area("LaTeX source", files[which], height=420, key=f"hg_edit_{which}")
        if st.button("Compile my edits", key="hg_compile_edits"):
            pdf, err = hc.compile_pdf(edited)
            if pdf:
                st.success("Compiled.")
                st.download_button("⬇️ Edited PDF", data=pdf, file_name=which.replace(".tex", "_edited.pdf"),
                                   mime="application/pdf", key="hg_dl_edited")
            else:
                st.error("LaTeX error:")
                st.code(err, language="text")
