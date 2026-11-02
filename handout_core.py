# -*- coding: utf-8 -*-
"""
handout_core.py -- Handout generator for Canelita (MAT 3A: Calculus 1)

Builds three kinds of handouts from the official learning standards:
  * Preparation             -- practice problems + worked solutions for students
  * Quest                   -- assessment (student copy + optional teacher key)
  * Ticket for Reassessment -- reassessment (student copy + optional teacher key)

For each chosen standard, every problem is tied to a randomly chosen official
subskill and is one of three types: skill, conceptual, interpretation.
Claude writes the problems in a tagged format; this module assembles them into
an exam-class LaTeX file and compiles it to PDF with pdflatex.

No Streamlit code lives here, so it can be tested on its own.
"""
import ast
import glob
import os
import pathlib
import random
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

APP_DIR = pathlib.Path(__file__).resolve().parent
HANDOUTS_DIR = APP_DIR / "handouts"
MODEL = "claude-sonnet-4-5"      # same model the tutor already uses
MAX_TOKENS = 16000

QUESTION_TYPES = ["skill", "conceptual", "interpretation"]
HANDOUT_ORDER = ["preparation", "quest", "ticket"]
DEFAULT_COUNTS = {"preparation": 3, "quest": 2, "ticket": 3}
WORK_SPACE = {"None": "0in", "Small (0.75 in)": "0.75in",
              "Medium (1.5 in)": "1.5in", "Large (2.5 in)": "2.5in"}

LABELS = {
    "en": {
        "preparation": "Preparation", "quest": "Quest",
        "ticket": "Ticket for Reassessment",
        "skill": "Skill", "conceptual": "Conceptual",
        "interpretation": "Interpretation",
        "skill_desc": "Carry out the computation or procedure.",
        "conceptual_desc": "Explain the idea behind the mathematics.",
        "interpretation_desc": "Explain what the mathematics means in context.",
        "part": "Part", "name": "Name", "date": "Date", "section": "Section",
        "instructions": "Instructions", "page": "Page", "of": "of",
        "pass": "Pass", "retake": "Retake",
        "worked": "Worked Solutions", "key": "Answer Key",
        "teacher": "Teacher Version", "teacher_short": "Teacher", "teacher_note": "Teacher Version -- includes answer key",
        "problem": "Problem", "answer": "Answer", "sec": "Sec.",
    },
    "es": {
        "preparation": "Preparación", "quest": "Quest",
        "ticket": "Ticket de reevaluación",
        "skill": "Habilidad", "conceptual": "Conceptual",
        "interpretation": "Interpretación",
        "skill_desc": "Realiza el cálculo o el procedimiento.",
        "conceptual_desc": "Explica la idea detrás de las matemáticas.",
        "interpretation_desc": "Explica qué significan las matemáticas en el contexto.",
        "part": "Parte", "name": "Nombre", "date": "Fecha", "section": "Sección",
        "instructions": "Instrucciones", "page": "Página", "of": "de",
        "pass": "Aprobado", "retake": "Repetir",
        "worked": "Soluciones desarrolladas", "key": "Clave de respuestas",
        "teacher": "Versión del profesor", "teacher_short": "Profesor", "teacher_note": "Versión del profesor -- incluye la clave de respuestas",
        "problem": "Problema", "answer": "Respuesta", "sec": "Secc.",
    },
}

DEFAULT_INSTRUCTIONS = {
    ("en", "preparation"): (
        "Use this preparation to practice before the Quest. Try each problem on your own "
        "first, then compare your reasoning with the worked solutions at the end. Show all "
        "of your work and give exact answers unless rounding is requested."),
    ("en", "assessment"): (
        "To give you credit, I need to see how you think through each problem. Show all work "
        "so I can fairly assess your understanding and give you helpful feedback. Give exact "
        "answers unless rounding is requested, and box your final answers. Write your name, "
        "the assessment title, and the corresponding question numbers on any separate sheets "
        "you submit. Thank you."),
    ("es", "preparation"): (
        "Usa esta preparación para practicar antes del Quest. Primero intenta cada problema "
        "por tu cuenta y después compara tu razonamiento con las soluciones desarrolladas al "
        "final. Muestra todo tu trabajo y da respuestas exactas a menos que se pida redondear."),
    ("es", "assessment"): (
        "Para darte crédito, necesito ver cómo razonas en cada problema. Muestra todo tu "
        "trabajo para que pueda evaluar tu comprensión de manera justa y darte comentarios "
        "útiles. Da respuestas exactas a menos que se pida redondear, y encierra tus respuestas "
        "finales en un recuadro. Escribe tu nombre, el título de la evaluación y los números de "
        "las preguntas en cualquier hoja adicional que entregues. Gracias."),
}


def default_instructions(lang, htype):
    return DEFAULT_INSTRUCTIONS[(lang, "preparation" if htype == "preparation" else "assessment")]


# ------------------------------------------------------------------
# Standards: kept in handout_standards.json next to this file.
# ------------------------------------------------------------------
def load_standards(path=APP_DIR / "handout_standards.json"):
    """The 24 official MAT 3A learning standards (from the standards docx),
    each with code, title, sections, description, and 4 subskills."""
    import json
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


# ------------------------------------------------------------------
# Planning: which subskill each problem targets
# ------------------------------------------------------------------
def plan_problems(std, counts, rng=random):
    """Pick subskills at random for each question type. Within a type the
    subskills don't repeat until all four have been used."""
    slots = []
    n_sub = len(std["subskills"])
    for qtype in QUESTION_TYPES:
        n = int(counts.get(qtype, 0))
        picks = []
        while len(picks) < n:
            batch = list(range(n_sub))
            rng.shuffle(batch)
            picks.extend(batch)
        for i in sorted(picks[:n]):
            slots.append({"type": qtype,
                          "subskill_code": f"{std['code']}.{i + 1}",
                          "subskill": std["subskills"][i]})
    for k, s in enumerate(slots, 1):
        s["id"] = k
    return slots


# ------------------------------------------------------------------
# Prompting
# ------------------------------------------------------------------
HANDOUT_PURPOSE = {
    "preparation": ("a PREPARATION handout: practice students do before the Quest. Problems may "
                    "be lightly scaffolded. Students receive the solutions, so each solution must "
                    "be complete, step by step, and written to teach."),
    "quest": ("a QUEST: an in-class assessment of the standard. Problems must be fair, "
              "unambiguous, and at the level of a typical Calculus 1 exam question, with no trick "
              "questions. Solutions are for the instructor's answer key."),
    "ticket": ("a TICKET FOR REASSESSMENT: a second chance to show mastery after an earlier "
               "attempt. Same difficulty as a Quest, but use fresh functions, numbers, and "
               "contexts. Solutions are for the instructor's answer key."),
}

TYPE_GUIDE = {
    "skill": ("SKILL: carry out the computation or procedure the subskill names (evaluate, "
              "differentiate, solve, set up). It has a definite final answer."),
    "conceptual": ("CONCEPTUAL: test understanding of why or what, not just how. For example: "
                   "explain a definition or theorem in your own words, decide true or false and "
                   "justify, find and fix an error in sample student work, compare two ideas, or "
                   "predict a result without computing. It still has a clear expected answer that "
                   "can be graded."),
    "interpretation": ("INTERPRETATION: explain what a mathematical result means: units, the "
                       "meaning of a sign or value in a realistic context, information read from "
                       "a table or graph, or whether a result is reasonable. Ask for answers in "
                       "complete sentences."),
}

FORMAT_RULES = r"""Rules for the LaTeX inside the tags:
- It is pasted into a LaTeX exam-class document that loads amsmath, amssymb, and pgfplots. Do not use any other package or define new commands.
- Inline math: $...$. Displayed math: \[ ... \]. Never use $$, \( \), or numbered equation environments; for multi-line work use \begin{aligned} inside \[ \].
- Keep inline math short so it never has to break across lines; put any formula longer than about 25 characters in displayed math.
- Use LaTeX commands for every math symbol (\le, \infty, \pi, \to, \cdot, \sqrt{}). Text is plain ASCII<<ACCENTS>>. No Unicode math symbols, no curly quotes.
- Write a literal dollar sign as \$ and a percent sign as \%.
- Do not use \section, \question, \part, \begin{parts}, \newpage, \vspace, markdown, or bullet characters.
- Use 0 to 4 <part> tags. Do not write (a), (b) labels at the start of a part; they are added automatically. A problem without parts has no <part> tags.
- Tables: \begin{center}\begin{tabular}{|c|c|c|} with \hline rules, header row first\end{tabular}\end{center}.
- Graphs only when the subskill needs one. Use pgfplots with explicit formulas, for example:
  \begin{center}\begin{tikzpicture}\begin{axis}[width=7cm, height=5cm, axis lines=middle, xlabel={$x$}, ylabel={$y$}, grid=both]\addplot[thick, domain=-2:3, samples=100]{x^2-1};\end{axis}\end{tikzpicture}\end{center}
  Right after every graph, add one sentence that begins "Graph description:" and describes the graph in words for students who cannot see it.
- Contexts are fictional and realistic. No real people or brand names.
- Choose numbers so answers come out clean, or state exactly how to round.
- In <answer>, give only the final results, labeled (a), (b), ... when there are parts. Do not use \boxed.
- In <solution>, show every step a student would need, with short explanations between steps.
- Before writing each problem, solve it yourself and check the answer. Each problem must be solvable with only the information given, and must truly assess its assigned subskill."""

BLOCK_FORMAT = """<problem id="1">
<title>2 to 6 word label naming the skill, no math</title>
<statement>problem text in LaTeX</statement>
<part>text of the first part</part>
<part>text of the second part</part>
<answer>final answer(s)</answer>
<solution>complete worked solution</solution>
</problem>"""


def _std_context(std):
    subs = "\n".join(f"  {std['code']}.{i}: {s}" for i, s in enumerate(std["subskills"], 1))
    return (f"Learning standard {std['code']} -- {std['title']} (Active Calculus, "
            f"Sec. {std['sections']})\nDescription: {std['description']}\nSubskills:\n{subs}")


def build_prompt(std, slots, lang, htype, avoid=None):
    language = ("Write every problem, part, answer, and solution in Spanish (as spoken in a "
                "California community college classroom), with standard math notation."
                if lang == "es" else "Write in English.")
    slot_lines = "\n".join(
        f'{s["id"]}. type: {TYPE_GUIDE[s["type"]].split(":")[0]}; subskill {s["subskill_code"]} -- {s["subskill"]}'
        for s in slots)
    types_used = sorted({s["type"] for s in slots}, key=QUESTION_TYPES.index)
    type_text = "\n".join(f"- {TYPE_GUIDE[t]}" for t in types_used)
    rules = FORMAT_RULES.replace("<<ACCENTS>>", " plus Spanish accented letters and inverted punctuation"
                                 if lang == "es" else "")
    avoid_text = ""
    if avoid:
        avoid_text = ("\nWrite a different problem from this earlier version (new function, numbers, "
                      f"and context):\n{avoid}\n")
    return f"""You are an experienced Calculus 1 professor at a California community college (course MAT 3A, textbook Active Calculus by Boelkins). Write problems for {HANDOUT_PURPOSE[htype]}

{_std_context(std)}

Question types:
{type_text}

Write exactly {len(slots)} problem(s), one for each slot below, in this order. Each problem must target its assigned subskill and be of its assigned type. Vary the functions, numbers, and contexts so no two problems feel alike.
{slot_lines}
{avoid_text}
{language}

Return only the problem blocks, in this exact format, using the slot number as the id:
{BLOCK_FORMAT}

{rules}"""


# ------------------------------------------------------------------
# Parsing and cleanup of Claude's output
# ------------------------------------------------------------------
BLOCK_RE = re.compile(r'<problem\s+id\s*=\s*"?(\d+)"?\s*>(.*?)</problem>', re.S)


def _tag(body, name):
    m = re.search(rf"<{name}>(.*?)</{name}>", body, re.S)
    return m.group(1).strip() if m else ""


UNICODE_MAP = {
    "\u2018": "`", "\u2019": "'", "\u201c": "``", "\u201d": "''", "\u2014": "---", "\u2013": "--",
    "\u2212": "-", "\u2032": "'", "\u2033": "''", "\u00a0": " ", "\u2026": "...",
    "\u2264": r"\ensuremath{\le}", "\u2265": r"\ensuremath{\ge}", "\u2260": r"\ensuremath{\neq}",
    "\u221e": r"\ensuremath{\infty}", "\u2192": r"\ensuremath{\to}", "\u00d7": r"\ensuremath{\times}",
    "\u00b7": r"\ensuremath{\cdot}", "\u22c5": r"\ensuremath{\cdot}", "\u03c0": r"\ensuremath{\pi}",
    "\u0394": r"\ensuremath{\Delta}", "\u03b8": r"\ensuremath{\theta}", "\u00b1": r"\ensuremath{\pm}",
    "\u2248": r"\ensuremath{\approx}", "\u00b0": r"\ensuremath{^\circ}", "\u221a": r"\ensuremath{\surd}",
    "\u222b": r"\ensuremath{\int}", "\u00b2": r"\ensuremath{^2}", "\u00b3": r"\ensuremath{^3}",
    "\u2211": r"\ensuremath{\sum}",
}
FORBIDDEN_RE = re.compile(r"\\(newpage|clearpage|pagebreak|newline\s*\[|vspace\*?\s*\{[^}]*\}|section\*?\s*\{[^}]*\})")


def clean_latex(text):
    """Make model LaTeX safe for pdflatex. Returns (text, warnings)."""
    warnings = []
    if not text:
        return text, warnings
    for u, r in UNICODE_MAP.items():
        text = text.replace(u, r)
    # $$...$$ -> \[...\]
    text = re.sub(r"\$\$(.+?)\$\$", r"\\[\1\\]", text, flags=re.S)
    text = FORBIDDEN_RE.sub("", text)
    for bad in (r"\question", r"\begin{parts}", r"\end{parts}", r"\begin{questions}", r"\end{questions}"):
        if bad in text:
            warnings.append(f"removed {bad}")
            text = text.replace(bad, "")
    text = re.sub(r"\\part\b(?!ial)", "", text)
    # characters pdflatex can't handle
    odd = sorted({c for c in text if ord(c) > 255})
    if odd:
        warnings.append("replaced unsupported characters: " + " ".join(odd))
        text = "".join("?" if ord(c) > 255 else c for c in text)
    # balance checks
    if len(re.findall(r"(?<!\\)\$", text)) % 2:
        warnings.append("unbalanced $ signs")
    if text.count("{") - text.count(r"\{") != text.count("}") - text.count(r"\}"):
        warnings.append("unbalanced braces")
    return text, warnings


TYPE_TITLE_FALLBACK = {"skill": "Skill", "conceptual": "Concept", "interpretation": "Interpretation"}


def parse_problems(text, slots):
    """Turn Claude's tagged reply into problem dicts keyed to the planned slots."""
    found = {int(i): body for i, body in BLOCK_RE.findall(text)}
    problems, missing = [], []
    for s in slots:
        body = found.get(s["id"])
        if body is None:
            missing.append(s)
            continue
        p = dict(s)
        p["warnings"] = []
        for field in ("title", "statement", "answer", "solution"):
            p[field], w = clean_latex(_tag(body, field))
            p["warnings"] += w
        if not p["title"]:  # tolerate an unclosed <title> tag
            m = re.search(r"<title>([^<\n]*)", body)
            p["title"] = m.group(1).strip() if m else ""
        p["title"] = re.sub(r"[$\\{}]", "", p["title"])[:60] or TYPE_TITLE_FALLBACK[s["type"]]
        p["parts"] = []
        for part in re.findall(r"<part>(.*?)</part>", body, re.S):
            part = re.sub(r"^\s*\(?[a-dA-D]\)\s*", "", part.strip())
            cleaned, w = clean_latex(part)
            p["parts"].append(cleaned)
            p["warnings"] += w
        if not p["statement"]:
            p["warnings"].append("empty statement")
        problems.append(p)
    return problems, missing


# ------------------------------------------------------------------
# Claude calls
# ------------------------------------------------------------------
def call_claude(client, prompt, max_tokens=MAX_TOKENS):
    resp = client.messages.create(model=MODEL, max_tokens=max_tokens,
                                  messages=[{"role": "user", "content": prompt}])
    text = "".join(getattr(b, "text", "") for b in resp.content)
    return text, resp.stop_reason


def generate_for_standard(client, std, counts, lang, htype, rng=random, check=True):
    """Generate, parse, and (if pdflatex exists) compile-check one standard's problems."""
    slots = plan_problems(std, counts, rng)
    notes = []
    if not slots:
        return {"std": std, "problems": [], "notes": notes}
    text, stop = call_claude(client, build_prompt(std, slots, lang, htype))
    if stop == "max_tokens":
        notes.append("Claude's reply was cut off; missing problems were requested again.")
    problems, missing = parse_problems(text, slots)
    if missing:  # one more try for anything that didn't come back
        sub = [dict(s, id=k) for k, s in enumerate(missing, 1)]
        text2, _ = call_claude(client, build_prompt(std, sub, lang, htype))
        extra, still = parse_problems(text2, sub)
        for e, orig in zip(extra, missing):
            e["id"] = orig["id"]
        problems += extra
        if still:
            notes.append(f"{len(still)} problem(s) could not be generated.")
        problems.sort(key=lambda p: p["id"])
    if check and find_pdflatex():
        problems = repair_failures(client, std, problems, lang, htype, notes)
    return {"std": std, "problems": problems, "notes": notes}


def regenerate_problem(client, std, problem, lang, htype):
    """Write a fresh problem for the same slot (same type and subskill)."""
    slot = {k: problem[k] for k in ("type", "subskill_code", "subskill")}
    slot["id"] = 1
    text, _ = call_claude(client, build_prompt(std, [slot], lang, htype, avoid=problem["statement"]),
                          max_tokens=6000)
    new, _ = parse_problems(text, [slot])
    if not new:
        raise RuntimeError("Claude did not return a problem. Try again.")
    p = new[0]
    p["id"] = problem["id"]
    notes = []
    if find_pdflatex():
        p = repair_failures(client, std, [p], lang, htype, notes)[0]
        p["warnings"] += notes
    return p


def repair_failures(client, std, problems, lang, htype, notes, attempts=2):
    """Compile each problem alone; ask Claude to fix any that don't compile."""
    for p in problems:
        for attempt in range(attempts):
            ok, err = problem_compiles(p)
            if ok:
                break
            prompt = (
                "This problem block does not compile in LaTeX (exam class with amsmath, amssymb, "
                f"pgfplots). pdflatex error:\n{err}\n\nRewrite the block so it compiles. Keep the "
                "same mathematics, type, and subskill. Return only the corrected block with "
                f'id="1".\n\n{block_text(p)}\n\n'
                + FORMAT_RULES.replace("<<ACCENTS>>", " plus Spanish accented letters" if lang == "es" else ""))
            text, _ = call_claude(client, prompt, max_tokens=6000)
            slot = {k: p[k] for k in ("type", "subskill_code", "subskill")}
            slot["id"] = 1
            fixed, _ = parse_problems(text, [slot])
            if fixed:
                fixed[0]["id"] = p["id"]
                p.clear()
                p.update(fixed[0])
        else:
            ok, err = problem_compiles(p)
            if not ok:
                notes.append(f"Problem {p['id']} ({p['subskill_code']}) still has a LaTeX error -- "
                             "edit or regenerate it.")
                p.setdefault("warnings", []).append("LaTeX error: " + err[:300])
    return problems


def block_text(p):
    parts = "".join(f"<part>{x}</part>\n" for x in p.get("parts", []))
    return (f'<problem id="1">\n<title>{p["title"]}</title>\n<statement>{p["statement"]}</statement>\n'
            f'{parts}<answer>{p["answer"]}</answer>\n<solution>{p["solution"]}</solution>\n</problem>')


def generate_handout(client, standards, counts, lang, htype, progress=None, workers=4):
    """Generate problems for several standards in parallel. progress(done, total) is optional."""
    results = [None] * len(standards)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(generate_for_standard, client, s, counts, lang, htype): i
                   for i, s in enumerate(standards)}
        done = 0
        for fut in as_completed(futures):
            i = futures[fut]
            results[i] = fut.result()
            done += 1
            if progress:
                progress(done, len(standards))
    return results


# ------------------------------------------------------------------
# LaTeX assembly
# ------------------------------------------------------------------
def esc(s):
    """Escape plain text (titles, instructions) for LaTeX."""
    rep = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
           "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    s = "".join(rep.get(c, c) for c in str(s))
    for u, r in UNICODE_MAP.items():
        s = s.replace(u, r)
    return "".join("?" if ord(c) > 255 else c for c in s)


PREAMBLE = r"""\documentclass[12pt]{exam}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage{amsmath,amssymb}
\usepackage[margin=0.9in,headheight=16pt,headsep=14pt,footskip=28pt]{geometry}
\usepackage{pgfplots}
\pgfplotsset{compat=1.16}
\usepackage{needspace}
\usepackage[hidelinks,pdftitle={<<PDFTITLE>>},pdfauthor={<<COURSE>>},pdfsubject={<<PDFSUBJECT>>},pdflang={<<PDFLANG>>}]{hyperref}
\input{glyphtounicode}
\pdfgentounicode=1
\newcommand{\StdCode}{}
\newcommand{\StdName}{}
\newcommand{\SetStandard}[2]{\gdef\StdCode{#1}\gdef\StdName{#2}}
\pagestyle{headandfoot}
\firstpageheader{<<COURSE>>}{\textbf{<<HEADTYPE>>}}{\textbf{\StdCode}<<TEACHERMARK>>}
\runningheader{<<COURSE>>}{\textbf{<<HEADTYPE>>}}{\textbf{\StdCode}<<TEACHERMARK>>}
\firstpageheadrule
\runningheadrule
\firstpagefooter{\small\StdCode\ --- \StdName}{}{\small <<PAGE>> \thepage\ <<OF>> \numpages}
\runningfooter{\small\StdCode\ --- \StdName}{}{\small <<PAGE>> \thepage\ <<OF>> \numpages}
\firstpagefootrule
\runningfootrule
\renewcommand{\questionlabel}{\textbf{\thequestion.}}
\renewcommand{\partlabel}{(\thepartno)}
\renewcommand{\arraystretch}{1.3}
\setlength{\parindent}{0pt}
"""


def _question(p, num, space):
    title = esc(p.get("title", ""))
    out = [r"\par\begin{samepage}",
           rf"\question \textit{{[{title}]}}\hspace{{0.6em}}{p['statement']}"]
    if p.get("parts"):
        out.append(r"\begin{parts}")
        for part in p["parts"]:
            out.append(rf"\part {part}")
            if space != "0in":
                out.append(rf"\par\vspace*{{{space}}}")
        out.append(r"\end{parts}")
    elif space != "0in":
        out.append(rf"\par\vspace*{{{space}}}")
    out.append(r"\par\end{samepage}\penalty-100")
    return "\n".join(out)


def _std_box(std, L, show_pass):
    extra = (rf"\\[5pt]$\square$ {L['pass']}\qquad $\square$ {L['retake']}" if show_pass else "")
    return (r"\noindent\fbox{\parbox{\dimexpr\textwidth-2\fboxsep-2\fboxrule}{"
            rf"{{\large\textbf{{{esc(std['code'])} --- {esc(std['title'])}}}}}\\"
            rf"{{\small\itshape Active Calculus, {L['sec']} {esc(std['sections'])}}}\\[4pt]"
            rf"{esc(std['description'])}{extra}}}}}"
            "\n\\par\\vspace{8pt}\n")


def build_tex(handout, version="student"):
    """handout: dict with type, lang, course, instructions, work_space, teacher_key,
    and results = [{"std": ..., "problems": [...]}]. version: 'student' or 'teacher'."""
    lang, htype = handout["lang"], handout["type"]
    L = LABELS[lang]
    type_label = L[htype]
    teacher = version == "teacher"
    head_type = type_label
    results = [r for r in handout["results"] if r["problems"]]
    codes = ", ".join(r["std"]["code"] for r in results)
    course = esc(handout.get("course", "MAT 3A: Calculus 1"))
    space = WORK_SPACE.get(handout.get("work_space", "None"), "0in")
    pre = (PREAMBLE.replace("<<PDFTITLE>>", esc(f"{type_label} {codes}"))
           .replace("<<COURSE>>", course)
           .replace("<<PDFSUBJECT>>", esc("Learning standards " + codes))
           .replace("<<PDFLANG>>", "es-MX" if lang == "es" else "en-US")
           .replace("<<HEADTYPE>>", esc(head_type))
           .replace("<<TEACHERMARK>>", (r" $\cdot$ " + esc(L["teacher_short"])) if teacher else "")
           .replace("<<PAGE>>", L["page"]).replace("<<OF>>", L["of"]))
    body = [pre, r"\begin{document}", r"\binoppenalty=10000 \relpenalty=10000 \tolerance=1000 \emergencystretch=4em"]
    first = results[0]["std"]
    show_pass = htype in ("quest", "ticket")
    body.append(rf"\SetStandard{{{esc(first['code'])}}}{{{esc(first['title'])}}}")
    # Title line, like the S-14 Quest heading: "Quest -- S-14" centered
    title_line = esc(f"{type_label} -- {codes}")
    body.append(rf"\noindent\makebox[\linewidth][c]{{\Large\textbf{{{title_line}}}}}\par\vspace{{6pt}}")
    if teacher:
        body.append(rf"\begin{{center}}\fbox{{\textbf{{{esc(L['teacher_note'])}}}}}\end{{center}}")
    body.append(rf"\noindent {L['name']}: \underline{{\hspace{{2.4in}}}} \hfill {L['date']}: "
                rf"\underline{{\hspace{{1.0in}}}} \hfill {esc(handout.get('course_code', 'MAT 3A'))} {L['section']}: "
                rf"\underline{{\hspace{{0.7in}}}}" + "\n\\par\\vspace{8pt}")
    body.append(_std_box(first, L, show_pass))
    body.append(r"\noindent\begin{minipage}{\linewidth}" +
                rf"\textbf{{{L['instructions']}:}} {esc(handout.get('instructions', ''))}" +
                r"\par\end{minipage}\par\vspace{10pt}")
    num = 0
    letters = "ABC"
    for k, r in enumerate(results):
        std = r["std"]
        if k:
            body.append(r"\newpage")
            body.append(rf"\SetStandard{{{esc(std['code'])}}}{{{esc(std['title'])}}}")
            body.append(_std_box(std, L, show_pass))
        li = 0
        for qtype in QUESTION_TYPES:
            group = [p for p in r["problems"] if p["type"] == qtype]
            if not group:
                continue
            body.append(r"\needspace{7\baselineskip}")
            body.append(rf"\noindent{{\large\textbf{{{L['part']} {letters[li]}: {L[qtype]}}}}}"
                        rf"\quad{{\itshape {L[qtype + '_desc']}}}\par\nobreak\vspace{{4pt}}")
            li += 1
            body.append(r"\begin{questions}" + rf"\setcounter{{question}}{{{num}}}")
            for p in group:
                num += 1
                p["num"] = num
                body.append(_question(p, num, space))
            body.append(r"\end{questions}" + "\n\\vspace{6pt}")
    include_solutions = htype == "preparation" or teacher
    if include_solutions:
        heading = L["worked"] if htype == "preparation" else L["key"]
        for r in results:
            std = r["std"]
            body.append(r"\newpage")
            body.append(rf"\SetStandard{{{esc(std['code'])}}}{{{esc(std['title'])}}}")
            body.append(rf"\begin{{center}}{{\Large\bfseries {esc(heading)} --- {esc(std['code'])}}}\end{{center}}")
            for p in r["problems"]:
                body.append(r"\needspace{6\baselineskip}")
                body.append(rf"\noindent\textbf{{{L['problem']} {p['num']}.}} \textit{{[{esc(p['title'])}]}}"
                            rf"\hfill{{\small {esc(L[p['type']])} $\cdot$ {esc(p['subskill_code'])}}}\par\vspace{{2pt}}")
                body.append(p.get("solution", "") + "\n\\par\\vspace{3pt}")
                body.append(rf"\noindent\textbf{{{L['answer']}:}} {p.get('answer', '')}\par")
                body.append(r"\vspace{6pt}\noindent\rule{\linewidth}{0.3pt}\par\vspace{6pt}")
    body.append(r"\end{document}")
    return "\n".join(body) + "\n"


# ------------------------------------------------------------------
# Compiling
# ------------------------------------------------------------------
def find_pdflatex():
    cands = [shutil.which("pdflatex"), "/Library/TeX/texbin/pdflatex",
             "/opt/homebrew/bin/pdflatex", "/usr/local/bin/pdflatex"]
    cands += sorted(glob.glob("/usr/local/texlive/*/bin/*/pdflatex"), reverse=True)
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


def _error_excerpt(log):
    lines = log.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("!"):
            return "\n".join(lines[i:i + 8])
    return "\n".join(lines[-15:])


def compile_pdf(tex, runs=2, timeout=180):
    """Return (pdf_bytes or None, error_text)."""
    exe = find_pdflatex()
    if not exe:
        return None, ("pdflatex was not found. Install MacTeX (tug.org/mactex) or open the .tex "
                      "file in TeXstudio to make the PDF.")
    with tempfile.TemporaryDirectory() as d:
        src = pathlib.Path(d) / "handout.tex"
        src.write_text(tex, encoding="utf-8")
        env = os.environ.copy()
        env["PATH"] = str(pathlib.Path(exe).parent) + os.pathsep + env.get("PATH", "")
        rc = 1
        for _ in range(runs):
            try:
                proc = subprocess.run([exe, "-interaction=nonstopmode", "-halt-on-error", "handout.tex"],
                                      cwd=d, capture_output=True, timeout=timeout, env=env)
            except subprocess.TimeoutExpired:
                return None, "pdflatex timed out."
            rc = proc.returncode
            if rc:
                break
        pdf, logf = src.with_suffix(".pdf"), src.with_suffix(".log")
        log = logf.read_text(errors="replace") if logf.exists() else ""
        if rc == 0 and pdf.exists():
            return pdf.read_bytes(), ""
        return None, _error_excerpt(log)


def problem_compiles(p):
    """Compile one problem (statement, parts, answer, solution) in a minimal document."""
    std = {"code": p.get("subskill_code", "S"), "title": "check", "sections": "", "description": "",
           "subskills": []}
    handout = {"type": "preparation", "lang": "en", "course": "check", "instructions": "",
               "work_space": "None", "results": [{"std": std, "problems": [dict(p)]}]}
    pdf, err = compile_pdf(build_tex(handout), runs=1, timeout=60)
    return pdf is not None, err


# ------------------------------------------------------------------
# Saving
# ------------------------------------------------------------------
def base_name(handout, date_str):
    codes = "_".join(r["std"]["code"] for r in handout["results"] if r["problems"])
    kind = {"preparation": "Preparation", "quest": "Quest", "ticket": "Ticket"}[handout["type"]]
    return f"{date_str}_{kind}_{codes}_{handout['lang']}"


def save_files(folder_name, files):
    """files: {filename: bytes or str}. Saves into handouts/<folder_name>/ and returns the folder."""
    out = HANDOUTS_DIR / folder_name
    out.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        if data is None:
            continue
        path = out / name
        if isinstance(data, str):
            path.write_text(data, encoding="utf-8")
        else:
            path.write_bytes(data)
    return out
