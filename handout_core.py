# -*- coding: utf-8 -*-
"""
handout_core.py -- Canelita Handout Generator
Courses: MAT 3A Calculus 1 and MAT 5 Differential Equations (course-scoped S-codes).

Handout versions (Standards Based Quests requirements):
  Preparation          readiness check; the ONLY version with an answer key
  Quest 1, 2, 3        Pass/Retake row; Quest 2 and 3 add Attempt and
                       "Ticket Reassessment Completed"
  Reassessment Ticket  completed and brought on the day a student reassesses

Every problem is skill, conceptual, or interpretation, tied to a randomly
chosen subskill of the selected standard.

Pipeline for one handout:
  1. write the problems (Claude, with a calculator tool to check numbers)
  2. independent review (Claude, with the calculator): math, scope, realism
  3. targeted repair of confirmed errors, then re-review (bounded)
  4. LaTeX compile check and repair of any problem that doesn't typeset
  5. layout: Preparation answer space fitted to two question pages
  6. PDF (+ page images for preview)
No Streamlit code lives here.
"""
import ast
import glob
import json
import math
import os
import pathlib
import queue
import random
import re
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction

APP_DIR = pathlib.Path(__file__).resolve().parent
MODEL = "claude-sonnet-4-5"          # same model the tutor uses
MAX_TOKENS = 16000
MAX_CALC_ROUNDS = 3                  # calculator turns per Claude call (checks are batched)
MAX_REVIEW_ROUNDS = 2                # review -> repair cycles per handout

# ------------------------------------------------------------------
# Courses and standards
# ------------------------------------------------------------------
COURSES = {
    "calc1": {"code": "MAT 3A", "name": "Calculus 1", "textbook": "Active Calculus",
              "file": "handout_standards.json"},
    "diffeq": {"code": "MAT 5", "name": "Differential Equations", "textbook": "MyOpenMath",
               "file": "handout_standards_diffeq.json"},
}
# Course-specific scope reminders (on top of the general "this standard only" rule)
SCOPE_NOTES = {
    "calc1": {n: "Do not require the chain rule (taught in S-11)." for n in range(1, 11)},
    "diffeq": {},
}


def course_available(course):
    return (APP_DIR / COURSES[course]["file"]).exists()


def load_standards(course="calc1"):
    """Course catalog: list of {code, title, sections, description, subskills}."""
    return json.loads((APP_DIR / COURSES[course]["file"]).read_text(encoding="utf-8"))


# ------------------------------------------------------------------
# Versions, labels, instructions
# ------------------------------------------------------------------
QUESTION_TYPES = ["skill", "conceptual", "interpretation"]
VERSIONS = ["preparation", "quest1", "quest2", "quest3", "ticket"]
QUESTS = ("quest1", "quest2", "quest3")
DEFAULT_COUNTS = {"preparation": 3, "quest1": 2, "quest2": 2, "quest3": 2, "ticket": 3}
TITLE_ALIGN = {"preparation": "l", "ticket": "r"}          # Quests are centered
QUESTION_SPACE_IN = 1.0     # answer space after a question without parts (inches)
PART_SPACE_IN = 0.5         # answer space after each lettered part (inches)

LABELS = {
    "en": {
        "preparation": "Preparation", "quest1": "Quest 1", "quest2": "Quest 2",
        "quest3": "Quest 3", "ticket": "Reassessment Ticket",
        "skill": "Skill", "conceptual": "Conceptual", "interpretation": "Interpretation",
        "skill_desc": "Carry out the computation or procedure.",
        "conceptual_desc": "Explain the idea behind the mathematics.",
        "interpretation_desc": "Explain what the mathematics means in context.",
        "tag_skill": "S", "tag_conceptual": "C", "tag_interpretation": "I",
        "part": "Part", "name": "Name", "date": "Date", "section": "Section",
        "instructions": "Instructions", "page": "Page", "of": "of",
        "pass": "Pass", "retake": "Retake", "attempt": "Attempt",
        "ticket_done": "Ticket Reassessment Completed",
        "key": "Answer Key", "problem": "Problem", "answer": "Answer", "sec": "Sec.",
    },
    "es": {
        "preparation": "Preparación", "quest1": "Quest 1", "quest2": "Quest 2",
        "quest3": "Quest 3", "ticket": "Ticket de reevaluación",
        "skill": "Habilidad", "conceptual": "Conceptual", "interpretation": "Interpretación",
        "skill_desc": "Realiza el cálculo o el procedimiento.",
        "conceptual_desc": "Explica la idea detrás de las matemáticas.",
        "interpretation_desc": "Explica qué significan las matemáticas en el contexto.",
        "tag_skill": "H", "tag_conceptual": "C", "tag_interpretation": "I",
        "part": "Parte", "name": "Nombre", "date": "Fecha", "section": "Sección",
        "instructions": "Instrucciones", "page": "Página", "of": "de",
        "pass": "Aprobado", "retake": "Repetir", "attempt": "Intento",
        "ticket_done": "Ticket de reevaluación completado",
        "key": "Clave de respuestas", "problem": "Problema", "answer": "Respuesta", "sec": "Secc.",
    },
}

INSTRUCTIONS = {
    ("en", "quest"): (
        "To give you credit, I need to see how you think through each problem; that lets me "
        "assess your understanding fairly and give you useful feedback. Show all of your work "
        "and box your final answers. Give exact values unless a problem asks you to round. "
        "Answer application questions in complete sentences with appropriate units. Write your "
        "name, the assessment title, and the corresponding question numbers on any separate "
        "pages you submit."),
    ("en", "preparation"): (
        "This Preparation is a readiness check. Work each problem on your own first, then "
        "compare your work with the answer key at the end. Use what you find to decide what to "
        "study, so you can make the most of your assessment days. Show all of your work and box "
        "your final answers."),
    ("en", "ticket"): (
        "Complete this Reassessment Ticket and bring it with you on the day you plan to "
        "reassess. Show all of your work, box your final answers, and give exact values unless "
        "a problem asks you to round."),
    ("es", "quest"): (
        "Para darte crédito, necesito ver cómo razonas en cada problema; así puedo evaluar tu "
        "comprensión de manera justa y darte comentarios útiles. Muestra todo tu trabajo y "
        "encierra tus respuestas finales en un recuadro. Da valores exactos a menos que el "
        "problema pida redondear. Responde las preguntas de aplicación con oraciones completas "
        "y unidades apropiadas. Escribe tu nombre, el título de la evaluación y los números de "
        "las preguntas en cualquier hoja adicional que entregues."),
    ("es", "preparation"): (
        "Esta Preparación es una revisión de tu preparación. Primero resuelve cada problema por "
        "tu cuenta y después compara tu trabajo con la clave de respuestas al final. Usa lo que "
        "descubras para decidir qué estudiar y aprovechar al máximo tus días de evaluación. "
        "Muestra todo tu trabajo y encierra tus respuestas finales en un recuadro."),
    ("es", "ticket"): (
        "Completa este Ticket de reevaluación y tráelo el día en que planeas reevaluarte. "
        "Muestra todo tu trabajo, encierra tus respuestas finales en un recuadro y da valores "
        "exactos a menos que el problema pida redondear."),
}


def kind(version):
    return "quest" if version in QUESTS else version


def default_instructions(lang, version):
    return INSTRUCTIONS[(lang, kind(version))]


# ------------------------------------------------------------------
# Planning: which subskill (and application context) each problem targets
# ------------------------------------------------------------------
CONTEXT_FAMILIES = [
    "college life (campus services, transportation, events, or student budgets)",
    "a fictional social-media, streaming, or app scenario",
    "STEM careers (engineering, ecology, medicine, data science, or renewable energy)",
    "work and community on California's Central Coast (agriculture, small business, health care, or public services)",
    "community-centered math (a community garden, a local clinic, public-transit access, air- or water-quality monitoring, a family business) where people use math to make decisions that benefit their community",
]

# Names from many cultures and genders, used only when a problem needs a person.
NAME_POOL = [
    "Ximena", "Mateo", "Valeria", "Diego", "Camila", "Joaquín", "Lucía", "Andrés", "Itzel", "Marisol",
    "Jada", "Malik", "Imani", "Darius", "Amara", "Kwame", "Zainab", "Tariq",
    "Mei", "Kenji", "Ji-woo", "Minh", "Linh", "Hiroshi", "Priya", "Arjun", "Anika", "Rohan",
    "Layla", "Omar", "Yasmin", "Karim", "Leilani", "Kai", "Malia", "Tavita",
    "Andrea", "Jomar", "Rizalyn", "Emma", "Owen", "Hannah", "Liam", "Nadia", "Sofía", "Elijah",
    "Alex", "Jordan", "Sam", "River", "Taylor",
]


def pick_names(rng=random, k=4):
    return rng.sample(NAME_POOL, k)


def plan_problems(std, counts, rng=random):
    """Pick subskills at random for each question type; within a type they
    don't repeat until every subskill has been used."""
    if isinstance(counts, int):  # "n of each type"
        counts = {t: counts for t in QUESTION_TYPES}
    slots, n_sub = [], len(std["subskills"])
    contexts = CONTEXT_FAMILIES[:]
    rng.shuffle(contexts)
    ctx_i = 0
    for qtype in QUESTION_TYPES:
        n, picks = int(counts.get(qtype, 0)), []
        while len(picks) < n:
            batch = list(range(n_sub))
            rng.shuffle(batch)
            picks.extend(batch)
        for i in sorted(picks[:n]):
            slot = {"type": qtype, "subskill_code": f"{std['code']}.{i + 1}",
                    "subskill": std["subskills"][i]}
            if qtype == "interpretation":
                slot["context"] = contexts[ctx_i % len(contexts)]
                ctx_i += 1
            slots.append(slot)
    for k, s in enumerate(slots, 1):
        s["id"] = k
    return slots


# ------------------------------------------------------------------
# Calculator tool (restricted arithmetic evaluator)
# ------------------------------------------------------------------
CALC_TOOL = {
    "name": "calculator",
    "description": (
        "Evaluate arithmetic. Exact for fractions and decimals; numeric for functions. "
        "Put several expressions on separate lines or separate them with semicolons. "
        "You may assign variables (t=8; 2*t**3-15*t**2+24*t+5). Supports + - * / ** ^ ( ), "
        "sqrt, exp, ln, log (natural), log10, sin, cos, tan, asin, acos, atan, sinh, cosh, "
        "abs, floor, ceil, round, pi, e."),
    "input_schema": {"type": "object",
                     "properties": {"expressions": {"type": "string"}},
                     "required": ["expressions"]},
}
_FUNCS = {"sqrt": math.sqrt, "exp": math.exp, "ln": math.log, "log": math.log,
          "log10": math.log10, "sin": math.sin, "cos": math.cos, "tan": math.tan,
          "asin": math.asin, "acos": math.acos, "atan": math.atan, "sinh": math.sinh,
          "cosh": math.cosh, "abs": abs, "floor": math.floor, "ceil": math.ceil, "round": round}
_CONSTS = {"pi": math.pi, "e": math.e}


def _num(v):
    if isinstance(v, Fraction) and (abs(v.numerator).bit_length() > 4000 or v.denominator.bit_length() > 4000):
        return float(v)
    return v


def _ev(node, env):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return Fraction(node.value) if isinstance(node.value, int) else Fraction(repr(node.value))
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        if node.id in _CONSTS:
            return _CONSTS[node.id]
        raise ValueError(f"unknown name {node.id}")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        v = _ev(node.operand, env)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp):
        a, b = _ev(node.left, env), _ev(node.right, env)
        op = node.op
        if isinstance(op, ast.Add):
            return _num(a + b)
        if isinstance(op, ast.Sub):
            return _num(a - b)
        if isinstance(op, ast.Mult):
            return _num(a * b)
        if isinstance(op, ast.Div):
            if b == 0:
                raise ZeroDivisionError("division by zero")
            return _num(a / b)
        if isinstance(op, ast.Mod):
            return _num(a % b)
        if isinstance(op, ast.Pow):
            if isinstance(a, Fraction) and isinstance(b, Fraction) and b.denominator == 1 and abs(b) <= 200:
                if a == 0 and b < 0:
                    raise ZeroDivisionError("0 to a negative power")
                return _num(a ** int(b))
            fa, fb = float(a), float(b)
            if abs(fb) > 1000:
                raise ValueError("exponent too large")
            r = fa ** fb
            if isinstance(r, complex):
                raise ValueError("result is not a real number")
            return r
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
        args = [float(_ev(a, env)) for a in node.args]
        return _FUNCS[node.func.id](*args)
    raise ValueError("unsupported expression")


def _fmt(v):
    if isinstance(v, Fraction):
        if v.denominator == 1:
            return str(v.numerator)
        return f"{v.numerator}/{v.denominator} ≈ {float(v):.10g}"
    return f"{v:.10g}"


def calculate(text):
    env, out = {}, []
    for expr in re.split(r"[;\n]", str(text))[:80]:
        expr = expr.strip()
        if not expr:
            continue
        shown = expr
        try:
            if len(expr) > 400:
                raise ValueError("expression too long")
            expr = expr.replace("^", "**").replace("\u2212", "-").replace("\u00b7", "*")
            stmt = ast.parse(expr, mode="exec").body[0]
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                val = _ev(stmt.value, env)
                env[stmt.targets[0].id] = val
            elif isinstance(stmt, ast.Expr):
                val = _ev(stmt.value, env)
            else:
                raise ValueError("unsupported statement")
            out.append(f"{shown} = {_fmt(val)}")
        except Exception as exc:  # noqa: BLE001 -- report to the model, don't crash
            out.append(f"{shown} -> error: {exc}")
    return "\n".join(out) or "no expressions"


def _blocks_to_dicts(content):
    out = []
    for b in content:
        if b.type == "text":
            out.append({"type": "text", "text": b.text})
        elif b.type == "tool_use":
            out.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
    return out


def call_claude(client, prompt, max_tokens=MAX_TOKENS, calculator=True):
    """One bounded conversation. With the calculator, Claude may check numbers for up
    to MAX_CALC_ROUNDS turns; the last turn must produce text. Completed calculator
    work is kept if the reply comes back empty. Returns (text, stop_reason)."""
    messages = [{"role": "user", "content": prompt}]
    nudged = False
    if hasattr(client, "with_options"):  # wait and retry on rate limits instead of failing
        client = client.with_options(max_retries=6)
    for rnd in range(MAX_CALC_ROUNDS + 2):
        kwargs = {"model": MODEL, "max_tokens": max_tokens, "messages": messages}
        if calculator:
            kwargs["tools"] = [CALC_TOOL]
            if rnd >= MAX_CALC_ROUNDS:
                kwargs["tool_choice"] = {"type": "none"}
        resp = client.messages.create(**kwargs)
        messages.append({"role": "assistant", "content": _blocks_to_dicts(resp.content)})
        if resp.stop_reason == "tool_use":
            results = [{"type": "tool_result", "tool_use_id": b.id,
                        "content": calculate((b.input or {}).get("expressions", ""))}
                       for b in resp.content if b.type == "tool_use"]
            messages.append({"role": "user", "content": results})
            continue
        text = "".join(b.text for b in resp.content if b.type == "text")
        if text.strip() or nudged:
            return text, resp.stop_reason
        nudged = True  # empty reply: keep the calculator work and ask for the output
        messages.append({"role": "user", "content": "Now write the final output in the required format."})
    return "", "max_rounds"


# ------------------------------------------------------------------
# Prompts
# ------------------------------------------------------------------
HANDOUT_PURPOSE = {
    "preparation": ("a PREPARATION: a readiness check students complete before the Quest. "
                    "Students receive the answer key, so every solution must be complete, step by "
                    "step, and written to teach."),
    "quest": ("a QUEST: an in-class assessment of the standard. Problems must be fair, "
              "unambiguous, and at the level of a typical exam question, with no trick questions. "
              "No key is printed; solutions are kept only for checking."),
    "ticket": ("a REASSESSMENT TICKET: work students complete and bring on the day they "
               "reassess. Same difficulty as a Quest, with fresh functions, numbers, and contexts."),
}

TYPE_GUIDE = {
    "skill": ("SKILL: carry out the computation or procedure the subskill names (evaluate, "
              "differentiate, solve, set up). It has a definite final answer."),
    "conceptual": ("CONCEPTUAL: test understanding of why or what, not only how. For example: "
                   "explain a definition or theorem in your own words, decide true or false and "
                   "justify, find and fix an error in sample student work, compare two ideas, or "
                   "predict a result without computing. It has a clear expected answer that can "
                   "be graded. When showing a classmate's mistake, frame it respectfully as part of learning."),
    "interpretation": ("INTERPRETATION: a realistic application. Students compute and then explain "
                       "what a result means: units, the meaning of a sign or value in context, "
                       "information read from a table or graph, or whether a result is "
                       "reasonable. Ask for interpretations in complete sentences with units."),
}

QUALITY_RULES = r"""QUESTION CONSTRUCTION
- Assess only the selected standard. Earlier standards may be used as prerequisites. Later standards must never become the assessment target or a required solution method, unless this standard cannot be done without that technique.
- Give shared information once, in the question stem. Put each distinct task in its own lettered part.
- Keep rounding and units reminders with the calculation they apply to.
- Do not repeat rules, formulas, definitions, or interpretation requests across parts.
- If students must state a rule or formula, do not give it away in the question.
- Do not supply unnecessary precomputed values when a function is given; ask students to evaluate and interpret instead.
- Keep complete equations together. Display long equations instead of splitting an equality or fraction across text lines.

CULTURALLY RELEVANT AND AFFIRMING (very important; follows Hartnell College's Equity-Minded Rubric)
- Connect each application to the lived experiences, jobs, families, communities, and career goals of California community college students, many of them Latine, first-generation, multilingual, working, commuting, and caring for family. Show these realities with respect and agency, never as hardships to pity.
- Asset-based framing: show people using their strengths (bilingual skills, family knowledge, community networks, work experience, persistence) and making decisions. No deficit narratives: never make poverty, debt trouble, immigration or citizenship status, crime, disability, mental health, body size, or housing insecurity the "story" of a problem.
- Representation: when a problem needs a person, use one of the names provided for this handout (at most once each; many problems need no named person). Across the handout, show women, men, and nonbinary people (they/them is fine) of many backgrounds as engineers, scientists, nurses, farmers, business owners, data analysts, and students. Show varied families and multilingual people naturally, without making identity the topic.
- Never tie a name or culture to a stereotyped job, food, accent, income level, or behavior. Avoid language that triggers stereotype threat, such as suggesting a group is "bad at math."
- Mistakes are part of learning: when a problem shows a classmate's work with an error, frame it respectfully ("Jordan's first attempt...") and ask students to help improve it; never mock or shame the person.
- Use communal, inclusive language where natural (we, our community). Contexts may highlight how math helps communities make fair, informed decisions; keep the focus on agency and solutions.
- Avoid upsetting or exclusionary topics: violence, weapons, policing, gambling, alcohol or drugs, dieting or weight loss, injuries, disasters with casualties, and hobbies that assume wealth (yachts, golf, skiing, luxury travel).
- A student should not need specialized cultural, sports, or insider knowledge to understand the situation.

COMMON-SENSE NUMBERS (very important)
- Before writing any money or quantity, estimate its everyday ballpark, then make sure the given values and every result fall in that range.
- Money must be predictable with common sense: realistic current California prices, wages, fees, and revenues for the situation (a concert ticket brings in tens of dollars, not thousands; a campus coffee costs a few dollars). Marginal revenue or cost per item must be close to a realistic price for one item.
- Counts of people or objects are whole numbers; speeds, temperatures, times, distances, concentrations, and growth rates stay within real-world ranges for the situation.
- A student who estimates first should be able to predict roughly what the answer will be.

APPLICATIONS AND REALISM (realism is part of correctness)
- Vary contexts. Use the context family assigned to each interpretation slot. Never use a phone-battery scenario.
- Contexts are fictional. Do not claim a model describes real platform earnings, current trends, or real measurements. No real people or brand names.
- State sensible units and a plausible working domain. Keep scenario duration, time units, and the mathematical domain consistent.
- Check magnitudes, signs, rates, endpoints, and interior extrema. Revenue, counts, concentrations, and other nonnegative levels must stay nonnegative on the working domain. Negative rates can be valid; distinguish levels from rates, and revenue from profit or loss.
- Explain any jump with a credible mechanism (a fee policy, a discrete transfer, a sensor recalibration). Never invent unexplained physical jumps.
- Do not move numerical constants into an unrelated context or unit system.

ROUNDING AND UNITS
- Keep full precision during calculations. Round only final requested approximations, to three decimal places unless the problem says otherwise; money to the nearest cent.
- Respect exact-answer requests and any precision a problem specifies.
- Do not attach physical units to a dimensionless answer.

GRAPHS (only when the standard calls for one: average velocity from a position graph, tangent lines on the same grid as the function, increasing/decreasing, concavity, extrema, slope fields, phase lines or planes)
- Draw the actual figure with readable scales, axis labels with units, the relevant domain endpoints, and open or closed points where needed.
- Never pre-draw what the student is asked to construct (for example, the requested tangent line).
- Use enough plotted points and grid bounds that include all of the curve; never cut off curve data or endpoints.
- A later part may reuse a graph given earlier in the same question.

NUMBERS
Use the calculator to check every number before you write it: givens printed in the statement, table entries, graph coordinates, function and derivative values, tangent points and line endpoints, zeros and the sign on every relevant subinterval, and every answer. Put ALL of your checks in ONE calculator call (one expression per line); make a second call only if a check fails."""

FORMAT_RULES = r"""LATEX FORMAT (inside the tags)
- It is pasted into a LaTeX exam-class document that loads amsmath, amssymb, and pgfplots. Do not use any other package or define new commands.
- Inline math: $...$. Displayed math: \[ ... \]. Never use $$, \( \), or numbered equation environments; for multi-line work use \begin{aligned} inside \[ \].
- Keep inline math short so it never breaks across lines; put any formula longer than about 25 characters in displayed math.
- Use LaTeX commands for every math symbol (\le, \infty, \pi, \to, \cdot, \sqrt{}). Text is plain ASCII<<ACCENTS>>. No Unicode math symbols, no curly quotes.
- Write a literal dollar sign as \$ and a percent sign as \%.
- Do not use \section, \question, \part, \begin{parts}, \newpage, \vspace, markdown, or bullet characters.
- Use 0 to 4 <part> tags. Do not write (a), (b) labels yourself; they are added automatically.
- Tables: \begin{center}\begin{tabular}{|c|c|c|} with \hline rules, header row first\end{tabular}\end{center}.
- Graphs: pgfplots inside \begin{center}...\end{center}, for example
  \begin{tikzpicture}\begin{axis}[width=7cm, height=5cm, axis lines=middle, xlabel={$t$ (s)}, ylabel={$s$ (m)}, xmin=0, xmax=6, ymin=0, ymax=40, grid=both]\addplot[thick, domain=0:6, samples=100]{t^2+2*t};\addplot[only marks, mark=*] coordinates {(0,0) (6,48)};\end{axis}\end{tikzpicture}
  Use mark=o for an open point. Right after every graph add one sentence that begins "Graph description:" and describes it in words for students who cannot see it.
- In <answer>, give only the final results, labeled (a), (b), ... when there are parts. Do not use \boxed.
- In <solution>, show every step with short explanations between steps."""

BLOCK_FORMAT = """<problem id="1">
<title>short italic label naming the subskill (2 to 6 words, no math); leave it empty when the statement is already self-explanatory</title>
<statement>problem stem in LaTeX</statement>
<part>first task</part>
<part>second task</part>
<answer>final answer(s)</answer>
<solution>complete worked solution</solution>
</problem>"""


def _rules(lang):
    acc = " plus Spanish accented letters and inverted punctuation" if lang == "es" else ""
    return QUALITY_RULES + "\n\n" + FORMAT_RULES.replace("<<ACCENTS>>", acc)


def _scope(course, std, catalog):
    codes = [s["code"] for s in catalog]
    i = codes.index(std["code"]) if std["code"] in codes else -1
    later = "; ".join(f"{s['code']} {s['title']}" for s in catalog[i + 1:]) if i >= 0 else ""
    note = SCOPE_NOTES.get(course, {}).get(int(std["code"].split("-")[1]), "")
    text = f"Later standards in this course (not assessment targets here): {later or 'none'}."
    return text + (f" {note}" if note else "")


def _std_context(course, std):
    c = COURSES[course]
    subs = "\n".join(f"  {std['code']}.{i}: {s}" for i, s in enumerate(std["subskills"], 1))
    return (f"Course: {c['code']} {c['name']} (California community college; {c['textbook']}).\n"
            f"Learning standard {std['code']} -- {std['title']} (Sec. {std['sections']})\n"
            f"Description: {std['description']}\nSubskills:\n{subs}")


def build_prompt(course, std, catalog, slots, lang, version, avoid=None, others=None, names=None,
                 new_function_type=False):
    language = ("Write every problem, part, answer, and solution in Spanish (as spoken in a "
                "California community college classroom), with standard math notation."
                if lang == "es" else "Write in English.")
    lines = []
    for s in slots:
        line = f'{s["id"]}. type: {s["type"].upper()}; subskill {s["subskill_code"]} -- {s["subskill"]}'
        if s.get("context"):
            line += f"; context family: {s['context']}"
        if s.get("note"):
            line += f"; the instructor asks for: {s['note']}"
        lines.append(line)
    types_used = sorted({s["type"] for s in slots}, key=QUESTION_TYPES.index)
    avoid_text = (f"\nWrite a different problem from this earlier version (new function, numbers, and "
                  f"context):\n{avoid}\n" if avoid else "")
    if new_function_type and avoid:
        avoid_text += ("Assess the same skill with a DIFFERENT TYPE of function than the earlier version "
                       "(for example polynomial -> rational, exponential, trigonometric, radical, or "
                       "logarithmic, whichever types this standard and the earlier standards allow).\n")
    if names:
        avoid_text += f"\nNames available for this handout (use only if a person is needed): {', '.join(names)}.\n"
    if others:
        avoid_text += ("\nOther problems on this handout are written separately and cover: "
                       + "; ".join(f"{o['type']} on {o['subskill_code']}" for o in others)
                       + ". Choose functions, numbers, and contexts that a typical version of those "
                         "problems would not use, so the handout doesn't repeat itself.\n")
    return f"""You are an experienced mathematics professor writing problems for {HANDOUT_PURPOSE[kind(version)]}

{_std_context(course, std)}
{_scope(course, std, catalog)}

Question types:
{chr(10).join('- ' + TYPE_GUIDE[t] for t in types_used)}

Write exactly {len(slots)} problem(s), one per slot, in this order. Each problem must assess its assigned subskill and be of its assigned type. Vary functions, numbers, and contexts so no two problems feel alike.
{chr(10).join(lines)}
{avoid_text}
{language}

First use the calculator to check your numbers. Then return only the problem blocks, in this exact format, using the slot number as the id:
{BLOCK_FORMAT}

{_rules(lang)}"""


# ------------------------------------------------------------------
# Parsing and cleanup
# ------------------------------------------------------------------
BLOCK_RE = re.compile(r'<problem\s+id\s*=\s*"?(\d+)"?\s*>(.*?)</problem>', re.S)
UNICODE_MAP = {
    "\u2018": "`", "\u2019": "'", "\u201c": "``", "\u201d": "''", "\u2014": "---", "\u2013": "--",
    "\u2212": "-", "\u2032": "'", "\u2033": "''", "\u00a0": " ", "\u2026": "...",
    "\u2264": r"\ensuremath{\le}", "\u2265": r"\ensuremath{\ge}", "\u2260": r"\ensuremath{\neq}",
    "\u221e": r"\ensuremath{\infty}", "\u2192": r"\ensuremath{\to}", "\u00d7": r"\ensuremath{\times}",
    "\u00b7": r"\ensuremath{\cdot}", "\u22c5": r"\ensuremath{\cdot}", "\u03c0": r"\ensuremath{\pi}",
    "\u0394": r"\ensuremath{\Delta}", "\u03b8": r"\ensuremath{\theta}", "\u00b1": r"\ensuremath{\pm}",
    "\u2248": r"\ensuremath{\approx}", "\u00b0": r"\ensuremath{^\circ}", "\u221a": r"\ensuremath{\surd}",
    "\u222b": r"\ensuremath{\int}", "\u00b2": r"\ensuremath{^2}", "\u00b3": r"\ensuremath{^3}",
    "\u2211": r"\ensuremath{\sum}", "\u03bb": r"\ensuremath{\lambda}", "\u03c9": r"\ensuremath{\omega}",
}
FORBIDDEN_RE = re.compile(r"\\(newpage|clearpage|pagebreak|vspace\*?\s*\{[^}]*\}|section\*?\s*\{[^}]*\})")


def _tag(body, name):
    m = re.search(rf"<{name}>(.*?)</{name}>", body, re.S)
    return m.group(1).strip() if m else ""


def clean_latex(text):
    """Normalize harmless syntax so valid math typesets; never rewrites the mathematics."""
    warnings = []
    if not text:
        return text, warnings
    for u, r in UNICODE_MAP.items():
        text = text.replace(u, r)
    text = re.sub(r"\$\$(.+?)\$\$", r"\\[\1\\]", text, flags=re.S)
    text = re.sub(r"\\\((.+?)\\\)", r"$\1$", text, flags=re.S)
    text = FORBIDDEN_RE.sub("", text)
    for bad in (r"\question", r"\begin{parts}", r"\end{parts}", r"\begin{questions}", r"\end{questions}"):
        if bad in text:
            warnings.append(f"removed {bad}")
            text = text.replace(bad, "")
    text = re.sub(r"\\part\b(?!ial)", "", text)
    odd = sorted({c for c in text if ord(c) > 255})
    if odd:
        warnings.append("replaced unsupported characters: " + " ".join(odd))
        text = "".join("?" if ord(c) > 255 else c for c in text)
    if len(re.findall(r"(?<!\\)\$", text)) % 2:
        warnings.append("unbalanced $ signs")
    if text.count("{") - text.count(r"\{") != text.count("}") - text.count(r"\}"):
        warnings.append("unbalanced braces")
    return text, warnings


def parse_problems(text, slots):
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
        if not p["title"]:  # tolerate an unclosed <title>; an empty title means "no label"
            m = re.search(r"<title>([^<\n]*)\n", body)
            p["title"] = m.group(1).strip() if m else ""
        p["title"] = re.sub(r"[$\\{}]", "", p["title"])[:60]
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


def block_text(p, pid=None):
    parts = "".join(f"<part>{x}</part>\n" for x in p.get("parts", []))
    return (f'<problem id="{pid or p["id"]}">\n<title>{p.get("title", "")}</title>\n'
            f'<statement>{p["statement"]}</statement>\n{parts}<answer>{p.get("answer", "")}</answer>\n'
            f'<solution>{p.get("solution", "")}</solution>\n</problem>')


def _slot(p, pid=1):
    s = {k: p[k] for k in ("type", "subskill_code", "subskill") if k in p}
    if p.get("context"):
        s["context"] = p["context"]
    s["id"] = pid
    return s


# ------------------------------------------------------------------
# Independent review and repair
# ------------------------------------------------------------------
FINDING_RE = re.compile(r'<finding\s+problem\s*=\s*"?(\d+)"?\s+verdict\s*=\s*"?([a-z_]+)"?\s*>(.*?)</finding>', re.S)


def build_review_prompt(course, std, catalog, problems):
    blocks = "\n\n".join(
        f"[Problem {p['id']}: {p['type']}, subskill {p['subskill_code']} -- {p['subskill']}]\n{block_text(p)}"
        for p in problems)
    return f"""You are an independent reviewer checking problems before they go to students. You did not write them.

{_std_context(course, std)}
{_scope(course, std, catalog)}

For EVERY problem, check:
1. Every number: givens printed in the statement, table entries, graph coordinates, function and derivative values, tangent points, zeros and the sign on each relevant subinterval, every step of the solution, and the final answer. Recompute them with the calculator.
2. The answer and solution are correct and complete, and each part can be answered from the information given.
3. Scope: it assesses this standard and its assigned subskill and type, and does not require a later standard's method.
4. Realism: sensible units and domain, plausible magnitudes and signs, nonnegative levels stay nonnegative, levels vs. rates and revenue vs. profit are distinguished, any jump has a credible mechanism, consistent time units.
5. Wording: tasks agree with the results (for example, no "explain the negative sign" when the value is zero), no contradictions, no repeated formulas or giveaways.
6. Common sense: estimate the everyday ballpark of every money amount and quantity yourself and compare. A value far outside what a person would expect (for example, thousands of dollars of marginal revenue for one concert ticket) is a confirmed_error, even if the algebra is right.
7. Culturally relevant and affirming (Hartnell College Equity-Minded Rubric): the context connects to community college students' lives and is framed with assets and agency; people and names are not stereotyped or homogeneous; no deficit framing, stereotype-threat language, shaming of mistakes, or upsetting or wealth-assuming topics. Report violations as confirmed_error, saying what to change.

Put all of your recomputations in ONE calculator call (one expression per line); make a second call only to confirm a suspected error. Before you call something an error, verify it with the calculator. A proposed root must be checked by substitution, and signs tested on both sides. A task can legitimately have several sign intervals. If your check shows the work is correct, report verified_correct, not an error.

Return only findings, at least one per problem, in this format:
<finding problem="N" verdict="confirmed_error">what is wrong, exactly where, and the corrected value or fix</finding>
<finding problem="N" verdict="verified_correct">what you checked</finding>
<finding problem="N" verdict="nonblocking_note">optional minor suggestion</finding>

Problems:
{blocks}"""


def parse_findings(text):
    out = {}
    for pid, verdict, body in FINDING_RE.findall(text):
        out.setdefault(int(pid), []).append({"verdict": verdict, "text": " ".join(body.split())})
    return out


def build_repair_prompt(course, std, catalog, problems, findings, lang, version):
    items = []
    for p in problems:
        errs = "\n".join(f"- {f['text']}" for f in findings.get(p["id"], []) if f["verdict"] == "confirmed_error")
        items.append(f"Confirmed errors for problem {p['id']} ({p['type']}, subskill {p['subskill_code']}"
                     f"{', context family: ' + p['context'] if p.get('context') else ''}):\n{errs}\n\n{block_text(p)}")
    return f"""An independent review found confirmed errors in these problems for {HANDOUT_PURPOSE[kind(version)]}

{_std_context(course, std)}
{_scope(course, std, catalog)}

Rewrite each problem below so every confirmed error is fixed:
- Correct a wrong number everywhere it appears: statement, tables, graphs, answer, and solution.
- Update any wording that depends on a changed result (a sign, a zero, a maximum).
- If an application model is unrealistic, replace the whole application, including all of its parts, graphs, and answers. Never keep an unrealistic model only because its algebra works.
- Keep the same type and subskill. Keep everything that was already correct.
- Use the calculator to check every number.
{"Write in Spanish." if lang == "es" else "Write in English."}

Return only the corrected problem blocks, with the same ids, in the same format.

{chr(10).join(items)}

{_rules(lang)}"""


def review_and_repair(client, course, std, catalog, problems, lang, version, report=lambda s: None):
    """Independent review, then targeted repair of confirmed errors (bounded).
    Returns (problems, summary dict)."""
    summary = {"checked": len(problems), "fixed": 0, "unresolved": 0, "notes": []}
    to_review = list(problems)
    for rnd in range(MAX_REVIEW_ROUNDS):
        report("Checking the math" if rnd == 0 else "Re-checking the fixes")
        findings = {}
        for text, _ in _parallel(lambda g: call_claude(client, build_review_prompt(course, std, catalog, g)),
                                 _type_groups(to_review)):
            findings.update(parse_findings(text))
        bad = [p for p in to_review
               if any(f["verdict"] == "confirmed_error" for f in findings.get(p["id"], []))]
        for p in to_review:
            p["review"] = findings.get(p["id"], [])
        if not bad:
            return problems, summary
        if rnd == MAX_REVIEW_ROUNDS - 1:
            break
        report(f"Fixing {len(bad)} problem(s)")

        def repair(group):
            text, _ = call_claude(client, build_repair_prompt(course, std, catalog, group, findings, lang, version))
            return parse_problems(text, [_slot(p, p["id"]) for p in group])[0]
        by_id = {f["id"]: f for got in _parallel(repair, _type_groups(bad)) for f in got}
        for p in bad:
            if p["id"] in by_id:
                new = by_id[p["id"]]
                new["repaired_from"] = [f["text"] for f in findings[p["id"]] if f["verdict"] == "confirmed_error"]
                problems[problems.index(p)] = new
                summary["fixed"] += 1
        to_review = [problems[i] for i, p in enumerate(problems) if p.get("repaired_from") and p["id"] in by_id]
    for p in problems:
        errs = [f["text"] for f in p.get("review", []) if f["verdict"] == "confirmed_error"]
        if errs:
            summary["unresolved"] += 1
            p.setdefault("warnings", []).append("Review still reports: " + errs[0][:300])
    return problems, summary


# ------------------------------------------------------------------
# Generation
# ------------------------------------------------------------------
def _parallel(fn, items, workers=3):
    """Run fn over items in threads (Claude calls are network-bound)."""
    if len(items) <= 1:
        return [fn(x) for x in items]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(fn, items))


def _type_groups(items):
    return [g for g in ([x for x in items if x["type"] == t] for t in QUESTION_TYPES) if g]
def generate_version(client, course, std, catalog, version, counts, lang, report=lambda s: None, rng=random):
    """Write, review, repair, and compile-check one handout version."""
    slots = plan_problems(std, counts, rng)
    names = pick_names(rng)
    notes, timings = [], {}
    t0 = time.time()
    report("Writing problems")

    def write(group):
        others = [s for s in slots if s not in group]
        text, _ = call_claude(client, build_prompt(course, std, catalog, group, lang, version, others=others,
                                                   names=names))
        got, missing = parse_problems(text, group)
        if missing:  # one more try for anything that didn't come back
            text2, _ = call_claude(client, build_prompt(course, std, catalog, missing, lang, version,
                                                        others=others, names=names))
            extra, missing = parse_problems(text2, missing)
            got += extra
        return got, missing

    problems, still = [], []
    for got, missing in _parallel(write, _type_groups(slots)):
        problems += got
        still += missing
    problems.sort(key=lambda p: p["id"])
    if still:
        notes.append(f"{len(still)} problem(s) could not be written; generate again or lower the count.")
    timings["writing"] = time.time() - t0
    if not problems:
        raise RuntimeError("Claude returned no problems. Nothing was saved; please try again.")
    t1 = time.time()
    problems, summary = review_and_repair(client, course, std, catalog, problems, lang, version, report)
    timings["review"] = time.time() - t1
    if find_pdflatex():
        t2 = time.time()
        report("Typesetting")
        problems = repair_latex(client, course, std, catalog, problems, lang, version, notes)
        timings["typesetting"] = time.time() - t2
    return {"course": course, "std": std, "version": version, "lang": lang,
            "problems": problems, "notes": notes, "review": summary, "timings": timings}


def _write_one(client, course, std, catalog, slot, lang, version, avoid, new_function_type=False,
               others=None):
    text, _ = call_claude(client, build_prompt(course, std, catalog, [slot], lang, version, avoid=avoid,
                                               names=pick_names(), new_function_type=new_function_type,
                                               others=others),
                          max_tokens=8000)
    new, _ = parse_problems(text, [slot])
    if not new:
        raise RuntimeError("Claude did not return a problem. Try again.")
    new[0]["id"] = 1
    p = review_and_repair(client, course, std, catalog, new, lang, version)[0][0]
    if find_pdflatex():
        p = repair_latex(client, course, std, catalog, [p], lang, version, [])[0]
    return p


def regenerate_problem(client, course, std, catalog, problem, lang, version):
    """Replace one problem: same type and subskill, new function, numbers, and context."""
    p = _write_one(client, course, std, catalog, _slot(problem, 1), lang, version, problem["statement"])
    p["id"] = problem["id"]
    return p


def duplicate_problem(client, course, std, catalog, problem, lang, version, new_id):
    """One MORE problem on the same skill and type, using a different type of function."""
    slot = _slot(problem, 1)
    if slot.get("context"):  # and a different kind of real-world setting
        others = [c for c in CONTEXT_FAMILIES if c != slot["context"]]
        slot["context"] = random.choice(others)
    p = _write_one(client, course, std, catalog, slot, lang, version, problem["statement"],
                   new_function_type=True)
    p["id"] = new_id
    return p


def _new_slot(std, qtype, subskill_index=None):
    i = subskill_index if subskill_index is not None else random.randrange(len(std["subskills"]))
    slot = {"type": qtype, "subskill_code": f"{std['code']}.{i + 1}", "subskill": std["subskills"][i], "id": 1}
    if qtype == "interpretation":
        slot["context"] = random.choice(CONTEXT_FAMILIES)
    return slot


def add_problem(client, course, std, catalog, existing, qtype, lang, version, new_id,
                subskill_index=None, note=""):
    """Claude writes one more problem of the chosen type (and subskill, if given), following an
    optional note from the instructor, unlike the problems already on the handout."""
    slot = _new_slot(std, qtype, subskill_index)
    if note.strip():
        slot["note"] = note.strip()[:500]
    p = _write_one(client, course, std, catalog, slot, lang, version, None,
                   others=[_slot(q) for q in existing])
    p.pop("note", None)
    p["id"] = new_id
    p["added"] = "claude"
    return p


def build_own_prompt(course, std, catalog, typed, qtype, lang, version, subskill_index=None):
    language = ("The handout is in Spanish: keep the instructor's Spanish wording, and write the answer and "
                "solution in Spanish." if lang == "es" else "Write the answer and solution in English.")
    sub = (f"It assesses subskill {std['code']}.{subskill_index + 1}." if subskill_index is not None else
           "Decide which subskill it assesses best and give its number in a <subskill> tag, for example "
           "<subskill>2</subskill> for " + f"{std['code']}.2.")
    return f"""An instructor typed their own problem for {HANDOUT_PURPOSE[kind(version)]}

{_std_context(course, std)}

The problem is a {qtype.upper()} problem. {sub}

The instructor typed:
<typed>
{typed.strip()}
</typed>

Your job is to typeset it, not to rewrite it:
- Keep the instructor's question, numbers, functions, context, and wording. Fix only obvious typos and notation.
- Put all mathematics in LaTeX (inline $...$; displayed \\[ ... \\] only for a long expression on its own line).
  Plain-text math such as x^2, sqrt(x), 3/4, f'(x), or e^(2x) becomes $x^2$, $\\sqrt{{x}}$, $\\frac{{3}}{{4}}$, $f'(x)$, $e^{{2x}}$.
- If it has several tasks (a), (b), ..., put each one in its own <part> without the letter.
- Write the correct final answer and a complete worked solution. Use the calculator to check every number.
- If the problem as typed has a mistake or cannot be answered, still typeset it exactly, and explain the issue
  in one sentence inside <issue>...</issue> after the problem block.
{language}

Return the block in this exact format, with id="1":
{BLOCK_FORMAT}

{FORMAT_RULES.replace('<<ACCENTS>>', ' plus Spanish accented letters and inverted punctuation' if lang == 'es' else '')}"""


def format_own_problem(client, course, std, catalog, typed, qtype, lang, version, new_id, subskill_index=None):
    """The instructor's own problem, typeset in LaTeX with an answer and worked solution.
    The math is checked but never changed: any problem found is reported, not 'fixed'."""
    if not typed.strip():
        raise ValueError("Type the problem first.")
    text, _ = call_claude(client, build_own_prompt(course, std, catalog, typed, qtype, lang, version,
                                                   subskill_index), max_tokens=8000)
    if subskill_index is None:
        m = re.search(r"<subskill>\s*(\d+)\s*</subskill>", text)
        k = int(m.group(1)) - 1 if m else 0
        subskill_index = k if 0 <= k < len(std["subskills"]) else 0
    slot = {"type": qtype, "subskill_code": f"{std['code']}.{subskill_index + 1}",
            "subskill": std["subskills"][subskill_index], "id": 1}
    new, _ = parse_problems(text, [slot])
    if not new:
        raise RuntimeError("Claude could not format that problem. Try again, or simplify the wording.")
    p = new[0]
    issue = re.search(r"<issue>(.*?)</issue>", text, re.S)
    if issue and issue.group(1).strip():
        p["warnings"].append("Check this problem: " + issue.group(1).strip()[:400])
    # independent check of the answer key (reported only; the instructor's wording stays)
    findings = parse_findings(call_claude(client, build_review_prompt(course, std, catalog, [p]))[0])
    p["review"] = findings.get(1, [])
    for f in p["review"]:
        if f["verdict"] == "confirmed_error":
            p["warnings"].append("Review note: " + f["text"][:400])
    if find_pdflatex():
        p = repair_latex(client, course, std, catalog, [p], lang, version, [])[0]
    p["id"] = new_id
    p["added"] = "instructor"
    return p


def insert_position(problems, qtype):
    """New problems go at the end of their own type group (skill, then conceptual, then interpretation)."""
    order = QUESTION_TYPES.index(qtype)
    last = -1
    for i, q in enumerate(problems):
        if QUESTION_TYPES.index(q["type"]) <= order:
            last = i
    return last + 1


def problems_compile(problems, course="calc1", lang="en"):
    std = {"code": "S-0", "title": "check", "sections": "", "description": "", "subskills": []}
    h = {"course": course, "std": std, "version": "preparation", "lang": lang,
         "problems": [dict(p) for p in problems]}
    return _pdflatex(build_tex(h), runs=1, timeout=120)[0] is not None


def repair_latex(client, course, std, catalog, problems, lang, version, notes, attempts=2):
    if problems_compile(problems, course, lang):  # usual case: one compile, done
        return problems
    for p in problems:
        for _ in range(attempts):
            ok, err = problem_compiles(p, course, lang)
            if ok:
                break
            prompt = ("This problem block does not compile in LaTeX (exam class with amsmath, amssymb, "
                      f"pgfplots). pdflatex error:\n{err}\n\nRewrite the block so it compiles. Keep the same "
                      "mathematics, type, and subskill. Return only the corrected block with id=\"1\".\n\n"
                      f"{block_text(p, 1)}\n\n{FORMAT_RULES.replace('<<ACCENTS>>', '')}")
            text, _ = call_claude(client, prompt, max_tokens=8000, calculator=False)
            fixed, _ = parse_problems(text, [_slot(p, 1)])
            if fixed:
                keep = {k: p[k] for k in ("id", "review", "repaired_from") if k in p}
                p.clear()
                p.update(fixed[0])
                p.update(keep)
        else:
            ok, err = problem_compiles(p, course, lang)
            if not ok:
                notes.append(f"Problem {p['id']} still has a LaTeX error; edit or regenerate it.")
                p.setdefault("warnings", []).append("LaTeX error: " + err[:300])
    return problems


class Cancelled(Exception):
    """The instructor cancelled the request."""


class _GuardedClient:
    """Wraps the Anthropic client so no new Claude call starts after Cancel."""

    def __init__(self, client, cancel):
        self._client, self._cancel = client, cancel
        self.messages = self

    def create(self, **kwargs):
        if self._cancel.is_set():
            raise Cancelled()
        return self._client.messages.create(**kwargs)

    def with_options(self, **kwargs):
        inner = self._client.with_options(**kwargs) if hasattr(self._client, "with_options") else self._client
        return _GuardedClient(inner, self._cancel)


def generate_batch(client, course, std, catalog, versions, counts_by_version, lang, on_event=None,
                   workers=3, cancel=None, on_tick=None):
    """Generate several versions of one standard in parallel.
    on_event(version, stage) and on_tick() are called from THIS thread (safe for Streamlit);
    on_tick runs about twice a second so the screen can update and Streamlit can stop
    the run when the instructor clicks Cancel. If this thread is interrupted, or `cancel`
    is set, no new Claude call starts and the call returns without waiting for workers.
    Returns {version: result, Exception, or Cancelled}."""
    cancel = cancel or threading.Event()
    guarded = _GuardedClient(client, cancel)
    q = queue.Queue()
    results = {}

    def reporter(v):
        def report(stage):
            if cancel.is_set():
                raise Cancelled()
            q.put((v, stage))
        return report

    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        futs = {pool.submit(generate_version, guarded, course, std, catalog, v, counts_by_version[v], lang,
                            reporter(v)): v for v in versions}
        pending = set(futs)
        while pending:
            time.sleep(0.4)
            if on_tick:
                on_tick()
            if cancel.is_set():
                for f in pending:
                    results[futs[f]] = Cancelled()
                break
            while not q.empty():
                v, stage = q.get()
                if on_event:
                    on_event(v, stage)
            for f in [f for f in pending if f.done()]:
                pending.discard(f)
                v = futs[f]
                try:
                    results[v] = f.result()
                    if on_event:
                        on_event(v, "Done")
                except Exception as exc:  # noqa: BLE001 -- shown to the instructor
                    results[v] = exc
                    if on_event:
                        on_event(v, "Cancelled" if isinstance(exc, Cancelled) else f"Failed: {exc}")
    except BaseException:
        cancel.set()  # e.g. Streamlit stopped this run because Cancel was clicked
        raise
    finally:
        # never block the screen on work that is no longer wanted
        pool.shutdown(wait=not cancel.is_set(), cancel_futures=True)
    return results


# ------------------------------------------------------------------
# LaTeX assembly
# ------------------------------------------------------------------
def esc(s):
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
\usepackage[hidelinks,pdftitle={<<PDFTITLE>>},pdfauthor={<<COURSE>>},pdfsubject={<<PDFTITLE>>},pdflang={<<PDFLANG>>}]{hyperref}
\input{glyphtounicode}
\pdfgentounicode=1
\pagestyle{headandfoot}
\firstpageheader{\small <<STD>>}{}{\small <<VERSION>>}
\runningheader{\small <<STD>>}{}{\small <<VERSION>>}
\firstpageheadrule
\runningheadrule
\firstpagefooter{\small <<CODE>> $\cdot$ <<VERSION>>}{}{\small <<PAGE>> \thepage\ <<OF>> \numpages}
\runningfooter{\small <<CODE>> $\cdot$ <<VERSION>>}{}{\small <<PAGE>> \thepage\ <<OF>> \numpages}
\firstpagefootrule
\runningfootrule
\renewcommand{\questionlabel}{\textbf{\thequestion.}}
\renewcommand{\partlabel}{(\thepartno)}
\renewcommand{\arraystretch}{1.3}
\setlength{\parindent}{0pt}
\newcommand{\typetag}[1]{{\setlength{\fboxsep}{1.5pt}\fbox{\footnotesize\sffamily\bfseries #1}}\hspace{0.45em}}
"""


def _space(inches):
    return f"{max(inches, 0):.3f}in"


def _question(p, q_space, part_space, tag=""):
    label = rf"\textit{{[{esc(p['title'])}]}}\hspace{{0.12in}}" if p.get("title") else ""
    tagtex = rf"\typetag{{{tag}}}" if tag else ""
    out = [r"\par\begin{samepage}", rf"\question {tagtex}{label}{p['statement']}"]
    if p.get("parts"):
        out.append(r"\begin{parts}")
        for part in p["parts"]:
            out.append(rf"\part {part}")
            if part_space > 0:
                out.append(rf"\par\vspace*{{{_space(part_space)}}}")
        out.append(r"\end{parts}")
    elif q_space > 0:
        out.append(rf"\par\vspace*{{{_space(q_space)}}}")
    out.append(r"\par\end{samepage}\penalty-100")
    return "\n".join(out)


def build_tex(h, space_scale=1.0, include_key=True):
    """h: result of generate_version (+ optional 'instructions'). Returns LaTeX source."""
    course, std, version, lang = h["course"], h["std"], h["version"], h["lang"]
    L, C = LABELS[lang], COURSES[course]
    vlabel = L[version]
    code = esc(std["code"])
    pre = (PREAMBLE.replace("<<PDFTITLE>>", esc(f"{std['code']} {vlabel}"))
           .replace("<<COURSE>>", esc(f"{C['code']} {C['name']}"))
           .replace("<<PDFLANG>>", "es-MX" if lang == "es" else "en-US")
           .replace("<<STD>>", esc(f"{std['code']} -- {std['title']}"))
           .replace("<<VERSION>>", esc(vlabel)).replace("<<CODE>>", code)
           .replace("<<PAGE>>", L["page"]).replace("<<OF>>", L["of"]))
    body = [pre, r"\begin{document}",
            r"\binoppenalty=10000 \relpenalty=10000 \tolerance=1000 \emergencystretch=4em"]
    # Assessment identification above the name line: Preparation left, Quest center, Ticket right
    align = TITLE_ALIGN.get(version, "c")
    body.append(rf"\noindent\makebox[\linewidth][{align}]{{\Large\textbf{{{code} $\cdot$ {esc(vlabel)}}}}}"
                r"\par\vspace{6pt}")
    body.append(rf"\noindent {L['name']}: \underline{{\hspace{{2.4in}}}} \hfill {L['date']}: "
                rf"\underline{{\hspace{{1.0in}}}} \hfill {esc(C['code'])} {L['section']}: "
                r"\underline{\hspace{0.7in}}" + "\n\\par\\vspace{8pt}")
    # Learning-standard box (separate from the assessment ID and the Pass/Retake row)
    secs = f"{C['textbook']}, {L['sec']} {std['sections']}" if std.get("sections") else C["textbook"]
    body.append(r"\noindent\fbox{\parbox{\dimexpr\textwidth-2\fboxsep-2\fboxrule}{"
                rf"{{\fontsize{{14}}{{17}}\selectfont\textbf{{{code} --- {esc(std['title'])}}}}}\\"
                rf"{{\small\itshape {esc(secs)}}}\\[4pt]{esc(std['description'])}}}}}")
    if version in QUESTS:
        row = rf"\noindent$\square$ {L['pass']}\qquad $\square$ {L['retake']}"
        if version in ("quest2", "quest3"):
            row += (rf"\qquad {L['attempt']}: \underline{{\hspace{{0.5in}}}}\hfill "
                    rf"{esc(L['ticket_done'])}: $\square$")
        body.append(r"\par\vspace{6pt}" + row)
    body.append(r"\par\vspace{10pt}")  # small gap after the standard before instructions
    body.append(r"\noindent\begin{minipage}{\linewidth}" +
                rf"\textbf{{{L['instructions']}:}} {esc(h.get('instructions') or default_instructions(lang, version))}" +
                r"\par\end{minipage}\par\vspace{10pt}")
    q_space, p_space = QUESTION_SPACE_IN * space_scale, PART_SPACE_IN * space_scale
    num = 0
    body.append(r"\begin{questions}")
    for qtype in QUESTION_TYPES:  # every type is included; each problem carries its letter tag
        for p in [p for p in h["problems"] if p["type"] == qtype]:
            num += 1
            p["num"] = num
            body.append(_question(p, q_space, p_space, L["tag_" + qtype]))
    body.append(r"\end{questions}")
    if version == "preparation" and include_key:  # only Preparation prints a key
        body.append(r"\newpage")
        body.append(rf"\begin{{center}}{{\Large\bfseries {esc(L['key'])} --- {code} {esc(vlabel)}}}\end{{center}}")
        for p in h["problems"]:
            body.append(r"\needspace{6\baselineskip}")
            lab = rf" \textit{{[{esc(p['title'])}]}}" if p.get("title") else ""
            body.append(rf"\noindent\textbf{{{L['problem']} {p['num']}.}} \typetag{{{L['tag_' + p['type']]}}}{lab}"
                        rf"\hfill{{\small {esc(p['subskill_code'])}}}\par\vspace{{2pt}}")
            body.append(p.get("solution", "") + "\n\\par\\vspace{3pt}")
            body.append(rf"\noindent\textbf{{{L['answer']}:}} {p.get('answer', '')}\par")
            body.append(r"\vspace{6pt}\noindent\rule{\linewidth}{0.3pt}\par\vspace{6pt}")
    body.append(r"\end{document}")
    return "\n".join(body) + "\n"


# ------------------------------------------------------------------
# Compiling, page fitting, previews
# ------------------------------------------------------------------
def find_pdflatex():
    cands = [shutil.which("pdflatex"), "/Library/TeX/texbin/pdflatex",
             "/opt/homebrew/bin/pdflatex", "/usr/local/bin/pdflatex"]
    cands += sorted(glob.glob("/usr/local/texlive/*/bin/*/pdflatex"), reverse=True)
    return next((c for c in cands if c and os.path.exists(c)), None)


def _error_excerpt(log):
    lines = log.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("!"):
            return "\n".join(lines[i:i + 8])
    return "\n".join(lines[-15:])


def _pdflatex(tex, runs=2, timeout=180):
    """Returns (pdf_bytes or None, error_text, page_count)."""
    exe = find_pdflatex()
    if not exe:
        return None, ("LaTeX isn't installed where the app runs, so only the .tex file is available "
                      "(open it in TeXstudio to make the PDF)."), 0
    with tempfile.TemporaryDirectory() as d:
        src = pathlib.Path(d) / "handout.tex"
        src.write_text(tex, encoding="utf-8")
        env = dict(os.environ, PATH=str(pathlib.Path(exe).parent) + os.pathsep + os.environ.get("PATH", ""))
        rc = 1
        for _ in range(runs):
            try:
                rc = subprocess.run([exe, "-interaction=nonstopmode", "-halt-on-error", "handout.tex"],
                                    cwd=d, capture_output=True, timeout=timeout, env=env).returncode
            except subprocess.TimeoutExpired:
                return None, "pdflatex timed out.", 0
            if rc:
                break
        logf, pdf = src.with_suffix(".log"), src.with_suffix(".pdf")
        log = logf.read_text(errors="replace") if logf.exists() else ""
        m = re.search(r"Output written on .*?\((\d+) pages?", log)
        pages = int(m.group(1)) if m else 0
        if rc == 0 and pdf.exists():
            return pdf.read_bytes(), "", pages
        return None, _error_excerpt(log), pages


def compile_pdf(tex, runs=2, timeout=180):
    pdf, err, _ = _pdflatex(tex, runs, timeout)
    return pdf, err


def problem_compiles(p, course="calc1", lang="en"):
    std = {"code": "S-0", "title": "check", "sections": "", "description": "", "subskills": []}
    h = {"course": course, "std": std, "version": "preparation", "lang": lang, "problems": [dict(p)]}
    pdf, err, _ = _pdflatex(build_tex(h), runs=1, timeout=60)
    return pdf is not None, err


def fit_preparation(h, target_pages=2, steps=4):
    """Largest answer-space scale (0..1) that keeps Preparation's questions on
    `target_pages` pages (or on as few pages as the content allows at 12 pt)."""
    if not find_pdflatex():
        return 0.5

    def pages(s):
        return _pdflatex(build_tex(h, s, include_key=False), runs=1, timeout=90)[2] or 99
    if pages(1.0) <= target_pages:
        return 1.0
    floor_pages = pages(0.0)
    target = max(target_pages, floor_pages)
    if floor_pages > target_pages:      # content needs more pages at full print size
        if pages(1.0) <= target:
            return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(steps):
        mid = (lo + hi) / 2
        if pages(mid) <= target:
            lo = mid
        else:
            hi = mid
    return round(lo, 3)


def build_files(h):
    """Final .tex and .pdf for one handout. Returns dict with files, errors, scale."""
    scale = fit_preparation(h) if h["version"] == "preparation" else 1.0
    tex = build_tex(h, scale)
    base = base_name(h)
    files = {f"{base}.tex": tex}
    pdf, err, pages = _pdflatex(tex)
    if pdf:
        files[f"{base}.pdf"] = pdf
    return {"base": base, "files": files, "error": err if not pdf else "", "pages": pages, "scale": scale}


def pdf_page_images(pdf_bytes, dpi=70):
    """PNG bytes for each page (needs pdftoppm); empty list if unavailable."""
    exe = shutil.which("pdftoppm")
    if not exe or not pdf_bytes:
        return []
    with tempfile.TemporaryDirectory() as d:
        src = pathlib.Path(d) / "h.pdf"
        src.write_bytes(pdf_bytes)
        subprocess.run([exe, "-png", "-r", str(dpi), str(src), str(pathlib.Path(d) / "p")],
                       capture_output=True, timeout=60)
        return [f.read_bytes() for f in sorted(pathlib.Path(d).glob("p-*.png"),
                                               key=lambda f: int(f.stem.split("-")[-1]))]


def base_name(h):
    import datetime
    v = LABELS["en"][h["version"]].replace(" ", "_")
    return f"{datetime.date.today().isoformat()}_{COURSES[h['course']]['code'].replace(' ', '')}_{h['std']['code']}_{v}_{h['lang']}"
