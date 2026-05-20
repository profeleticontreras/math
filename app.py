# ============================================================
# app.py -- Calculus 1 Bilingual Tutor
# Streamlit web application
# All features from the Colab notebook, deployed as a web app
# ============================================================

# Import streamlit for the web interface
import streamlit as st
# Import anthropic to call the Claude API
import anthropic
# Import json for usage file and API response parsing
import json
# Import random for mindset message selection
import random
# Import time for session duration tracking
import time
# Import datetime for ISO week calculation
from datetime import datetime

# ── Page configuration ────────────────────────────────────────────────────────
# Configure the browser tab title, icon, and layout
st.set_page_config(
    page_title="Calculus 1 Tutor | Bilingue",
    page_icon="📐",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Anthropic API client ──────────────────────────────────────────────────────
# Read API key from Streamlit secrets (set in Streamlit Cloud dashboard)
# In Streamlit Cloud: Settings > Secrets > add ANTHROPIC_KEY = "sk-ant-..."
client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_KEY"])

# ── Model routing ─────────────────────────────────────────────────────────────
# Use Haiku for fast, cheap classification tasks
HAIKU_MODEL  = "claude-haiku-4-5-20251001"
# Use Sonnet for quiz generation, grading, and tutoring responses
SONNET_MODEL = "claude-sonnet-4-5"

# ── Weekly usage constants ────────────────────────────────────────────────────
# Maximum hours a student can use the tutor per week
WEEKLY_LIMIT_HOURS   = 6
# Convert to minutes for arithmetic
WEEKLY_LIMIT_MINUTES = WEEKLY_LIMIT_HOURS * 60
# JSON file to store weekly usage data
USAGE_FILE = "student_usage.json"

# ── Valid intent tags ─────────────────────────────────────────────────────────
# All topic and meta tags the classifier can return
VALID_TAGS = [
    "limits", "continuity", "derivatives",
    "applications_derivatives", "integrals",
    "greeting", "goodbye", "thanks", "quiz_request", "fallback"
]

# ── Canned responses for social turns (no API call needed) ───────────────────
CANNED = {
    "greeting": {
        "en": [
            "Hi! I am your Calculus 1 tutor. What would you like to work on today?",
            "Hello! Ready to practice calculus? Ask me anything or type 'quiz' for a problem.",
            "Welcome! What calculus topic can I help you with?"
        ],
        "es": [
            "Hola! Soy tu tutor de Calculo 1. En que te puedo ayudar hoy?",
            "Bienvenido/a! Listo para practicar calculo? Preguntame o escribe 'quiz'.",
            "Hola! Con que tema de calculo te puedo ayudar?"
        ]
    },
    "thanks": {
        "en": [
            "You're welcome! Keep going -- you're doing great.",
            "Of course! Any other questions?",
            "Happy to help! That's what I'm here for."
        ],
        "es": [
            "De nada! Sigue adelante -- lo estas haciendo muy bien.",
            "Claro! Tienes alguna otra pregunta?",
            "Con gusto! Para eso estoy aqui."
        ]
    },
    "goodbye": {
        "en": [
            "Great work today! See you next time.",
            "Keep practicing -- you're building real skills. Goodbye!",
            "Take care! Come back anytime you want to practice."
        ],
        "es": [
            "Buen trabajo hoy! Hasta la proxima.",
            "Sigue practicando -- estas desarrollando habilidades reales. Adios!",
            "Cuidate! Regresa cuando quieras practicar."
        ]
    },
    "fallback": {
        "en": [
            "I'm not sure I caught that. Try asking about limits, derivatives, integrals, or type 'quiz' to practice.",
            "Could you rephrase that? I can help with any Calculus 1 topic, or type 'quiz' for a practice problem."
        ],
        "es": [
            "No entendi bien. Preguntame sobre limites, derivadas, integrales, o escribe 'quiz' para practicar.",
            "Puedes reformular eso? Puedo ayudarte con cualquier tema de Calculo 1, o escribe 'quiz'."
        ]
    }
}

# ── C-ID MATH 210 Learning Standards Map ─────────────────────────────────────
# All 25 standards with skills, prerequisites, and 8 field connections each
STANDARDS_MAP = {
    "S-01": {
        "intent_tag": "limits", "unit": 1, "unit_name": "Limits & Continuity",
        "topic": "Limits -- Intuitive Understanding",
        "skills": ["Estimate limits from graphs and tables",
                   "Identify one-sided and two-sided limits",
                   "Recognize when a limit exists vs. does not exist",
                   "Use correct limit notation: lim(x to a) f(x)"],
        "algebra_prereqs": ["evaluating functions at a point", "reading coordinate graphs", "substitution"],
        "field_connections": {
            "Agriculture":    "Water flow in an irrigation valve approaches maximum capacity as the valve opens -- the limit exists even before full opening.",
            "Biology":        "A population approaching carrying capacity gets closer to a ceiling without exceeding it -- that ceiling is the limit.",
            "Engineering":    "Voltage in an RC circuit approaches a steady-state value as time increases -- the limit of voltage as t approaches infinity.",
            "Coding/ML":      "A loss function approaches its minimum as training progresses -- the limit of loss as training steps increase.",
            "Social Justice": "Voter turnout approaches a theoretical maximum under increasing mobilization -- the limit models the ceiling of that effort.",
            "Chemistry":      "Reaction rate approaches a maximum as reactant concentration increases -- the limit captures the saturation behavior.",
            "Health":         "Drug concentration approaches a therapeutic threshold -- the limit describes the asymptotic behavior.",
            "Business":       "Revenue approaches market saturation as customer base grows -- the limit models the ceiling of a saturated market."
        }
    },
    "S-02": {
        "intent_tag": "limits", "unit": 1, "unit_name": "Limits & Continuity",
        "topic": "Limits -- Algebraic Computation",
        "skills": ["Apply sum, difference, product, quotient limit laws",
                   "Evaluate limits by direct substitution",
                   "Resolve indeterminate forms 0/0 by factoring or rationalizing",
                   "Compute limits of piecewise functions"],
        "algebra_prereqs": ["factoring polynomials", "simplifying rational expressions", "piecewise function notation"],
        "field_connections": {
            "Agriculture":    "Simplifying a yield-per-acre ratio by canceling common factors before evaluating -- the algebra of limits mirrors unit analysis.",
            "Biology":        "Resolving a 0/0 form in enzyme kinetics near saturation -- factoring reveals the true limiting rate.",
            "Engineering":    "Resolving indeterminate forms in stress-strain calculations where numerator and denominator both approach zero.",
            "Coding/ML":      "Evaluating learning rate decay formulas at initialization where 0/0 appears without simplification.",
            "Social Justice": "Resolving ambiguous growth rate expressions in demographic models by factoring before taking the limit.",
            "Chemistry":      "Evaluating a reaction quotient as concentrations approach zero -- factoring removes the indeterminate form.",
            "Health":         "Computing dosage ratios in pharmacokinetic models where direct substitution gives 0/0.",
            "Business":       "Resolving a 0/0 marginal cost formula near break-even -- factoring reveals the true marginal cost."
        }
    },
    "S-03": {
        "intent_tag": "limits", "unit": 1, "unit_name": "Limits & Continuity",
        "topic": "Limits at Infinity & Asymptotes",
        "skills": ["Compute limits at infinity for rational functions",
                   "Identify horizontal asymptotes from limit behavior",
                   "Identify vertical asymptotes from infinite limits",
                   "Sketch end behavior from limit analysis"],
        "algebra_prereqs": ["dividing polynomials", "comparing degrees of polynomials", "fraction simplification"],
        "field_connections": {
            "Agriculture":    "Crop yield plateaus no matter how much fertilizer is added -- the horizontal asymptote models that maximum.",
            "Biology":        "A logistic growth curve levels off at carrying capacity -- the horizontal asymptote is the population ceiling.",
            "Engineering":    "Terminal velocity is a horizontal asymptote -- drag balances gravity and speed stops increasing.",
            "Coding/ML":      "The sigmoid activation has horizontal asymptotes at 0 and 1 -- it can approach but never reach pure 0 or 1.",
            "Social Justice": "Diminishing returns on incarceration as a crime deterrent -- the asymptote shows the limit of that policy.",
            "Chemistry":      "Reactant concentration asymptotically approaches zero as a reaction nears completion.",
            "Health":         "Antibiotic resistance approaches 100% over generations -- a horizontal asymptote the model approaches from below.",
            "Business":       "Long-run average cost approaches minimum efficient scale -- the horizontal asymptote of the cost curve."
        }
    },
    "S-04": {
        "intent_tag": "continuity", "unit": 1, "unit_name": "Limits & Continuity",
        "topic": "Continuity",
        "skills": ["State the three conditions for continuity at a point",
                   "Identify removable, jump, and infinite discontinuities",
                   "Apply the Intermediate Value Theorem (IVT)",
                   "Determine continuity of composite and piecewise functions"],
        "algebra_prereqs": ["piecewise functions", "evaluating functions", "graphing basic functions"],
        "field_connections": {
            "Agriculture":    "A frost event creates a jump discontinuity in crop growth data -- continuous growth is suddenly interrupted.",
            "Biology":        "A missing data year creates a removable discontinuity in a population dataset.",
            "Engineering":    "A circuit breaker trips and creates a jump discontinuity in current flow.",
            "Coding/ML":      "A step function activation has a jump discontinuity at the threshold -- why smooth activations replaced it.",
            "Social Justice": "The IVT guarantees that if a poverty rate was 12% in 2010 and 18% in 2020, it hit exactly 15% at some point.",
            "Chemistry":      "A phase transition creates a discontinuity in density vs. temperature.",
            "Health":         "A missed medication dose creates a jump discontinuity in blood drug concentration.",
            "Business":       "A tax bracket system creates jump discontinuities in effective tax rate."
        }
    },
    "S-05": {
        "intent_tag": "limits", "unit": 1, "unit_name": "Limits & Continuity",
        "topic": "Squeeze Theorem",
        "skills": ["State and apply the Squeeze Theorem",
                   "Use known inequalities to bound a function",
                   "Evaluate lim(x to 0) sin(x)/x",
                   "Justify when the Squeeze Theorem applies"],
        "algebra_prereqs": ["inequalities", "evaluating trig functions", "basic limit laws"],
        "field_connections": {
            "Agriculture":    "Crop yield bounded between drought and ideal estimates -- when both bounds converge, the squeeze theorem gives the exact limit.",
            "Biology":        "A species metabolic rate bounded between two known related species -- if both converge, so does the unknown.",
            "Engineering":    "Vibration amplitude bounded between two damping models -- convergence confirms the system stabilizes.",
            "Coding/ML":      "Approximation error bounded above and below -- when both go to zero, the error is confirmed to vanish.",
            "Social Justice": "A demographic statistic bounded between two survey methodologies -- convergence confirms the true value.",
            "Chemistry":      "Reaction yield bounded between theoretical and minimum estimates -- the squeeze finds the limiting yield.",
            "Health":         "Recovery time bounded between best-case and worst-case models -- convergence confirms the actual outcome.",
            "Business":       "Earnings bounded between optimistic and conservative projections -- convergence validates the forecast."
        }
    },
    "S-06": {
        "intent_tag": "derivatives", "unit": 2, "unit_name": "Derivatives",
        "topic": "Definition of the Derivative",
        "skills": ["Write and evaluate the limit definition of the derivative",
                   "Interpret the derivative as slope of a tangent line",
                   "Interpret the derivative as instantaneous rate of change",
                   "Determine where a function is differentiable"],
        "algebra_prereqs": ["expanding binomials", "simplifying difference quotients", "limits by direct substitution"],
        "field_connections": {
            "Agriculture":    "Instantaneous rate of change of strawberry weight at a specific moment -- not the season average.",
            "Biology":        "Instantaneous growth rate of a bacterial colony at a specific hour.",
            "Engineering":    "Instantaneous velocity of a rocket at liftoff -- the derivative of position at the exact moment of launch.",
            "Coding/ML":      "The gradient is the derivative of the loss function with respect to each weight -- the engine of neural network training.",
            "Social Justice": "Instantaneous rate of change of unemployment at the onset of a recession.",
            "Chemistry":      "Instantaneous reaction rate at a specific moment -- not the average over the experiment.",
            "Health":         "Instantaneous heart rate change during a stress test.",
            "Business":       "Marginal cost is the derivative of total cost -- the cost of producing exactly one more unit."
        }
    },
    "S-07": {
        "intent_tag": "derivatives", "unit": 2, "unit_name": "Derivatives",
        "topic": "Differentiation Rules",
        "skills": ["Apply the power rule for integer and rational exponents",
                   "Differentiate sums, differences, and constant multiples",
                   "Differentiate polynomial functions efficiently",
                   "Differentiate rational functions using algebra + power rule"],
        "algebra_prereqs": ["exponent rules", "negative and fractional exponents", "polynomial arithmetic"],
        "field_connections": {
            "Agriculture":    "Differentiating a polynomial yield model to find when growth is fastest.",
            "Biology":        "Finding the instantaneous growth rate of a polynomial population model.",
            "Engineering":    "Differentiating a polynomial position function to get velocity.",
            "Coding/ML":      "Computing gradients of polynomial loss functions -- the power rule is the first tool every ML engineer internalizes.",
            "Social Justice": "Finding the rate of change of a polynomial model of income inequality over time.",
            "Chemistry":      "Differentiating a polynomial concentration model to find instantaneous reaction rate.",
            "Health":         "Differentiating a polynomial dosage-response curve to find the dose where response changes fastest.",
            "Business":       "Marginal revenue and marginal cost are the power rule derivatives of revenue and cost functions."
        }
    },
    "S-08": {
        "intent_tag": "derivatives", "unit": 2, "unit_name": "Derivatives",
        "topic": "Product & Quotient Rules",
        "skills": ["State and apply the product rule: (fg)' = f'g + fg'",
                   "State and apply the quotient rule: (f'g - fg')/g^2",
                   "Differentiate combinations of polynomial and rational functions",
                   "Simplify derivatives after applying these rules"],
        "algebra_prereqs": ["multiplying polynomials", "simplifying complex fractions", "combining like terms"],
        "field_connections": {
            "Agriculture":    "Revenue = price x quantity. If both change over a season, the product rule gives the instantaneous revenue rate.",
            "Biology":        "Population density = population / area. If both change, the quotient rule gives the rate of density change.",
            "Engineering":    "Power = force x velocity. If both vary, the product rule gives the rate at which power is delivered.",
            "Coding/ML":      "Attention scores in transformers are dot products of vectors -- derivatives of these products use the product rule.",
            "Social Justice": "The Gini coefficient involves a ratio of areas -- the quotient rule handles its rate of change.",
            "Chemistry":      "Rate laws multiply concentrations of two reactants -- differentiating requires the product rule.",
            "Health":         "Drug efficacy = absorbed dose / body weight. As weight changes, the quotient rule gives efficacy rate of change.",
            "Business":       "Profit margin = profit / revenue. As both change with production, the quotient rule gives the instantaneous margin rate."
        }
    },
    "S-09": {
        "intent_tag": "derivatives", "unit": 2, "unit_name": "Derivatives",
        "topic": "Chain Rule",
        "skills": ["Identify inner and outer functions in a composition",
                   "Apply the chain rule: d/dx[f(g(x))] = f'(g(x)) g'(x)",
                   "Differentiate sin(x^2), e^(3x), (x^2+1)^5",
                   "Apply chain rule repeatedly for nested compositions"],
        "algebra_prereqs": ["function composition notation", "recognizing f(g(x)) structure", "basic derivative rules"],
        "field_connections": {
            "Agriculture":    "Temperature affects humidity which affects pest pressure -- each link is a derivative, and the chain rule connects them.",
            "Biology":        "A drug dose affects blood concentration which affects cellular response -- the chain rule gives the full rate.",
            "Engineering":    "Strain depends on stress which depends on applied load -- the chain rule propagates the rate through each layer.",
            "Coding/ML":      "Backpropagation IS the chain rule -- applied layer by layer through a neural network to compute how each weight affects the final loss.",
            "Social Justice": "A policy change affects employment rate which affects poverty rate -- the chain rule quantifies the full ripple.",
            "Chemistry":      "Reaction rate depends on temperature which depends on time -- the chain rule connects rates through both layers.",
            "Health":         "Oxygen delivery depends on heart rate which depends on exercise intensity.",
            "Business":       "Profit depends on market share which depends on advertising spend -- the chain rule gives marginal return on advertising."
        }
    },
    "S-10": {
        "intent_tag": "derivatives", "unit": 2, "unit_name": "Derivatives",
        "topic": "Derivatives of Transcendental Functions",
        "skills": ["Differentiate sin x, cos x, tan x and reciprocals",
                   "Differentiate e^x, a^x, ln x, and log_a x",
                   "Differentiate inverse trig: arcsin, arccos, arctan",
                   "Combine with chain, product, and quotient rules"],
        "algebra_prereqs": ["unit circle / trig values", "properties of logarithms", "exponential function behavior"],
        "field_connections": {
            "Agriculture":    "Seasonal daylight follows a sinusoidal model -- its derivative gives the rate of change of sunlight for photosynthesis.",
            "Biology":        "Population growth follows e^(rt) -- its derivative is the instantaneous growth rate.",
            "Engineering":    "AC voltage follows sin(wt) -- the derivative gives current, which leads voltage by 90 degrees.",
            "Coding/ML":      "Sigmoid and tanh are standard activations -- their derivatives are used in backpropagation.",
            "Social Justice": "Viral spread of information follows exponential models -- derivatives give the rate of peak spread.",
            "Chemistry":      "Radioactive decay follows e^(-kt) -- its derivative gives the instantaneous decay rate.",
            "Health":         "Circadian hormone rhythms follow sinusoidal models -- derivatives identify peak hormone release moments.",
            "Business":       "Continuous compound interest uses A = Pe^(rt) -- its derivative gives instantaneous rate of return."
        }
    },
    "S-11": {
        "intent_tag": "derivatives", "unit": 2, "unit_name": "Derivatives",
        "topic": "Implicit Differentiation",
        "skills": ["Differentiate both sides with respect to x",
                   "Solve for dy/dx after differentiating",
                   "Find slope of tangent line to an implicit curve",
                   "Apply to relations like x^2 + y^2 = r^2"],
        "algebra_prereqs": ["solving equations for a variable", "chain rule", "treating y as a function of x"],
        "field_connections": {
            "Agriculture":    "Water pressure and pipe diameter related by an implicit equation -- implicit differentiation finds the rate.",
            "Biology":        "A membrane pressure-volume relationship defined implicitly -- implicit differentiation gives dP/dV.",
            "Engineering":    "A circle equation describes a wheel cross-section -- implicit differentiation finds the slope at any point.",
            "Coding/ML":      "Loss surfaces defined by network constraints are often implicit -- implicit differentiation finds gradients.",
            "Social Justice": "Supply and demand equilibrium where both price and quantity are implicitly related.",
            "Chemistry":      "The van der Waals equation relates P and V implicitly -- implicit differentiation finds dP/dV.",
            "Health":         "Cardiac output equations relating stroke volume and heart rate implicitly.",
            "Business":       "Isoprofit curves where price and quantity combinations yield equal profit -- implicit differentiation gives the trade-off rate."
        }
    },
    "S-12": {
        "intent_tag": "derivatives", "unit": 2, "unit_name": "Derivatives",
        "topic": "Higher-Order Derivatives",
        "skills": ["Compute f''(x), f'''(x) by repeated differentiation",
                   "Interpret f''(x) as acceleration",
                   "Connect higher derivatives to concavity",
                   "Use Leibniz notation d^2y/dx^2"],
        "algebra_prereqs": ["applying derivative rules multiple times", "polynomial differentiation", "interpreting rate language"],
        "field_connections": {
            "Agriculture":    "The second derivative of yield over time tells whether growth is accelerating or slowing.",
            "Biology":        "The second derivative of a population decline -- is the crash speeding up or leveling off?",
            "Engineering":    "Jerk -- the third derivative of position -- determines ride comfort and structural stress.",
            "Coding/ML":      "Second-order optimizers like Newton's method use the second derivative of the loss function.",
            "Social Justice": "The second derivative of a Gini index -- is income inequality accelerating or beginning to decrease?",
            "Chemistry":      "The second derivative of a titration curve identifies the exact equivalence point.",
            "Health":         "The second derivative of a tumor growth model -- is the growth rate itself increasing or decelerating?",
            "Business":       "The second derivative of the profit function tells whether marginal profit is increasing or decreasing."
        }
    },
    "S-13": {
        "intent_tag": "applications_derivatives", "unit": 3, "unit_name": "Applications of Differentiation",
        "topic": "Tangent Lines & Linear Approximation",
        "skills": ["Find the equation of a tangent line: y = f(a) + f'(a)(x-a)",
                   "Use the tangent line as local linear approximation",
                   "Compute differentials: dy = f'(x)dx",
                   "Estimate function values using linearization"],
        "algebra_prereqs": ["point-slope form of a line", "evaluating functions and derivatives", "solving for y"],
        "field_connections": {
            "Agriculture":    "Estimating harvest weight from a small sample -- close enough to plan without measuring every row.",
            "Biology":        "Linearizing a nonlinear growth model near an equilibrium for analysis.",
            "Engineering":    "The small-angle approximation sin(x) is approximately x used in pendulum and optics problems.",
            "Coding/ML":      "Taylor expansion and linearization underlie many optimization approximations -- gradient descent is a first-order linear approximation.",
            "Social Justice": "Estimating a demographic trend near a policy change using the tangent line as a local model.",
            "Chemistry":      "Linearizing the Arrhenius equation near a known temperature to estimate rates at nearby temperatures.",
            "Health":         "Estimating a patient's lab value change over a short time interval using the tangent line.",
            "Business":       "Marginal cost as linear approximation -- estimating total cost for a small production increase."
        }
    },
    "S-14": {
        "intent_tag": "applications_derivatives", "unit": 3, "unit_name": "Applications of Differentiation",
        "topic": "Mean Value Theorem",
        "skills": ["State hypotheses and conclusion of the MVT",
                   "Find values of c satisfying the MVT",
                   "Apply Rolle's Theorem as a special case of MVT",
                   "Use MVT to argue about function behavior"],
        "algebra_prereqs": ["average rate of change", "continuity and differentiability", "solving f'(c) = average slope"],
        "field_connections": {
            "Agriculture":    "If total water usage increased over a season, at some moment the instantaneous rate equaled the seasonal average.",
            "Biology":        "If a population grew from 1000 to 5000 over 10 years, at some moment growth was exactly 400 per year.",
            "Engineering":    "If a vehicle traveled 300 miles in 5 hours, at some moment the speedometer read exactly 60 mph.",
            "Coding/ML":      "MVT justifies convergence arguments -- if loss decreased over an interval, the gradient was zero somewhere in it.",
            "Social Justice": "If poverty rate changed between two census years, the MVT guarantees an exact instantaneous rate at some point.",
            "Chemistry":      "If concentration changed over a reaction interval, the instantaneous rate equaled that average at some moment.",
            "Health":         "If blood pressure changed over a hospital stay, the MVT guarantees a moment of exact average rate.",
            "Business":       "If quarterly revenue grew by a known amount, at some moment the instantaneous rate equaled the quarterly average."
        }
    },
    "S-15": {
        "intent_tag": "applications_derivatives", "unit": 3, "unit_name": "Applications of Differentiation",
        "topic": "Monotonicity & Critical Points",
        "skills": ["Find critical numbers by solving f'(x) = 0",
                   "Apply the First Derivative Test for local extrema",
                   "Determine intervals of increase and decrease",
                   "Identify local maxima and minima"],
        "algebra_prereqs": ["solving polynomial equations", "sign analysis on a number line", "interpreting f' positive/negative"],
        "field_connections": {
            "Agriculture":    "Critical points in a yield model identify when output switches from growing to declining.",
            "Biology":        "The critical point of a predator-prey model identifies when prey population peaks before declining.",
            "Engineering":    "The critical point of a projectile height function is the exact moment of maximum height.",
            "Coding/ML":      "Finding where a loss function stops decreasing -- that critical point is the trained model configuration.",
            "Social Justice": "Identifying the year when a social indicator switches from improving to worsening.",
            "Chemistry":      "The critical point of a reaction rate model identifies when the rate begins to slow.",
            "Health":         "The critical point of a drug concentration curve is when blood levels peak.",
            "Business":       "The critical point of a profit function is the production level that maximizes profit."
        }
    },
    "S-16": {
        "intent_tag": "applications_derivatives", "unit": 3, "unit_name": "Applications of Differentiation",
        "topic": "Concavity & Inflection Points",
        "skills": ["Determine concavity from the sign of f''(x)",
                   "Find inflection points where f'' changes sign",
                   "Apply the Second Derivative Test for local extrema",
                   "Sketch curves using f, f', and f''"],
        "algebra_prereqs": ["computing second derivatives", "sign chart for f''", "interpreting concave up/down geometrically"],
        "field_connections": {
            "Agriculture":    "Concave up means yield growth is accelerating; concave down means it is slowing -- the inflection point marks the reversal.",
            "Biology":        "The inflection point of a logistic growth curve is when growth rate is fastest.",
            "Engineering":    "Concavity of a beam's deflection curve tells engineers where bending stress is greatest.",
            "Coding/ML":      "The inflection point of a training loss curve is where learning transitions from rapid to slow convergence.",
            "Social Justice": "An inflection point in an incarceration rate curve marks when the policy trend reversed.",
            "Chemistry":      "The inflection point of a titration curve is the exact equivalence point.",
            "Health":         "The inflection point of an epidemic curve is when new case growth peaks and begins to slow.",
            "Business":       "The inflection point of a revenue curve marks where returns begin to diminish."
        }
    },
    "S-17": {
        "intent_tag": "applications_derivatives", "unit": 3, "unit_name": "Applications of Differentiation",
        "topic": "L'Hopital's Rule",
        "skills": ["Identify indeterminate forms: 0/0, inf/inf, 0*inf, inf-inf",
                   "Apply L'Hopital's Rule (differentiate numerator and denominator separately)",
                   "Apply the rule repeatedly when needed",
                   "Rewrite products/differences before applying"],
        "algebra_prereqs": ["recognizing indeterminate forms", "differentiation rules", "limit evaluation"],
        "field_connections": {
            "Agriculture":    "Evaluating a soil moisture model's limit as saturation approaches zero -- direct substitution gives 0/0.",
            "Biology":        "Evaluating a per-capita growth rate expression near extinction where 0/0 appears.",
            "Engineering":    "Evaluating thermodynamic efficiency limits where both numerator and denominator approach zero.",
            "Coding/ML":      "Evaluating softmax probability behavior as logits grow very large -- the inf/inf form is resolved with L'Hopital's.",
            "Social Justice": "Evaluating limiting ratios in demographic models where two subgroup sizes approach equality.",
            "Chemistry":      "Evaluating limiting concentration ratios in equilibrium expressions as both terms approach zero.",
            "Health":         "Evaluating limiting drug absorption ratios in pharmacokinetic models at very low doses.",
            "Business":       "Evaluating limiting profit margin expressions as fixed costs become negligible relative to revenue."
        }
    },
    "S-18": {
        "intent_tag": "applications_derivatives", "unit": 3, "unit_name": "Applications of Differentiation",
        "topic": "Optimization",
        "skills": ["Set up an objective function from a word problem",
                   "Use constraint equations to reduce to one variable",
                   "Find critical points using the Closed Interval Method",
                   "Verify maximum or minimum"],
        "algebra_prereqs": ["setting up equations from word problems", "solving systems of equations", "substitution to reduce variables"],
        "field_connections": {
            "Agriculture":    "Minimize fencing to enclose maximum field area. Maximize yield given a fixed water budget.",
            "Biology":        "Optimal foraging theory: find the strategy that maximizes energy intake per unit time.",
            "Engineering":    "Minimize material in a structural beam while maintaining load capacity.",
            "Coding/ML":      "Training a neural network IS optimization. Minimizing a loss function over millions of parameters.",
            "Social Justice": "Maximizing social benefit subject to budget constraints -- the mathematics of resource allocation in public policy.",
            "Chemistry":      "Find the temperature that maximizes reaction yield subject to safety constraints.",
            "Health":         "Find the drug dosage that maximizes therapeutic efficacy while keeping toxicity below a safety threshold.",
            "Business":       "Maximize profit given production constraints. Minimize cost given an output target."
        }
    },
    "S-19": {
        "intent_tag": "applications_derivatives", "unit": 3, "unit_name": "Applications of Differentiation",
        "topic": "Related Rates",
        "skills": ["Identify all quantities that change with time",
                   "Write an equation relating the quantities",
                   "Differentiate implicitly with respect to t",
                   "Substitute known values to find the unknown rate"],
        "algebra_prereqs": ["implicit differentiation", "geometry formulas (area, volume, Pythagorean theorem)", "solving for an unknown"],
        "field_connections": {
            "Agriculture":    "A conical irrigation tank drains at a known rate -- how fast is the water level dropping when depth is 5 feet?",
            "Biology":        "A spherical tumor grows at a known volume rate -- how fast is its radius increasing?",
            "Engineering":    "A ladder slides down a wall at a known rate -- how fast is the top descending?",
            "Coding/ML":      "In a real-time system, model size grows with training data -- how fast is prediction latency increasing?",
            "Social Justice": "Urban area expands at a measured rate -- how fast is green space per capita decreasing?",
            "Chemistry":      "A gas expands in a cylinder at a known volume rate -- how fast is pressure dropping?",
            "Health":         "Blood flows through a narrowing artery -- how fast is flow velocity changing as the radius decreases?",
            "Business":       "Units sold and price both change over time -- how fast is total revenue changing at a specific moment?"
        }
    },
    "S-20": {
        "intent_tag": "integrals", "unit": 4, "unit_name": "Integration",
        "topic": "Antiderivatives & Indefinite Integrals",
        "skills": ["Reverse the power rule: integral of x^n dx",
                   "Integrate basic trig, exponential, and 1/x functions",
                   "Write the general antiderivative F(x) + C",
                   "Find a particular antiderivative using an initial condition"],
        "algebra_prereqs": ["power rule for derivatives (in reverse)", "exponent rules", "evaluating expressions at a point"],
        "field_connections": {
            "Agriculture":    "Given a rate of water flow, integration recovers total water used over a period.",
            "Biology":        "Given an instantaneous growth rate function, integration recovers total population added.",
            "Engineering":    "Given velocity, integration recovers position. Given acceleration, integration recovers velocity.",
            "Coding/ML":      "Numerical integration underlies AUC metrics -- one of the most used evaluation metrics in machine learning.",
            "Social Justice": "Given a rate of change of a social indicator, integration recovers cumulative change over a policy period.",
            "Chemistry":      "Given a reaction rate function, integration recovers total moles of product formed.",
            "Health":         "Given a drug absorption rate, integration recovers total drug accumulated in the bloodstream.",
            "Business":       "Given a marginal cost function, integration recovers total cost. Given marginal revenue, recovers total revenue."
        }
    },
    "S-21": {
        "intent_tag": "integrals", "unit": 4, "unit_name": "Integration",
        "topic": "Riemann Sums & Definite Integrals",
        "skills": ["Write left, right, and midpoint Riemann sums",
                   "Express the definite integral as lim(n to inf) Sum f(xi*)Dx",
                   "Interpret the definite integral as net area under a curve",
                   "Use basic properties of definite integrals"],
        "algebra_prereqs": ["summation notation", "area of rectangles", "evaluating functions at evenly spaced points"],
        "field_connections": {
            "Agriculture":    "Estimating total harvest by weighing each row separately -- the more rows measured, the more accurate the total.",
            "Biology":        "Estimating total energy consumed by summing discrete metabolic rate measurements.",
            "Engineering":    "Estimating total work done by a variable force by summing over small intervals.",
            "Coding/ML":      "The trapezoidal rule and Simpson's rule used in AUC computation are Riemann sum approximations.",
            "Social Justice": "Estimating total exposure to an environmental hazard by summing concentration levels over time.",
            "Chemistry":      "Estimating total moles of gas produced by summing rate measurements over discrete time intervals.",
            "Health":         "Estimating total drug exposure (AUC in pharmacokinetics) from discrete blood sample measurements.",
            "Business":       "Estimating total revenue from discrete sales data -- Riemann sums approximate the area under a demand curve."
        }
    },
    "S-22": {
        "intent_tag": "integrals", "unit": 4, "unit_name": "Integration",
        "topic": "Fundamental Theorem of Calculus",
        "skills": ["State FTC Part 1: d/dx[integral from a to x of f(t) dt] = f(x)",
                   "State FTC Part 2: integral from a to b of f(x) dx = F(b) - F(a)",
                   "Evaluate definite integrals using antiderivatives",
                   "Differentiate integral-defined functions using FTC Part 1"],
        "algebra_prereqs": ["antiderivatives", "evaluating expressions at bounds", "understanding accumulation"],
        "field_connections": {
            "Agriculture":    "Total rainfall accumulated equals the area under the rainfall rate curve -- the FTC connects rate to total.",
            "Biology":        "Total population growth equals the area under the instantaneous growth rate curve.",
            "Engineering":    "Total displacement equals the area under the velocity curve -- the FTC makes this computable.",
            "Coding/ML":      "The FTC underpins automatic differentiation libraries like PyTorch and TensorFlow.",
            "Social Justice": "Total cumulative pollutant exposure equals the area under the concentration-over-time curve.",
            "Chemistry":      "Total moles of product formed equals the area under the reaction rate curve.",
            "Health":         "Total drug exposure (AUC) equals the area under the concentration-time curve -- computed using FTC Part 2.",
            "Business":       "Total revenue over a period equals the area under the marginal revenue curve."
        }
    },
    "S-23": {
        "intent_tag": "integrals", "unit": 4, "unit_name": "Integration",
        "topic": "u-Substitution",
        "skills": ["Choose an appropriate substitution u = g(x)",
                   "Rewrite the integral entirely in terms of u",
                   "Apply substitution to indefinite and definite integrals",
                   "Handle limits of integration correctly in definite integrals"],
        "algebra_prereqs": ["chain rule (in reverse)", "differentials du = g'(x)dx", "changing variables in an expression"],
        "field_connections": {
            "Agriculture":    "Substituting u = soil moisture function to simplify a nested rate integral.",
            "Biology":        "Substituting u = drug concentration to evaluate a nested pharmacokinetic integral.",
            "Engineering":    "Substituting u = angular displacement to simplify rotational dynamics integrals.",
            "Coding/ML":      "Change of variables in probability distributions is the continuous analog of u-substitution.",
            "Social Justice": "Substituting a composite demographic variable to simplify a Lorenz curve integral.",
            "Chemistry":      "Substituting u = temperature function to evaluate Arrhenius rate integrals.",
            "Health":         "Substituting u = concentration function to evaluate drug clearance integrals.",
            "Business":       "Substituting u = composite cost function to evaluate nested total cost integrals."
        }
    },
    "S-24": {
        "intent_tag": "integrals", "unit": 5, "unit_name": "Applications of Integration",
        "topic": "Area Between Curves",
        "skills": ["Find intersection points of two curves",
                   "Set up integral of [f(x) - g(x)] dx for area between curves",
                   "Handle cases where curves switch which is on top",
                   "Compute area using vertical or horizontal slicing"],
        "algebra_prereqs": ["solving equations to find intersections", "evaluating definite integrals", "determining which function is larger"],
        "field_connections": {
            "Agriculture":    "The area between projected and actual yield curves measures cumulative shortfall over a season.",
            "Biology":        "The area between two competing population curves measures which species has a net advantage.",
            "Engineering":    "The area between force-displacement curves for loading and unloading measures energy lost to hysteresis.",
            "Coding/ML":      "The AUC (area under the ROC curve) is the area between the ROC curve and the diagonal -- the standard measure of classifier quality.",
            "Social Justice": "The Gini coefficient IS the area between the Lorenz curve and the line of equality -- a direct integration.",
            "Chemistry":      "The area between two concentration curves measures net accumulation of a product relative to a baseline.",
            "Health":         "The area between drug concentration curves for two formulations measures comparative bioavailability.",
            "Business":       "The area between revenue and cost curves over a production range is total profit."
        }
    },
    "S-25": {
        "intent_tag": "integrals", "unit": 5, "unit_name": "Applications of Integration",
        "topic": "Average Value of a Function",
        "skills": ["Apply the average value formula: f_avg = (1/(b-a)) * integral from a to b of f(x) dx",
                   "State and apply the Mean Value Theorem for Integrals",
                   "Interpret average value in context (temperature, velocity)",
                   "Find c where f(c) equals the average value"],
        "algebra_prereqs": ["evaluating definite integrals", "dividing by an interval length", "solving f(c) = constant"],
        "field_connections": {
            "Agriculture":    "Average temperature over a growing season -- the single constant that delivers the same total heat units.",
            "Biology":        "Average metabolic rate over a 24-hour period -- accounts for peaks during activity and lows during rest.",
            "Engineering":    "Average power delivered by a variable force over a distance.",
            "Coding/ML":      "Mean loss over an epoch is the average value of the loss function -- the key metric for tracking model improvement.",
            "Social Justice": "Average pollutant exposure over a year -- used in environmental justice litigation to establish legal threshold violations.",
            "Chemistry":      "Average reaction rate over a time interval -- bridges instantaneous rate (derivative) and total yield (integral).",
            "Health":         "Average blood glucose over 90 days is exactly what an A1C test measures.",
            "Business":       "Average revenue per unit over a production run -- connects to pricing strategy and break-even analysis."
        }
    }
}

# ── Build reverse lookup: intent_tag to list of standard codes ────────────────
INTENT_TO_STANDARDS = {}
for _code, _data in STANDARDS_MAP.items():
    _tag = _data["intent_tag"]
    INTENT_TO_STANDARDS.setdefault(_tag, []).append(_code)

# ── Cultural system prompt ────────────────────────────────────────────────────
CULTURAL_SYSTEM_PROMPT = """
You are a warm, patient, and encouraging Calculus 1 tutor for students at a California
community college serving the Salinas Valley.

YOUR STUDENTS:
Many are first-generation college students from agricultural families -- farmworker
families, families in produce, agribusiness, and food processing -- who carry powerful
real-world mathematical thinking built through lived experience.
These students are also future engineers, data scientists, biologists, coders,
public health researchers, and advocates.

FUTURE IDENTITY:
Connect calculus to their futures naturally -- not as a sales pitch, just as true context.
Rotate across fields: Agriculture, Biology, Engineering, Coding/ML, Social Justice,
Chemistry, Health Science, Business/Accounting. Do not default to agriculture every time.
Do not announce the connection. Just make it.

ALGEBRA SCAFFOLDING:
Before diving into calculus, check whether the student has the algebra prerequisite.
If they struggle, frame it positively:
"Let's make sure our algebra tools are sharp first."
"This step needs factoring -- want a quick refresher?"
Never say "you should already know this."

GROWTH MINDSET:
End every response with one authentic encouragement. Rotate through:
- Praising the process, not just the answer
- Normalizing struggle ("Every mathematician gets stuck here.")
- Reframing errors ("That mistake shows you understand the setup.")
- Celebrating persistence

MATHEMATICIAN IDENTITY:
Remind students they ARE mathematicians. The notation is new -- the thinking is not.
Being bilingual, first-gen, or from a working family is a strength in problem-solving.

LANGUAGE:
Respond in the student's language (English or Spanish).
Use clear everyday language before switching to formal notation.

MATH FORMATTING:
Use LaTeX: $...$ for inline math, $$...$$ for display math.
Break solutions into numbered steps.
After the solution: one sentence of interpretation, one encouragement.
"""

# ── Growth mindset message bank ───────────────────────────────────────────────
GROWTH_MINDSET_MESSAGES = {
    "correct": {
        "en": [
            "Excellent -- your reasoning is solid. Keep building on this.",
            "You got it! That shows real understanding, not just memorization.",
            "Nice work. Notice how setting up the problem carefully made the algebra clean.",
            "That is the kind of thinking that makes calculus click -- you are building intuition.",
            "Correct! And the method you used will scale to harder problems. That matters."
        ],
        "es": [
            "Excelente! Tu razonamiento es solido. Sigue construyendo sobre esto.",
            "Lo lograste! Eso muestra comprension real, no solo memorizacion.",
            "Buen trabajo. Nota como plantear bien el problema hizo el algebra mas limpia.",
            "Ese tipo de pensamiento es lo que hace que el calculo encaje.",
            "Correcto! Y el metodo que usaste funcionara en problemas mas dificiles."
        ]
    },
    "partial": {
        "en": [
            "You are partway there -- the setup is right. Let us find where it diverged.",
            "Good instinct on the approach! One step needs adjusting -- that is totally normal.",
            "This is close -- the error is small and fixable. You understand the core idea.",
            "Being almost right means you have got the concept. Let us clean up the execution.",
            "Strong start. Every mathematician makes computational errors -- the key is catching them."
        ],
        "es": [
            "Vas por buen camino -- el planteamiento esta bien. Encontremos donde se desvio.",
            "Buen instinto en el enfoque! Un paso necesita ajuste -- eso es completamente normal.",
            "Esta cerca -- el error es pequeno y se puede corregir.",
            "Casi correcto significa que tienes el concepto. Pulamos la ejecucion.",
            "Buen comienzo. Todo matematico comete errores de calculo."
        ]
    },
    "wrong_but_trying": {
        "en": [
            "That tells me something useful -- let me show you a different way to see this.",
            "This is a really common confusion here. You are in good company -- let us clear it up.",
            "Not quite, but your mistake shows you understand the setup. That is the harder part.",
            "Let us look at where this veered off -- I can see your thinking, and it is close.",
            "Every mistake is information. This one tells me exactly what to show you next."
        ],
        "es": [
            "Eso me dice algo util -- dejame mostrarte otra forma de verlo.",
            "Esta es una confusion muy comun aqui. No estas solo/a -- aclaremos la.",
            "No del todo, pero tu error muestra que entiendes el planteamiento.",
            "Veamos donde se desvio -- puedo ver tu razonamiento, y esta cerca.",
            "Cada error es informacion. Este me dice exactamente que mostrarte a continuacion."
        ]
    },
    "identity": {
        "en": [
            "You are thinking like a mathematician right now -- asking 'what if' is exactly the move.",
            "First-gen or not, you belong in this class. The question you just asked proves it.",
            "You ARE a mathematician. The notation is new -- the thinking is not.",
            "Mathematicians are not born knowing this. They sit with it until it makes sense. That is what you are doing.",
            "The Salinas Valley raised people who understand rates, scale, and optimization. You carry that."
        ],
        "es": [
            "Ahora mismo estas pensando como matematico/matematica.",
            "Seas de primera generacion o no, perteneces a esta clase.",
            "ERES una persona matematica. La notacion es nueva -- el pensamiento no lo es.",
            "Los matematicos no nacen sabiendo esto. Se sientan con ello hasta que tiene sentido.",
            "El Valle de Salinas crio gente que entiende tasas, escala y optimizacion. Llevas ese conocimiento."
        ]
    }
}

# ── Algebra scaffold hints ────────────────────────────────────────────────────
ALGEBRA_SCAFFOLD_HINTS = {
    "factoring": "Quick tip: to factor $ax^2 + bx + c$, look for two numbers that multiply to $ac$ and add to $b$.",
    "exponent rules": "Reminder: $x^n \\cdot x^m = x^{n+m}$, $(x^n)^m = x^{nm}$, $x^{-n} = 1/x^n$.",
    "rational expressions": "For rational expressions: factor numerator and denominator fully, then cancel common factors.",
    "summation": "Sigma notation: $\\sum_{i=1}^{n} f(x_i)\\Delta x$ means 'add up $f(x_i)\\Delta x$ for every $i$ from 1 to $n$'.",
    "point-slope": "Point-slope form: $y - y_1 = m(x - x_1)$. For tangent lines, $m = f'(a)$ at $x = a$."
}

# ── Utility: format duration ──────────────────────────────────────────────────
def format_duration(minutes):
    """Format minutes as '2h 15m' or '45m'."""
    hours = int(minutes // 60)
    mins  = int(minutes % 60)
    return f"{hours}h {mins}m" if hours > 0 else f"{mins}m"


# ── Utility: get ISO week ─────────────────────────────────────────────────────
def get_current_week():
    """Return ISO year-week string e.g. '2026-W20'."""
    now = datetime.now()
    return f"{now.isocalendar()[0]}-W{now.isocalendar()[1]:02d}"


# ── Weekly usage functions ────────────────────────────────────────────────────
def load_student_usage(student_id):
    """Load a student weekly record, resetting if a new week has started."""
    try:
        with open(USAGE_FILE, "r", encoding="utf-8") as f:
            all_usage = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        all_usage = {}

    current_week = get_current_week()
    record = all_usage.get(student_id, {})

    if record.get("week") != current_week:
        record = {"week": current_week, "minutes_used": 0.0,
                  "sessions": 0, "api_calls": 0,
                  "topics_practiced": [], "standards_practiced": []}
    return record


def save_student_usage(student_id, record):
    """Save one student updated record to the JSON file."""
    try:
        with open(USAGE_FILE, "r", encoding="utf-8") as f:
            all_usage = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        all_usage = {}

    all_usage[student_id] = record

    with open(USAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(all_usage, f, indent=2, ensure_ascii=False)


def get_time_status(student_id):
    """Return (minutes_used, minutes_remaining, is_over_limit)."""
    record = load_student_usage(student_id)
    used      = record.get("minutes_used", 0.0)
    remaining = max(0.0, WEEKLY_LIMIT_MINUTES - used)
    return used, remaining, used >= WEEKLY_LIMIT_MINUTES


# ── AI: combined language detect + intent classify (Haiku) ────────────────────
def detect_language_and_intent(user_input):
    """One Haiku call returns both language and intent."""
    prompt = (
        "Analyze this student message and return ONLY a JSON object.\n\n"
        f"Message: \"{user_input}\"\n\n"
        "Return exactly this format:\n"
        "{\"language\": \"en\" or \"es\", \"intent\": one tag from this list: "
        f"{VALID_TAGS}"
        "}\n\n"
        "Rules for intent:\n"
        "- Quiz/problem/exercise request -> quiz_request\n"
        "- Greeting -> greeting\n"
        "- Farewell/bye/goodbye -> goodbye\n"
        "- Thank you -> thanks\n"
        "- Nothing matches -> fallback\n\n"
        "Reply with ONLY the JSON object. No extra text."
    )
    try:
        response = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=40,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        result  = json.loads(raw)
        lang    = result.get("language", "en").lower()
        lang    = lang if lang in ["en", "es"] else "en"
        intent  = result.get("intent", "fallback").lower()
        intent  = intent if intent in VALID_TAGS else "fallback"
        return lang, intent
    except Exception:
        return "en", "fallback"


# ── AI: extract topic from input ──────────────────────────────────────────────
def extract_topic_from_input(user_input):
    """Check if the student named a specific topic (e.g. 'quiz limits')."""
    topic_keywords = {
        "limits":                  ["limit", "limits", "limite", "limites"],
        "continuity":              ["continuity", "continuous", "continuidad"],
        "derivatives":             ["derivative", "derivatives", "derivada", "derivadas", "differentiat"],
        "applications_derivatives":["optimization", "related rates", "mvt", "mean value",
                                    "l'hopital", "lhopital", "concavity", "inflection",
                                    "critical", "monoton", "aplicacion", "optimiz"],
        "integrals":               ["integral", "integrals", "integration", "antiderivative",
                                    "riemann", "ftc", "substitution", "area", "average value",
                                    "integra"]
    }
    text = user_input.lower()
    for tag, keywords in topic_keywords.items():
        if any(kw in text for kw in keywords):
            return tag
    return None


# ── AI: quiz question generation (Sonnet + cultural prompt) ──────────────────
def quiz_by_standard(standard_code, difficulty="medium", language="en"):
    """Generate a quiz question aligned to a specific C-ID MATH 210 standard."""
    if standard_code not in STANDARDS_MAP:
        return {"error": f"Unknown standard: {standard_code}"}

    std = STANDARDS_MAP[standard_code]
    skills_list = "\n".join(f"  - {s}" for s in std["skills"])
    prereqs     = ", ".join(std["algebra_prereqs"])

    connections_block = ""
    for field, example in std["field_connections"].items():
        connections_block += f"  [CONNECTION: {field}]\n  {example}\n\n"

    lang_word = "Spanish" if language == "es" else "English"

    prompt = (
        f"You are a Calculus 1 tutor for California community college students -- "
        f"many are first-generation students heading into engineering, data science, "
        f"health, business, and social justice careers.\n\n"
        f"Generate ONE {difficulty}-level quiz question for this standard:\n\n"
        f"STANDARD: {standard_code} -- {std['topic']}\n"
        f"SKILLS ASSESSED:\n{skills_list}\n"
        f"ALGEBRA PREREQUISITES: {prereqs}\n\n"
        f"AVAILABLE FIELD CONNECTIONS (choose the one that fits most naturally):\n"
        f"{connections_block}\n"
        f"INSTRUCTIONS:\n"
        f"- Write in {lang_word}\n"
        f"- Include [CONNECTION: FieldName] at the start, then one brief context sentence, "
        f"then the mathematical question\n"
        f"- Use LaTeX: $...$ for inline, $$...$$ for display math\n"
        f"- Write ONLY the question, nothing else\n\n"
        f"Question:"
    )

    response = client.messages.create(
        model=SONNET_MODEL,
        max_tokens=400,
        system=CULTURAL_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )
    question_text = response.content[0].text.strip()

    return {
        "question":      question_text,
        "standard_code": standard_code,
        "topic":         std["topic"],
        "unit":          std["unit"],
        "skills":        std["skills"],
        "algebra_prereqs": std["algebra_prereqs"],
        "difficulty":    difficulty,
        "language":      language
    }


# ── AI: grade with mindset messaging (Sonnet) ─────────────────────────────────
def grade_with_mindset(q_dict, student_answer, language="en"):
    """Grade a student answer, detect algebra gaps, inject mindset messages."""
    standard_code = q_dict.get("standard_code", "")
    topic         = q_dict.get("topic", "Calculus")
    skills_str    = "; ".join(q_dict.get("skills", []))
    prereqs_str   = ", ".join(q_dict.get("algebra_prereqs", []))
    lang_word     = "Spanish" if language == "es" else "English"

    prompt = (
        f"You are grading a Calculus 1 student answer. Respond entirely in {lang_word}.\n\n"
        f"Standard: {standard_code} -- {topic}\n"
        f"Skills assessed: {skills_str}\n"
        f"Algebra prerequisites: {prereqs_str}\n\n"
        f"Question: {q_dict['question']}\n"
        f"Student answer: {student_answer}\n\n"
        f"GRADING RUBRIC:\n"
        f"  3 = Fully correct, clear method\n"
        f"  2 = Mostly correct, minor error\n"
        f"  1 = Partial understanding, significant errors\n"
        f"  0 = No demonstrated understanding\n\n"
        f"If the answer reveals algebra gaps (factoring, exponents, fractions, etc.), "
        f"note which skill needs reinforcement.\n\n"
        f"Respond in JSON only (no extra text):\n"
        f"{{\"score\": integer 0-3, \"feedback\": \"one to two sentences\", "
        f"\"algebra_gap\": \"skill name or empty string\", "
        f"\"full_solution\": \"complete step-by-step solution with LaTeX $...$ formatting\"}}"
    )

    response = client.messages.create(
        model=SONNET_MODEL,
        max_tokens=800,
        system=CULTURAL_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip().replace("```json", "").replace("```", "").strip()

    try:
        result = json.loads(raw)
    except Exception:
        result = {"score": 0, "feedback": raw, "algebra_gap": "", "full_solution": ""}

    score = result.get("score", 0)

    if score == 3:
        msg_cat = "correct"
    elif score >= 1:
        msg_cat = "partial"
    else:
        msg_cat = "wrong_but_trying"

    lang_msgs   = GROWTH_MINDSET_MESSAGES[msg_cat].get(language, GROWTH_MINDSET_MESSAGES[msg_cat]["en"])
    mindset_msg = random.choice(lang_msgs)

    if random.random() < 0.33:
        id_msgs     = GROWTH_MINDSET_MESSAGES["identity"].get(language, GROWTH_MINDSET_MESSAGES["identity"]["en"])
        mindset_msg += "\n\n" + random.choice(id_msgs)

    algebra_scaffold = ""
    gap = result.get("algebra_gap", "").lower().strip()
    if gap:
        for skill_key, hint in ALGEBRA_SCAFFOLD_HINTS.items():
            if any(w in gap for w in skill_key.split()):
                algebra_scaffold = hint
                break

    return {
        "score":            score,
        "feedback":         result.get("feedback", ""),
        "algebra_gap":      gap,
        "algebra_scaffold": algebra_scaffold,
        "full_solution":    result.get("full_solution", ""),
        "standard_code":    standard_code,
        "mindset_message":  mindset_msg
    }


# ── AI: open chat tutor response (Sonnet) ─────────────────────────────────────
def get_chat_response(user_input, intent_tag, language="en"):
    """Generate a tutoring reply for an open-ended question."""
    if intent_tag in ["greeting", "goodbye", "thanks", "fallback"]:
        options = CANNED.get(intent_tag, CANNED["fallback"])
        return random.choice(options.get(language, options["en"]))

    std_codes    = INTENT_TO_STANDARDS.get(intent_tag, [])
    topic_label  = intent_tag.replace("_", " ").title()
    lang_word    = "Spanish" if language == "es" else "English"

    context_examples = ""
    if std_codes:
        sample_std = STANDARDS_MAP[std_codes[0]]
        for field, example in list(sample_std["field_connections"].items())[:3]:
            context_examples += f"  [{field}] {example}\n"

    prompt = (
        f"You are a friendly, encouraging Calculus 1 tutor for community college students "
        f"from the Salinas Valley. Respond entirely in {lang_word}.\n\n"
        f"Topic: {topic_label}\n"
        f"Field connections for context (use one naturally if it fits):\n"
        f"{context_examples}\n"
        f"Student question: \"{user_input}\"\n\n"
        f"Respond in 3-5 sentences. Use clear accessible language. "
        f"Include a brief example or formula if helpful using LaTeX $...$ format. "
        f"End with one growth mindset sentence and suggest typing 'quiz' to practice."
    )

    response = client.messages.create(
        model=SONNET_MODEL,
        max_tokens=400,
        system=CULTURAL_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip()


# ── Session state initialization ──────────────────────────────────────────────
def init_session_state():
    """Initialize all Streamlit session state variables on first load."""
    defaults = {
        "screen":           "welcome",   # "welcome" or "chat"
        "student_id":       "",
        "language":         "auto",      # "auto", "en", or "es"
        "difficulty":       "medium",
        "messages":         [],          # list of {role, content, type}
        "quiz_state":       None,        # None or dict when quiz is active
        "session_start":    None,        # time.time() at session start
        "session_score":    0,
        "session_max":      0,
        "session_calls":    0,
        "session_topics":   [],
        "session_standards": [],
        "current_lang":     "en",
        "num_questions":    3,
        "session_ended":    False,
        "usage_saved":      False,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


init_session_state()


# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Import a clean, readable font */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap');

    /* Global type base */
    html, body, [class*="css"] {
        font-family: 'Inter', system-ui, sans-serif;
    }

    /* Page title */
    .app-title {
        font-size: 1.75rem;
        font-weight: 600;
        color: #00796b;
        letter-spacing: -0.02em;
        margin-bottom: 0.1rem;
        line-height: 1.2;
    }

    /* Subtitle / tagline */
    .app-sub {
        font-size: 0.875rem;
        font-weight: 400;
        color: #6b7280;
        letter-spacing: 0.01em;
        margin-bottom: 1.8rem;
    }

    /* Section heading on welcome screen */
    .section-head {
        font-size: 1.05rem;
        font-weight: 500;
        color: #1f2937;
        margin-bottom: 0.75rem;
        padding-bottom: 0.4rem;
        border-bottom: 1px solid #e5e7eb;
    }

    /* Feature description on welcome right column */
    .feature-item {
        margin-bottom: 0.9rem;
        line-height: 1.55;
        font-size: 0.9rem;
        color: #374151;
    }
    .feature-label {
        font-weight: 500;
        color: #00796b;
    }

    /* Unit coverage table */
    .unit-row {
        display: flex;
        justify-content: space-between;
        padding: 0.3rem 0;
        font-size: 0.82rem;
        color: #4b5563;
        border-bottom: 1px solid #f3f4f6;
    }
    .unit-num {
        font-weight: 500;
        color: #00796b;
        min-width: 58px;
    }
    .unit-codes {
        color: #9ca3af;
        font-size: 0.78rem;
    }

    /* Score badges */
    .score-3 { background: #ecfdf5; color: #065f46;
                padding: 3px 10px; border-radius: 9px;
                font-size: 0.82rem; font-weight: 500; }
    .score-2 { background: #fffbeb; color: #92400e;
                padding: 3px 10px; border-radius: 9px;
                font-size: 0.82rem; font-weight: 500; }
    .score-1 { background: #fff7ed; color: #9a3412;
                padding: 3px 10px; border-radius: 9px;
                font-size: 0.82rem; font-weight: 500; }
    .score-0 { background: #fef2f2; color: #991b1b;
                padding: 3px 10px; border-radius: 9px;
                font-size: 0.82rem; font-weight: 500; }

    /* Connection label in quiz questions */
    .connection-tag {
        display: inline-block;
        font-size: 0.7rem;
        font-weight: 500;
        color: #00796b;
        background: #f0fdf9;
        border: 1px solid #99f6e4;
        border-radius: 4px;
        padding: 2px 7px;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        margin-bottom: 0.4rem;
    }

    /* Time label in sidebar */
    .time-label {
        font-size: 0.8rem;
        color: #6b7280;
        line-height: 1.4;
    }

    /* Tone down Streamlit's default h3 in sidebar */
    section[data-testid="stSidebar"] h3 {
        font-size: 0.95rem;
        font-weight: 500;
    }

    /* Reduce default caption boldness */
    .stCaption { color: #6b7280; }
</style>
""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# SCREEN: WELCOME
# ════════════════════════════════════════════════════════════════════════════════
if st.session_state.screen == "welcome":

    # Title
    st.markdown('<p class="app-title">Calculus 1 Tutor &nbsp;|&nbsp; Bilingüe</p>',
                unsafe_allow_html=True)
    st.markdown(
        '<p class="app-sub">C-ID MATH 210 &nbsp;·&nbsp; Hartnell College '
        '&nbsp;·&nbsp; Culturally Responsive</p>',
        unsafe_allow_html=True
    )

    col1, col2 = st.columns([1, 1], gap="large")

    with col1:
        st.markdown('<p class="section-head">Sign in / Iniciar sesión</p>',
                    unsafe_allow_html=True)

        student_id = st.text_input(
            "Name or student ID / Nombre o ID:",
            placeholder="e.g. Maria G. or 12345",
            label_visibility="visible"
        )

        lang_choice = st.selectbox(
            "Language / Idioma:",
            ["Auto-detect / Auto-detección", "English", "Español"]
        )

        col_diff, col_q = st.columns(2)
        with col_diff:
            diff_choice = st.selectbox(
                "Difficulty / Dificultad:",
                ["Easy", "Medium", "Hard"],
                index=1
            )
        with col_q:
            num_q = st.selectbox(
                "Questions / Preguntas:",
                [1, 2, 3, 4, 5],
                index=2
            )

        st.write("")
        start_clicked = st.button(
            "Start session / Comenzar",
            type="primary",
            use_container_width=True
        )

        if start_clicked:
            if not student_id.strip():
                st.warning("Please enter your name or student ID.")
            else:
                sid = student_id.strip()
                # Check weekly limit from session_state usage store
                all_usage = st.session_state.get("all_usage", {})
                current_week = get_current_week()
                record = all_usage.get(sid, {})
                if record.get("week") != current_week:
                    record = {"week": current_week, "minutes_used": 0.0,
                              "sessions": 0, "api_calls": 0,
                              "topics_practiced": [], "standards_practiced": []}

                used = record.get("minutes_used", 0.0)
                remaining = max(0.0, WEEKLY_LIMIT_MINUTES - used)
                over_limit = used >= WEEKLY_LIMIT_MINUTES

                if over_limit:
                    st.error(
                        f"Hi {sid} — you have used your full {WEEKLY_LIMIT_HOURS}-hour "
                        f"weekly limit. Your time resets next week."
                    )
                else:
                    lang_map = {
                        "Auto-detect / Auto-detección": "auto",
                        "English": "en",
                        "Español": "es"
                    }
                    diff_map = {"Easy": "easy", "Medium": "medium", "Hard": "hard"}

                    st.session_state.student_id    = sid
                    st.session_state.language      = lang_map[lang_choice]
                    st.session_state.difficulty    = diff_map[diff_choice]
                    st.session_state.num_questions = num_q
                    st.session_state.session_start = time.time()
                    st.session_state.screen        = "chat"
                    st.session_state.current_lang  = \
                        "es" if st.session_state.language == "es" else "en"

                    lang = st.session_state.current_lang
                    welcome_msg = (
                        f"Hi {sid}! I am your Calculus 1 tutor. "
                        f"You have {format_duration(remaining)} of study time available this week. "
                        f"Ask me any calculus question, or type **quiz** for a practice problem "
                        f"aligned to C-ID MATH 210 standards. Type **bye** when you are done."
                        if lang == "en" else
                        f"Hola {sid}! Soy tu tutor de Cálculo 1. "
                        f"Tienes {format_duration(remaining)} de tiempo disponible esta semana. "
                        f"Pregúntame cualquier cosa de cálculo, o escribe **quiz** para un problema "
                        f"alineado a los estándares C-ID MATH 210. Escribe **bye** cuando termines."
                    )
                    st.session_state.messages.append({
                        "role": "assistant", "content": welcome_msg, "type": "chat"
                    })
                    st.rerun()

    with col2:
        st.markdown('<p class="section-head">About this tutor / Acerca del tutor</p>',
                    unsafe_allow_html=True)

        features = [
            ("Quiz mode",
             "Generates original questions aligned to all 25 C-ID MATH 210 standards. "
             "Each question connects to a real field: engineering, data science, biology, "
             "health, business, or social justice."),
            ("Tutor mode",
             "Ask any Calculus 1 question and receive a step-by-step explanation "
             "with rendered math notation."),
            ("Bilingual",
             "Full support in English and Spanish. Switch languages anytime "
             "by typing /es or /en."),
            ("Weekly limit",
             "Six hours per week per student keeps usage costs sustainable "
             "for the whole class."),
        ]

        for label, desc in features:
            st.markdown(
                f'<div class="feature-item">'
                f'<span class="feature-label">{label}.</span> {desc}'
                f'</div>',
                unsafe_allow_html=True
            )

        st.write("")
        st.markdown('<p class="section-head">C-ID MATH 210 — 25 Standards</p>',
                    unsafe_allow_html=True)

        unit_info = [
            ("Unit 1", "Limits & Continuity",         "S-01 – S-05"),
            ("Unit 2", "Derivatives",                  "S-06 – S-12"),
            ("Unit 3", "Applications of Derivatives",  "S-13 – S-19"),
            ("Unit 4", "Integration",                  "S-20 – S-23"),
            ("Unit 5", "Applications of Integration",  "S-24 – S-25"),
        ]

        for unit, name, codes in unit_info:
            st.markdown(
                f'<div class="unit-row">'
                f'<span class="unit-num">{unit}</span>'
                f'<span>{name}</span>'
                f'<span class="unit-codes">{codes}</span>'
                f'</div>',
                unsafe_allow_html=True
            )


# ════════════════════════════════════════════════════════════════════════════════
# SCREEN: CHAT
# ════════════════════════════════════════════════════════════════════════════════
elif st.session_state.screen == "chat":

    # ── Compute elapsed time and remaining ───────────────────────────────────
    elapsed_min = (time.time() - st.session_state.session_start) / 60 \
                  if st.session_state.session_start else 0.0

    # Get saved usage from session_state store (not file I/O)
    all_usage    = st.session_state.get("all_usage", {})
    current_week = get_current_week()
    saved_record = all_usage.get(st.session_state.student_id, {})
    if saved_record.get("week") != current_week:
        saved_record = {"week": current_week, "minutes_used": 0.0,
                        "sessions": 0, "api_calls": 0,
                        "topics_practiced": [], "standards_practiced": []}

    used_saved = saved_record.get("minutes_used", 0.0)
    total_used = used_saved + elapsed_min
    remaining  = max(0.0, WEEKLY_LIMIT_MINUTES - total_used)
    pct_used   = min(1.0, total_used / WEEKLY_LIMIT_MINUTES)

    # ── SIDEBAR ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown(f"**{st.session_state.student_id}**")
        st.caption(f"Week {get_current_week()}")
        st.divider()

        st.caption("Weekly time")
        st.progress(pct_used)
        st.markdown(
            f'<p class="time-label">'
            f'{format_duration(total_used)} used &nbsp;·&nbsp; '
            f'{format_duration(remaining)} remaining</p>',
            unsafe_allow_html=True
        )
        st.divider()

        st.caption("Session score")
        if st.session_state.session_max > 0:
            pct_score = round(
                (st.session_state.session_score / st.session_state.session_max) * 100
            )
            st.metric(
                label="Points",
                value=f"{st.session_state.session_score}"
                      f"/{st.session_state.session_max}",
                delta=f"{pct_score}%"
            )
        else:
            st.caption("No quiz questions yet.")

        if st.session_state.session_topics:
            st.divider()
            st.caption("Topics this session")
            for t in st.session_state.session_topics:
                st.caption(f"· {t.replace('_', ' ').title()}")

        if st.session_state.session_standards:
            st.caption("Standards: " + ", ".join(st.session_state.session_standards))

        st.divider()
        st.caption("Settings")

        new_diff = st.selectbox(
            "Difficulty",
            ["easy", "medium", "hard"],
            index=["easy", "medium", "hard"].index(st.session_state.difficulty)
        )
        st.session_state.difficulty = new_diff

        new_numq = st.select_slider(
            "Questions per quiz", options=[1, 2, 3, 4, 5],
            value=st.session_state.num_questions
        )
        st.session_state.num_questions = new_numq

        lang_opts  = {"Auto-detect": "auto", "English": "en", "Español": "es"}
        cur_label  = {v: k for k, v in lang_opts.items()}.get(
            st.session_state.language, "Auto-detect"
        )
        new_lang_label = st.selectbox("Language", list(lang_opts.keys()),
                                      index=list(lang_opts.keys()).index(cur_label))
        st.session_state.language = lang_opts[new_lang_label]

        st.divider()
        if st.button("End session", use_container_width=True):
            st.session_state.session_ended = True

        if remaining <= 30 and remaining > 0:
            st.warning(f"Only {format_duration(remaining)} remaining this week.")
        if remaining <= 0:
            st.error("Weekly limit reached.")
            st.session_state.session_ended = True

    # ── Chat messages ────────────────────────────────────────────────────────
    st.markdown(
        '<p class="app-title" style="font-size:1.2rem; margin-bottom:0.25rem;">'
        'Calculus 1 Tutor</p>',
        unsafe_allow_html=True
    )
    st.markdown(
        f'<p class="app-sub" style="margin-bottom:1rem;">'
        f'Hartnell College &nbsp;·&nbsp; C-ID MATH 210</p>',
        unsafe_allow_html=True
    )

    for msg in st.session_state.messages:
        role     = msg["role"]
        content  = msg["content"]
        msg_type = msg.get("type", "chat")

        with st.chat_message(role):
            if msg_type == "question":
                if "[CONNECTION:" in content:
                    parts      = content.split("]", 1)
                    tag_text   = parts[0].replace("[", "").strip()
                    rest       = parts[1].strip() if len(parts) > 1 else ""
                    st.markdown(
                        f'<span class="connection-tag">{tag_text}</span>',
                        unsafe_allow_html=True
                    )
                    st.markdown(rest)
                else:
                    st.markdown(content)

            elif msg_type == "grading":
                score    = msg.get("score", 0)
                feedback = msg.get("feedback", "")
                solution = msg.get("full_solution", "")
                mindset  = msg.get("mindset_message", "")
                scaffold = msg.get("algebra_scaffold", "")
                std_code = msg.get("standard_code", "")

                score_labels = {3: "3 / 3", 2: "2 / 3", 1: "1 / 3", 0: "0 / 3"}
                std_label    = f" &nbsp; {std_code}" if std_code else ""
                st.markdown(
                    f'<span class="score-{score}">{score_labels[score]}</span>'
                    f'{std_label}',
                    unsafe_allow_html=True
                )
                if feedback:
                    st.markdown(feedback)
                if scaffold:
                    st.info(scaffold)
                if solution:
                    with st.expander("Full solution"):
                        st.markdown(solution)
                if mindset:
                    st.success(mindset)

            else:
                st.markdown(content)

    # ── Session ended: show report ────────────────────────────────────────────
    if st.session_state.session_ended and not st.session_state.usage_saved:

        # Save to session_state usage store instead of file
        record = saved_record.copy()
        record["minutes_used"] = used_saved + elapsed_min
        record["sessions"]     = record.get("sessions", 0) + 1
        record["api_calls"]    = record.get("api_calls", 0) + \
                                  st.session_state.session_calls

        for t in st.session_state.session_topics:
            if t not in record.get("topics_practiced", []):
                record.setdefault("topics_practiced", []).append(t)
        for s in st.session_state.session_standards:
            if s not in record.get("standards_practiced", []):
                record.setdefault("standards_practiced", []).append(s)

        if "all_usage" not in st.session_state:
            st.session_state.all_usage = {}
        st.session_state.all_usage[st.session_state.student_id] = record
        st.session_state.usage_saved = True

        used_now = record["minutes_used"]
        rem_now  = max(0.0, WEEKLY_LIMIT_MINUTES - used_now)

        score_str = (
            f"{st.session_state.session_score}/{st.session_state.session_max} "
            f"({round((st.session_state.session_score / st.session_state.session_max)*100)}%)"
            if st.session_state.session_max > 0 else "--"
        )

        st.divider()
        st.markdown("**Session report**")

        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Duration", format_duration(elapsed_min))
            st.metric("Quiz score", score_str)
        with c2:
            st.metric("Weekly time used", format_duration(used_now))
            st.metric("Weekly time left", format_duration(rem_now))
        with c3:
            st.metric("Sessions this week", record["sessions"])

        if st.session_state.session_topics:
            st.caption(
                "Topics covered: " +
                ", ".join(t.replace("_", " ").title()
                           for t in st.session_state.session_topics)
            )
        if st.session_state.session_standards:
            st.caption("Standards: " +
                       ", ".join(st.session_state.session_standards))

        lang = st.session_state.current_lang
        id_msgs = GROWTH_MINDSET_MESSAGES["identity"].get(
            lang, GROWTH_MINDSET_MESSAGES["identity"]["en"]
        )
        st.success(random.choice(id_msgs))

        if st.button("Start a new session"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    # ── Chat input ────────────────────────────────────────────────────────────
    elif not st.session_state.session_ended:
        user_input = st.chat_input("Ask anything, or type 'quiz' / 'bye'")

        if user_input:
            # Detect language for this turn
            if st.session_state.language == "auto":
                lang, intent_tag = detect_language_and_intent(user_input)
            elif st.session_state.language == "es":
                lang = "es"
                _, intent_tag = detect_language_and_intent(user_input)
            else:
                lang = "en"
                _, intent_tag = detect_language_and_intent(user_input)

            st.session_state.current_lang  = lang
            st.session_state.session_calls += 1

            st.session_state.messages.append({
                "role": "user", "content": user_input, "type": "chat"
            })

            # ── QUIZ ANSWER MODE ──────────────────────────────────────────────
            if st.session_state.quiz_state is not None:
                qs = st.session_state.quiz_state

                grading = grade_with_mindset(qs["current_question"], user_input, lang)
                st.session_state.session_calls += 1
                st.session_state.session_score += grading["score"]
                st.session_state.session_max   += 3
                qs["scores"].append(grading["score"])

                std_code = grading.get("standard_code", "")
                if std_code and std_code not in st.session_state.session_standards:
                    st.session_state.session_standards.append(std_code)

                st.session_state.messages.append({
                    "role":             "assistant",
                    "content":          grading["feedback"],
                    "type":             "grading",
                    "score":            grading["score"],
                    "feedback":         grading["feedback"],
                    "full_solution":    grading["full_solution"],
                    "mindset_message":  grading["mindset_message"],
                    "algebra_scaffold": grading.get("algebra_scaffold", ""),
                    "standard_code":    std_code
                })

                qs["q_num"] += 1

                if qs["q_num"] <= qs["num_questions"]:
                    topic      = qs.get("topic")
                    pool       = INTENT_TO_STANDARDS.get(topic, list(STANDARDS_MAP.keys())) \
                                 if topic else list(STANDARDS_MAP.keys())
                    next_code  = random.choice(pool)
                    next_q     = quiz_by_standard(next_code,
                                                  st.session_state.difficulty, lang)
                    st.session_state.session_calls += 1
                    qs["current_question"] = next_q

                    q_header = (
                        f"**Question {qs['q_num']} of {qs['num_questions']}"
                        f" &nbsp;|&nbsp; {next_code}: {next_q['topic']}**\n\n"
                        f"*Prerequisites: {', '.join(next_q['algebra_prereqs'])}*\n\n"
                        + next_q["question"]
                    )
                    st.session_state.messages.append({
                        "role": "assistant", "content": q_header, "type": "question"
                    })
                else:
                    total = sum(qs["scores"])
                    max_s = len(qs["scores"]) * 3
                    pct   = round((total / max_s) * 100) if max_s > 0 else 0
                    done_msg = (
                        f"Quiz complete — {total}/{max_s} ({pct}%). "
                        f"Type 'quiz' for another round, or ask me any calculus question."
                        if lang == "en" else
                        f"Quiz terminado — {total}/{max_s} ({pct}%). "
                        f"Escribe 'quiz' para otra ronda, o hazme cualquier pregunta de cálculo."
                    )
                    st.session_state.messages.append({
                        "role": "assistant", "content": done_msg, "type": "chat"
                    })
                    st.session_state.quiz_state = None

            # ── CHAT / COMMAND MODE ───────────────────────────────────────────
            else:
                if intent_tag == "goodbye":
                    farewell = random.choice(
                        CANNED["goodbye"].get(lang, CANNED["goodbye"]["en"])
                    )
                    st.session_state.messages.append({
                        "role": "assistant", "content": farewell, "type": "chat"
                    })
                    st.session_state.session_ended = True

                elif intent_tag == "quiz_request":
                    topic = extract_topic_from_input(user_input)
                    if topic and topic not in st.session_state.session_topics:
                        st.session_state.session_topics.append(topic)

                    pool       = INTENT_TO_STANDARDS.get(topic, list(STANDARDS_MAP.keys())) \
                                 if topic else list(STANDARDS_MAP.keys())
                    first_code = random.choice(pool)
                    first_q    = quiz_by_standard(first_code,
                                                   st.session_state.difficulty, lang)
                    st.session_state.session_calls += 1
                    num_q = st.session_state.num_questions

                    q_header = (
                        f"**Question 1 of {num_q}"
                        f" &nbsp;|&nbsp; {first_code}: {first_q['topic']}**\n\n"
                        f"*Prerequisites: {', '.join(first_q['algebra_prereqs'])}*\n\n"
                        + first_q["question"]
                    )
                    st.session_state.messages.append({
                        "role": "assistant", "content": q_header, "type": "question"
                    })
                    st.session_state.quiz_state = {
                        "current_question": first_q,
                        "q_num":            2,
                        "num_questions":    num_q,
                        "topic":            topic,
                        "scores":           []
                    }

                else:
                    if intent_tag not in ["greeting", "goodbye", "thanks",
                                          "fallback", "quiz_request"] and \
                       intent_tag not in st.session_state.session_topics:
                        st.session_state.session_topics.append(intent_tag)

                    response = get_chat_response(user_input, intent_tag, lang)
                    st.session_state.session_calls += 1
                    st.session_state.messages.append({
                        "role": "assistant", "content": response, "type": "chat"
                    })

            st.rerun()
