"""The self-test instruments, seeded into the `test` table on boot.

All are standard, freely usable screens:
  - Stress Level Test  -> Perceived Stress Scale (PSS-10), Cohen et al.
  - Self-Esteem Test   -> Rosenberg Self-Esteem Scale (RSES)
  - Depression Test    -> PHQ-9 (the screen used by Mental Health America)
  - Suicide Risk Check -> adapted from the SWSPHN Clinical Suicide Risk
                          Screening Tool (self-administered wording)

Each question carries its own option values, so reverse-scored items are just
options with reversed values — the scorer in routes.py simply sums the chosen
values and looks the total up in `scoring.bands`.
"""


def _opts(labels, values):
    return [{"label": l, "value": v} for l, v in zip(labels, values)]


# ---------------- Stress Level Test (PSS-10) ----------------
_PSS_LABELS = ["Never", "Almost never", "Sometimes", "Fairly often", "Very often"]
_PSS = _opts(_PSS_LABELS, [0, 1, 2, 3, 4])
_PSS_R = _opts(_PSS_LABELS, [4, 3, 2, 1, 0])  # reverse-scored items

_STRESS_QUESTIONS = [
    ("been upset because of something that happened unexpectedly?", _PSS),
    ("felt that you were unable to control the important things in your life?", _PSS),
    ("felt nervous and stressed?", _PSS),
    ("felt confident about your ability to handle your personal problems?", _PSS_R),
    ("felt that things were going your way?", _PSS_R),
    ("found that you could not cope with all the things that you had to do?", _PSS),
    ("been able to control irritations in your life?", _PSS_R),
    ("felt that you were on top of things?", _PSS_R),
    ("been angered because of things that were outside of your control?", _PSS),
    ("felt difficulties were piling up so high that you could not overcome them?", _PSS),
]

# ---------------- Self-Esteem Test (Rosenberg) ----------------
_RSES_LABELS = ["Strongly agree", "Agree", "Disagree", "Strongly disagree"]
_RSES_POS = _opts(_RSES_LABELS, [3, 2, 1, 0])
_RSES_NEG = _opts(_RSES_LABELS, [0, 1, 2, 3])  # reverse-scored items

_ESTEEM_QUESTIONS = [
    ("On the whole, I am satisfied with myself.", _RSES_POS),
    ("At times I think I am no good at all.", _RSES_NEG),
    ("I feel that I have a number of good qualities.", _RSES_POS),
    ("I am able to do things as well as most other people.", _RSES_POS),
    ("I feel I do not have much to be proud of.", _RSES_NEG),
    ("I certainly feel useless at times.", _RSES_NEG),
    ("I feel that I am a person of worth, at least on an equal plane with others.", _RSES_POS),
    ("I wish I could have more respect for myself.", _RSES_NEG),
    ("All in all, I am inclined to feel that I am a failure.", _RSES_NEG),
    ("I take a positive attitude toward myself.", _RSES_POS),
]

# ---------------- Depression Test (PHQ-9) ----------------
_PHQ = _opts(["Not at all", "Several days", "More than half the days",
              "Nearly every day"], [0, 1, 2, 3])

_DEPRESSION_QUESTIONS = [
    ("Little interest or pleasure in doing things", _PHQ),
    ("Feeling down, depressed, or hopeless", _PHQ),
    ("Trouble falling or staying asleep, or sleeping too much", _PHQ),
    ("Feeling tired or having little energy", _PHQ),
    ("Poor appetite or overeating", _PHQ),
    ("Feeling bad about yourself — or that you are a failure or have let "
     "yourself or your family down", _PHQ),
    ("Trouble concentrating on things, such as reading or watching TV", _PHQ),
    ("Moving or speaking so slowly that other people could have noticed — or "
     "the opposite, being so fidgety or restless that you have been moving "
     "around a lot more than usual", _PHQ),
    ("Thoughts that you would be better off dead, or of hurting yourself in "
     "some way", _PHQ),
]

# ---------------- Suicide Risk Check (adapted from SWSPHN) ----------------
# Source: SWSPHN Clinical Suicide Risk Assessment screening tool. The original
# is a clinician-administered 6-section checklist scored by counting ticks:
# Low 0-1, Medium 2-3, High 4-6, and Emergency when a plan is immediate /
# within 24 hours. This adaptation keeps the six sections as six
# self-administered questions with the same count-based scoring; the
# "immediate plan" answer carries value 10 so it always lands in the
# Emergency band regardless of the other answers.
_YN = _opts(["No", "Yes"], [0, 1])
_YN_R = _opts(["Yes", "No"], [0, 1])  # protective factors: their ABSENCE scores

_SUICIDE_HELPLINES = (
    "Befrienders KL 03-7627 2929 (24 hours) · US: call or text 988 · "
    "UK & ROI: Samaritans 116 123 — or your local emergency number if you "
    "are in immediate danger."
)

_SUICIDE_QUESTIONS = [
    {"text": "Have things been so bad lately that you have thought about "
             "suicide?",
     "options": _YN},
    {"text": "Have you made any plans to take your own life?",
     "options": _opts(
         ["No",
          "Yes — but not right away",
          "Yes — I could act on it now or within the next 24 hours"],
         [0, 1, 10])},
    {"text": "Have you ever tried to take your own life before?",
     "options": _YN},
    {"text": "Have you been going through upsetting events lately? "
             "(a breakup, family conflict, losing a job, abuse, legal "
             "trouble, chronic pain or illness, grief, trauma)",
     "options": _YN},
    {"text": "Do you have people who support you? (family, friends, a "
             "partner, a doctor, a counsellor or health worker)",
     "options": _YN_R},
    {"text": "Do you have ways of coping that have helped you through tough "
             "times before? (reasons to live, strategies that worked in past "
             "crises, personal strengths)",
     "options": _YN_R},
]

TESTS = [
    {
        "slug": "stress-level-test",
        "title": "Stress Level Test",
        "description": (
            "The Perceived Stress Scale (PSS-10). Thinking about the LAST MONTH, "
            "choose how often you felt or thought each of the following."
        ),
        "source": "Psycom",
        "reference": "https://www.psycom.net/stress-test",
        "questions": [
            {"text": "In the last month, how often have you " + text, "options": opts}
            for text, opts in _STRESS_QUESTIONS
        ],
        "scoring": {
            "max": 40,
            "bands": [
                {"min": 0, "max": 13, "label": "Low stress",
                 "advice": "Your stress level looks manageable right now. Keep up the "
                           "habits that are working for you — steady sleep, breaks and "
                           "time with people you like."},
                {"min": 14, "max": 26, "label": "Moderate stress",
                 "advice": "You're carrying a noticeable amount of stress. Small daily "
                           "recovery habits make a real difference — try the Calm Down "
                           "Exercises on this page, and be deliberate about breaks and "
                           "sleep."},
                {"min": 27, "max": 40, "label": "High stress",
                 "advice": "Your stress load is heavy right now. Please be kind to "
                           "yourself — ease what you can, use the calming exercises "
                           "here, and consider talking it through with someone you "
                           "trust or the campus counselling service."},
            ],
        },
    },
    {
        "slug": "self-esteem-test",
        "title": "Self-Esteem Test",
        "description": (
            "The Rosenberg Self-Esteem Scale. Choose how much you agree with each "
            "statement about yourself. Answer with your first honest reaction."
        ),
        "source": "Psychology Today",
        "reference": "https://www.psychologytoday.com/intl/tests/personality/self-esteem-test",
        "questions": [
            {"text": text, "options": opts} for text, opts in _ESTEEM_QUESTIONS
        ],
        "scoring": {
            "max": 30,
            "bands": [
                {"min": 0, "max": 14, "label": "Low self-esteem",
                 "advice": "Your inner critic may be louder than it deserves to be. "
                           "The Self-Compassion ideas in this app can help you speak "
                           "to yourself more fairly — and a counsellor can help you "
                           "work on this; it responds well to support."},
                {"min": 15, "max": 25, "label": "Healthy range",
                 "advice": "Your self-esteem is in the healthy range. Everyone has "
                           "harsher days — treating yourself like you'd treat a good "
                           "friend keeps it steady."},
                {"min": 26, "max": 30, "label": "High self-esteem",
                 "advice": "You have a strong sense of your own worth. That's a real "
                           "asset — it helps you handle setbacks and speak up for "
                           "yourself."},
            ],
        },
    },
    {
        "slug": "depression-test",
        "title": "Depression Test",
        "description": (
            "The PHQ-9 — the same screen used by Mental Health America. Over the "
            "LAST 2 WEEKS, how often have you been bothered by each of the "
            "following problems?"
        ),
        "source": "Mental Health America",
        "reference": "https://screening.mhanational.org/screening-tools/depression/",
        "questions": [
            {"text": text, "options": opts} for text, opts in _DEPRESSION_QUESTIONS
        ],
        "scoring": {
            "max": 27,
            "bands": [
                {"min": 0, "max": 4, "label": "Minimal depression",
                 "advice": "Your answers suggest minimal signs of depression right "
                           "now. Keep doing what works — sleep, movement, connection "
                           "— and check in with yourself now and then."},
                {"min": 5, "max": 9, "label": "Mild depression",
                 "advice": "Your answers suggest mild symptoms. Gentle, repeatable "
                           "steps help: a little daylight, one small activity a day, "
                           "staying in touch with people. If this lasts more than two "
                           "weeks, consider talking to a counsellor."},
                {"min": 10, "max": 14, "label": "Moderate depression",
                 "advice": "Your answers suggest moderate symptoms. Talking to the "
                           "campus counselling service or another professional is a "
                           "good next step — support genuinely helps."},
                {"min": 15, "max": 19, "label": "Moderately severe depression",
                 "advice": "Your answers suggest moderately severe symptoms. Please "
                           "consider reaching out to a counsellor or doctor soon. You "
                           "deserve support, and this is very treatable."},
                {"min": 20, "max": 27, "label": "Severe depression",
                 "advice": "Your answers suggest severe symptoms. Please reach out to "
                           "a professional as soon as you can — the campus counselling "
                           "service, a doctor, or a helpline. You don't have to face "
                           "this alone."},
            ],
            # PHQ-9 item 9 asks about thoughts of self-harm: any answer above
            # "Not at all" always surfaces crisis contacts with the result.
            "alert_question": 8,
            "alert_min": 1,
            "alert_message": (
                "You mentioned thoughts of self-harm. You don't have to carry that "
                "alone — please reach out now: Befrienders KL 03-7627 2929 (24 hours), "
                "or your local emergency number if you're in immediate danger."
            ),
        },
    },
    {
        "slug": "suicide-risk-check",
        "title": "Suicide Risk Check",
        "description": (
            "A short check adapted from the SWSPHN Clinical Suicide Risk "
            "Screening Tool. Answer honestly about how things are for you "
            "RIGHT NOW. If you are in immediate danger, don't finish the "
            "quiz — call your local emergency number straight away."
        ),
        "source": "SWSPHN Clinical Suicide Risk Assessment",
        "reference": ("https://swsphn.com.au/wp-content/uploads/2022/02/"
                      "SWSPHN-Clinical-Suicide-Risk-Assessment-Word-pdf.pdf"),
        "questions": _SUICIDE_QUESTIONS,
        "scoring": {
            "max": 15,
            "bands": [
                {"min": 0, "max": 1, "label": "Low risk",
                 "advice": "Your answers suggest a low level of risk right now. "
                           "Keep checking in with yourself, and hold on to the "
                           "people and coping strategies that support you. If "
                           "things change, help is always there: " + _SUICIDE_HELPLINES},
                {"min": 2, "max": 3, "label": "Medium risk",
                 "advice": "Your answers suggest a medium level of risk. Please "
                           "don't carry this alone — talk to a counsellor, your "
                           "doctor, or someone you trust as soon as you can, and "
                           "keep a helpline within reach: " + _SUICIDE_HELPLINES},
                {"min": 4, "max": 6, "label": "High risk",
                 "advice": "Your answers suggest a high level of risk. Please "
                           "reach out TODAY — a counsellor, your doctor, or a "
                           "crisis line: " + _SUICIDE_HELPLINES + " Try not to "
                           "be alone right now, and consider telling someone "
                           "near you how you're feeling."},
                {"min": 7, "max": 15, "label": "Emergency",
                 "advice": "You said you could act on a plan now or within the "
                           "next 24 hours. Please treat this as an emergency: "
                           "do not stay alone, remove anything you could use to "
                           "hurt yourself, and call your local emergency number "
                           "or go to the nearest emergency department now. "
                           + _SUICIDE_HELPLINES},
            ],
            # This screen ALWAYS surfaces the counsellor / helpline block with
            # the result (shown before the score), whatever the answers were.
            "alert_always": True,
            "alert_message": (
                "If you are having thoughts of suicide, please talk to someone "
                "now — you deserve support: " + _SUICIDE_HELPLINES
            ),
        },
    },
]
