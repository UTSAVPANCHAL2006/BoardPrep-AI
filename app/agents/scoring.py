"""Deterministic scoring rules for the mock interview. No LLM here, so every rule is testable.

The rule that matters most: an answer that was never given scores 0. "skip", "pass", "pata nahi" or silence
is caught by code BEFORE any model sees it, and a report can never lift it with a floor. A score is also
capped by how much of the interview was actually answered, and a phase that was never reached is
"not assessed" (None), never a made-up 5.
"""

import math
import re

SCORE_KEYS = (
    "clarity",
    "structure",
    "daf_consistency",
    "subject_depth",
    "current_affairs",
    "confidence",
)

# A dimension that belongs to one phase is judged only from that phase's answers.
PHASE_OF_SCORE = {"subject_depth": "subject_probe", "current_affairs": "current_affairs"}

# Whole-answer phrases that mean "no answer" (English, Hinglish, Hindi). Matched against the WHOLE answer,
# so "I don't know the exact figure, but..." is still a real answer. "No", "none" and "nothing" are left out:
# they can be honest answers to a yes/no question.
SKIP_PHRASES = [
    r"skip(?: (?:it|this|this one|question|karo|kar do|kijiye|करो|कर दो|कीजिए))?",  # speech-to-text mixes scripts
    r"pass",
    r"next(?: question| one)?",
    r"move on",
    r"no idea",
    r"no comments?",
    r"idk",
    r"(?:i )?(?:do not|don ?t|dont) know",
    r"(?:i am |i m )?not sure",
    r"(?:i )?(?:can ?not|cannot|can ?t) (?:say|answer|tell)",
    r"(?:mujhe |muje )?(?:pata|maloom|malum) nahi(?: hai)?",
    r"(?:mujhe |muje )?nahi (?:pata|maloom|malum)(?: hai)?",
    r"(?:chhodo|chodo|chhod do|chod do)",
    r"(?:agla|next) (?:sawal|sawaal|question)",
    r"aage (?:badho|chalo)",
    r"(?:मुझे )?पता नहीं(?: है)?",
    r"नहीं पता(?: है)?",
    r"(?:मुझे )?मालूम नहीं(?: है)?",
    r"छोड़(?:ो|िए| दो)?",
    # speech-to-text often writes spoken English in Devanagari
    r"स्किप(?: करो| कीजिए| कर दो)?",
    r"पास",
    r"नेक्स्ट(?: क्वेश्चन)?",
    r"(?:आई )?(?:डोंट|डोन्ट) नो",
    r"नो आइडिया",
    r"अगला (?:सवाल|प्रश्न)",
]
POLITE_WORDS = r"(?:sir|ma ?am|madam|please|plz|sorry|ji|ok|okay|sir ji)"
SKIP_ANSWER = re.compile(
    rf"^(?:{POLITE_WORDS} )*(?:{'|'.join(SKIP_PHRASES)})(?: (?:{POLITE_WORDS}|{'|'.join(SKIP_PHRASES)}))*$",  # 'skip karo next question please'
    re.IGNORECASE,
)


def normalise(text: str) -> str:
    """Lowercase, punctuation to spaces, single spaces: 'Skip!!  Sir.' -> 'skip sir'."""
    text = re.sub(r"[^\w\sऀ-ॿ]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", text).strip()


# Text addressed to the grader, not the board: it earns nothing, whatever the model would have made of it.
INSTRUCTION_TO_GRADER = re.compile(
    r"(ignore|disregard|forget) (all |the |your |any )?(previous|above|prior|earlier|system)? ?(instructions|prompts?|rules)"
    r"|(give|award|score|rate|mark) (me|this|this answer|my answers?) (a |an )?(10|ten|full|perfect|maximum|max|high)"
    r"|(10|ten) out of (10|ten)|10 ?/ ?10|you are now|system prompt|act as (the |an? )?(examiner|evaluator|grader)",
    re.IGNORECASE,
)
VOWEL = re.compile(r"[aeiouy\u0900-\u097F]", re.IGNORECASE)
CONSONANT_RUN = re.compile(r"[bcdfghjklmnpqrstvwxz]{5,}", re.IGNORECASE)


KEYBOARD_ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm")


def isKeyboardRun(word: str) -> bool:
    """'asdf', 'qwer', 'zxcv', 'lkjh': letters typed straight along one keyboard row."""
    word = word.lower()
    return len(word) >= 3 and any(word in row or word in row[::-1] for row in KEYBOARD_ROWS)


def isGibberish(text: str) -> bool:
    """Keyboard mashing: most 'words' have no vowel, a run of 5+ consonants, or run along one keyboard row."""
    words = re.findall(r"[^\W\d_]+", text)
    if not words:
        return True  # only digits or symbols
    odd = [
        word
        for word in words
        if len(word) > 1 and (not VOWEL.search(word) or CONSONANT_RUN.search(word) or isKeyboardRun(word))
    ]
    return len(odd) * 2 > len(words)


# 'your hometown' read back as 'my hometown' is still the question.
SAME_PERSON = {"my": "your", "i": "you", "me": "you", "mine": "yours", "am": "are"}


def repeatsQuestion(answer: str, question: str) -> bool:
    """The question read back (or copied) is not an answer: nearly every word of it comes from the question."""
    answer_words = [SAME_PERSON.get(word, word) for word in normalise(answer).split()]
    question_words = {SAME_PERSON.get(word, word) for word in normalise(question).split()}
    if len(answer_words) < 4 or not question_words:
        return False
    copied = sum(1 for word in answer_words if word in question_words)
    return copied / len(answer_words) >= 0.85 and len(answer_words) <= len(question_words) + 3


FILLER_WORDS = {"yes", "no", "yeah", "yep", "nope", "sir", "maam", "ma", "am", "madam", "ok", "okay", "hmm", "hm",
                "sure", "maybe", "right", "fine", "haan", "han", "ji", "nahi", "na", "theek", "hai", "thik", "accha", "achha",
                "thank", "thanks", "you"}  # fmt: skip
OPEN_QUESTION = re.compile(r"^\s*(what|how|why|which|where|when|who|describe|explain|tell|share|discuss|elaborate|in what)\b", re.IGNORECASE)


def isFillerReply(answer: str, question: str) -> bool:
    """'Yes sir.' to 'What motivates you?' says nothing. To 'Do you play any sport?' a 'No' is a real answer."""
    words = normalise(answer).split()
    return bool(words) and all(word in FILLER_WORDS for word in words) and bool(OPEN_QUESTION.search(question or ""))


NUMBER_QUESTION = re.compile(r"\b(when|which year|what year|how many|how much|how old|age|number|percent|rank|marks|score)\b", re.IGNORECASE)


def classifyNonAnswer(answer: str, question: str = "") -> str | None:
    """Why this is not an answer ('empty', 'skipped', 'gibberish', 'repeated_question', 'instruction_to_grader'),
    or None for a real answer, which the model then judges."""
    text = normalise(answer)
    if not text:
        return "empty"
    if INSTRUCTION_TO_GRADER.search(answer or ""):
        return "instruction_to_grader"
    if isGibberish(text) and not (text.replace(" ", "").isdigit() and NUMBER_QUESTION.search(question or "")):
        return "gibberish"  # '2019' to 'When did you graduate?' is an answer, not mashing
    if question and repeatsQuestion(answer, question):
        return "repeated_question"
    if isFillerReply(answer, question):
        return "no_content"
    # "skip skip", "pass. next question", "skip करो। next question please।" - every piece is a skip phrase
    sentences = [normalise(part) for part in re.split(r"[.!?।]+", answer or "")]
    pieces = [piece for sentence in sentences for piece in re.split(r"\b(?:and|then|aur)\b", sentence) if piece.strip()]
    if pieces and all(SKIP_ANSWER.match(piece.strip()) for piece in pieces):
        return "skipped"
    if SKIP_ANSWER.match(text):
        return "skipped"
    return None


def isSubstantive(entry: dict) -> bool:
    """A turn that can earn marks: an answer was given and it was on the question."""
    return not entry.get("non_answer") and entry.get("clarity") != "off_topic" and bool((entry.get("answer") or "").strip())


def coverageCap(evaluation_log: list[dict]) -> int:
    """Answering 3 of 12 questions can never look like a strong interview: the best score is 10 x the share answered."""
    if not evaluation_log:
        return 0
    answered = sum(1 for entry in evaluation_log if isSubstantive(entry))
    return math.ceil(10 * answered / len(evaluation_log))


def calibrateFeedbackScores(report: dict, evaluation_log: list[dict], daf_flags: list) -> dict:
    """Make the model's scores honest: 0 for what was not answered, capped by coverage, None for phases never
    reached. Fair floors still apply, but only from answers that were really given."""
    raw = dict(report.get("scores") or {})
    answered = [entry for entry in evaluation_log if isSubstantive(entry)]
    cap = coverageCap(evaluation_log)
    phases_seen = {entry.get("phase") for entry in evaluation_log}
    clear_count = sum(1 for entry in answered if entry.get("clarity") == "clear")

    scores: dict[str, int | None] = {}
    for key in SCORE_KEYS:
        phase = PHASE_OF_SCORE.get(key)
        if phase and phase not in phases_seen:
            scores[key] = None  # never asked: not assessed, not a free 5
            continue
        phase_answers = [entry for entry in answered if not phase or entry.get("phase") == phase]
        if not phase_answers:
            scores[key] = 0  # asked, but nothing was answered
            continue
        value = parseScore(raw.get(key))
        if value is None:
            value = deriveScore(phase_answers)  # the model left it out or wrote something unreadable
        if len(answered) >= 3 and key in ("clarity", "structure", "confidence"):
            value = max(value, 5 if clear_count >= len(answered) // 2 else 4)  # fair floor for real answers
        if key == "daf_consistency":
            value = min(value, dafConsistencyCap(len(daf_flags))) if daf_flags else max(value, 7)
        scores[key] = max(0, min(value, cap, 10))

    report["scores"] = scores
    report["coverage"] = {"answered": len(answered), "asked": len(evaluation_log), "max_score": cap}
    alignNotesWithScores(report, evaluation_log)
    missed = len(evaluation_log) - len(answered)
    if answered and missed:
        # The summary must not read like a full interview when questions were skipped.
        lead = (
            f"You answered {len(answered)} of {len(evaluation_log)} questions; the {missed} you skipped "
            f"or answered off-topic score 0, so no score here can go above {cap}/10."
        )
        report["overall_summary"] = f"{lead} {report.get('overall_summary') or ''}".strip()
    return report


NOTE_OF_SCORE = {"daf_consistency": "daf_consistency", "subject_depth": "subject_depth", "current_affairs": "current_affairs_awareness"}
PHASE_NAMES = {"daf_opening": "DAF", "subject_probe": "subject", "current_affairs": "current-affairs", "closing": "closing"}


def alignNotesWithScores(report: dict, evaluation_log: list[dict]) -> None:
    """A note must never praise what scored 0: for a dimension or phase with no real answer, code writes the note."""
    scores = report.get("scores") or {}
    for key, note in NOTE_OF_SCORE.items():
        if key in scores and scores[key] is None:
            report[note] = "Not reached in this mock, so it was not assessed."
        elif key in scores and scores[key] == 0:
            report[note] = "You did not give a real answer here, so this could not be shown and scores 0."
    breakdown = dict(report.get("phase_breakdown") or {})
    for phase in list(breakdown):
        turns = [entry for entry in evaluation_log if entry.get("phase") == phase]
        if not turns:
            breakdown.pop(phase)  # never asked: no made-up commentary
        elif not any(isSubstantive(entry) for entry in turns):
            breakdown[phase] = f"You did not give a real answer to the {PHASE_NAMES.get(phase, phase)} question(s), so this phase scores 0."
    if "phase_breakdown" in report:
        report["phase_breakdown"] = breakdown


def buildNoAnswerReport(evaluation_log: list[dict]) -> dict:
    """Nothing was answered: the report says so plainly. No model is asked to find strengths that do not exist."""
    asked = len(evaluation_log)
    report = {
        "overall_summary": (
            f"You did not answer any of the {asked} questions, so there is nothing to assess yet. "
            "A board scores what you say: even a short, honest answer earns more than a skip."
        ),
        "strengths": [],
        "improvements": [
            "Answer every question, even briefly: state your view in one line, give one reason, and one example.",
            "If you do not know a fact, say so and then share how you would find out or what you do know nearby.",
        ],
        "priority_actions": [
            "Retry this mock and answer at least the DAF questions about yourself — they need no preparation.",
        ],
        "daf_consistency": "",
        "subject_depth": "",
        "current_affairs_awareness": "",
        "question_feedback": [skippedTurnFeedback(index, entry) for index, entry in enumerate(evaluation_log, 1)],
        "scores": {},
    }
    return calibrateFeedbackScores(report, evaluation_log, [])


def addCoaching(rules_report: dict, coach_report: dict | None, evaluation_log: list[dict]) -> dict:
    """Nothing was answered, but the candidate still deserves coaching. The model's advice (improvements, priority
    actions, per-question 'better answer') is added to the rules report; scores, summary and strengths stay
    fixed by rule, so silence can never be praised or scored."""
    if not coach_report:
        return rules_report
    for key in ("improvements", "priority_actions"):
        advice = [str(item) for item in coach_report.get(key) or [] if str(item).strip()]
        if advice:
            rules_report[key] = advice
    rules_report["question_feedback"] = coach_report.get("question_feedback") or []
    return groundQuestionFeedback(rules_report, evaluation_log)


NON_ANSWER_REASONS = {
    "empty": "No answer was given, so this question scores 0.",
    "skipped": "No answer was given, so this question scores 0.",
    "gibberish": "This was not a readable answer, so this question scores 0.",
    "repeated_question": "Repeating the question is not an answer, so this question scores 0.",
    "no_content": "A reply like 'Yes sir' does not answer an open question, so this question scores 0.",
    "instruction_to_grader": "Answers are judged only on what you say to the board; instructions to the grader "
    "are ignored, so this question scores 0.",
}

# Shortest answer a board would count as a real reply to an open question.
MIN_CLEAR_WORDS = 5


def capClarityForLength(clarity: str, answer: str) -> str:
    """'Yes' or 'Jaipur' to an open question is never a clear answer, whatever the model says."""
    if clarity == "clear" and len(normalise(answer).split()) < MIN_CLEAR_WORDS:
        return "vague"
    return clarity


def skippedTurnFeedback(turn: int, entry: dict) -> dict:
    return {
        "turn": turn,
        "question": entry.get("question", ""),
        "status": "skipped",
        "quote": "",
        "what_worked": "",
        "improve": NON_ANSWER_REASONS.get(entry.get("non_answer") or "", NON_ANSWER_REASONS["skipped"]),
        "better_answer": "",
    }


def quoteInAnswer(quote: str, answer: str) -> bool:
    """A quote counts only if the candidate really said it (ignoring case and punctuation)."""
    quote, answer = normalise(quote), normalise(answer)
    return len(quote) >= 3 and quote in answer


def groundQuestionFeedback(report: dict, evaluation_log: list[dict], profile: dict | None = None) -> dict:
    """One feedback row per question, tied to the candidate's own words. Code decides the status of each turn;
    a quote the candidate never said is removed, and praise without a real quote is dropped."""
    written = {}
    for item in report.get("question_feedback") or []:
        try:
            written[int(item.get("turn"))] = item
        except (TypeError, ValueError):
            continue
    rows = []
    for turn, entry in enumerate(evaluation_log, 1):
        if not isSubstantive(entry):
            # Zero by rule, but still coached: how to handle the question and what a strong answer covers.
            row = skippedTurnFeedback(turn, entry)
            if entry.get("clarity") == "off_topic" and not entry.get("non_answer"):
                row["status"] = "off_topic"
                row["improve"] = "This answer did not address the question, so it earns no marks."
            coaching = str((written.get(turn) or {}).get("improve") or "").strip()
            if coaching:
                row["improve"] = f"{row['improve']} {coaching}"
            row["better_answer"] = str((written.get(turn) or {}).get("better_answer") or "")
            rows.append(row)
            continue
        item = written.get(turn) or {}
        answer = entry.get("answer") or ""
        quote = str(item.get("quote") or "")
        grounded = quoteInAnswer(quote, answer) and len(normalise(quote).split()) >= MIN_CLEAR_WORDS
        rows.append(
            {
                "turn": turn,
                "question": entry.get("question", ""),
                "status": "answered",
                "quote": shortenQuote(quote) if grounded else "",
                "what_worked": toSecondPerson(str(item.get("what_worked") or "")) if grounded else "",
                "improve": toSecondPerson(str(item.get("improve") or entry.get("notes") or "")),
                "better_answer": str(item.get("better_answer") or ""),
                "checklist": verifyChecklist(item.get("checklist"), answer, profile),
                "length": judgeLength(answer),
            }
        )
    report["question_feedback"] = rows
    for key in ("overall_summary", "daf_consistency", "subject_depth", "current_affairs_awareness"):
        if isinstance(report.get(key), str):
            report[key] = toSecondPerson(report[key])
    for key in ("improvements", "priority_actions"):
        report[key] = [toSecondPerson(str(item)) for item in report.get(key) or []]
    report["strengths"] = [
        strength for strength in report.get("strengths") or [] if isStrengthGrounded(str(strength), evaluation_log)
    ]
    report["strengths"] = [toSecondPerson(strength) for strength in report["strengths"]]
    if not report["strengths"]:
        # The model praised without quoting: rebuild strengths from the rows whose quotes were verified.
        report["strengths"] = [
            f'Turn {row["turn"]}: "{row["quote"]}" — {row["what_worked"]}'
            for row in rows
            if row["status"] == "answered" and row["quote"] and row["what_worked"]
        ][:3]
    return report


QUOTED = re.compile(r"[\"“‘]([^\"“”‘’]{3,})[\"”’]")  # "..." or curly quotes; an apostrophe is not a quote


TURN_NAMED = re.compile(r"\b(?:turn|q|question)\s*(\d+)", re.IGNORECASE)


def isStrengthGrounded(strength: str, evaluation_log: list[dict]) -> bool:
    """Praise must quote at least MIN_CLEAR_WORDS words from a real answer; if it names a turn, from THAT turn."""
    named = TURN_NAMED.search(strength)
    turns = [int(named.group(1))] if named else range(1, len(evaluation_log) + 1)
    for quote in QUOTED.findall(strength):
        if len(normalise(quote).split()) < MIN_CLEAR_WORDS:
            continue  # '"Yes sir"' is not a strength
        for turn in turns:
            entry = evaluation_log[turn - 1] if 0 < turn <= len(evaluation_log) else None
            if entry and isSubstantive(entry) and quoteInAnswer(quote, entry.get("answer") or ""):
                return True
    return False


# ---------- DAF contradictions caught by code ----------
# A board checks your answers against your DAF. The common self-claims (where you are from, where you studied,
# your hobby) are read here directly, so a contradiction is flagged even when the model misses it.

HOMETOWN_CLAIM = re.compile(
    r"(?i:\b(?:i (?:grew up|was born|was brought up|come|hail|belong)(?: up)? (?:in|from|to)|i am from|i'm from"
    r"|my home ?town is|i am a native of|native of))\s+([A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+)?)"
)
INSTITUTION_CLAIM = re.compile(
    r"(?i:\b(?:studied|graduated|graduation|degree|b\.?\s?tech|b\.?\s?e|b\.?\s?sc|b\.?\s?a|m\.?\s?a|mba|engineering|masters?)"
    r"\b[^.]{0,60}?\b(?:at|from))\s+((?:IIT|IIM|NIT|IIIT|BITS)\s?[A-Z][a-z]+|University of [A-Z][a-z]+"
    r"|[A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+)*\s(?:University|College|Institute))"
)
HOBBY_CLAIM = re.compile(r"(?i:\bmy (?:main |favourite |favorite |biggest |only )?hobby is)\s+([A-Za-z ]{3,40}?)(?=[.;,]|$| and )")
GENERIC_WORDS = {"university", "college", "institute", "of", "the", "playing", "competitive", "doing", "watching", "level"}


def significantWords(text: str) -> list[str]:
    return [word for word in normalise(text).split() if len(word) > 2 and word not in GENERIC_WORDS]


def isInDaf(claim: str, daf_text: str) -> bool:
    """'University of Delhi' matches 'Delhi University'; a claim counts as consistent if its key words are there."""
    words = significantWords(claim)
    return bool(words) and all(word in daf_text for word in words)


def findDafContradictions(answer: str, profile: dict) -> list[dict]:
    """Self-claims in the answer that the DAF does not support, as DAF flags (field, daf_says, candidate_said)."""
    hometown = str(profile.get("hometown") or "")
    education = " ; ".join(profile.get("education") or [])
    work = " ; ".join(profile.get("work_experience") or [])
    hobbies = " ; ".join(profile.get("hobbies") or [])
    places = normalise(" ".join([hometown, education, work]))
    flags = []
    if hometown:
        for claim in HOMETOWN_CLAIM.findall(answer or ""):
            if not isInDaf(claim, places):
                flags.append({"field": "hometown", "daf_says": hometown, "candidate_said": claim,
                              "message": f"You said you are from {claim}, but your DAF says {hometown}."})  # fmt: skip
    if education:
        for claim in INSTITUTION_CLAIM.findall(answer or ""):
            if not isInDaf(claim, normalise(education + " ; " + work)):
                flags.append({"field": "education", "daf_says": education, "candidate_said": claim,
                              "message": f"You said you studied at {claim}, which is not in your DAF's education."})  # fmt: skip
    if hobbies:
        for claim in HOBBY_CLAIM.findall(answer or ""):
            words = significantWords(claim)
            if words and not any(word in normalise(hobbies) for word in words):
                flags.append({"field": "hobbies", "daf_says": hobbies, "candidate_said": claim.strip(),
                              "message": f"You named '{claim.strip()}' as your hobby, but it is not in your DAF."})  # fmt: skip
    return flags


def dafConsistencyCap(flag_count: int) -> int:
    """Each contradiction a board would notice costs more: 1 flag -> at most 5, 2 -> 3, 3 or more -> 1."""
    return max(1, 7 - 2 * flag_count) if flag_count else 10


# ---------- the qualitative part: how each answer was built ----------
# What a UPSC board listens for in an answer. The model points at the phrase that shows each one; code keeps it only
# if that phrase is really in the answer, so a tick can never be invented.
CHECKLIST_ITEMS = {
    "stand": "Clear stand",
    "reason": "Reason given",
    "example": "Specific example",
    "balance": "Other side considered",
    "daf_link": "Linked to your background",
    "conclusion": "Conclusion",
}


# Each tick must also READ like what it claims (English, Hinglish or Hindi): a 'conclusion' that starts with
# "However" is a counter-point, and 'other side' needs a contrast. 'stand' only needs the phrase to be there.
CHECKLIST_MARKERS = {
    "reason": r"because|since|due to|the reason|as a result|so that|which is why|this is why|as it |\bby \w+ing\b|"
    r"\b(lead|result|reduc|improv|enabl|ensur|allow|foster|promot|help|increas|decreas|boost|strengthen|creat|"
    r"requir|caus|build|teach|taught)\w*|kyunki|kyonki|isliye|wajah|karan|kyun ki|se hi|क्योंकि|कारण|इसलिए",
    "stand": r"in my view|in my opinion|i believe|i think|i feel|my view|crucial|important|essential|should|must|"
    r"\bkey\b|significant|mera maanna|meri raay|mujhe lagta|zaroori|ज़रूरी|मेरा मानना|मुझे लगता",
    "example": r"for example|for instance|such as|e\.g|like |during|when i|jab |jaise|udaharan|जैसे|उदाहरण",
    "balance": r"however|but |although|though|on the other hand|conversely|while |whereas|\byet\b|limitation|risk|downside|"
    r"concern|criticism|drawback|lekin|magar|\bpar\b|kintu|halanki|लेकिन|परंतु|हालांकि|मगर",
    "conclusion": r"in conclusion|overall|therefore|\bthus\b|\bhence\b|to sum up|in short|ultimately|should|must|"
    r"need to|^so\b|crucial|essential|underscores|shows that|in the end|that is why|the way forward|isliye|chahiye|"
    r"zaroori hai|short mein|kul milakar|aakhir|अंततः|इसलिए|कुल मिलाकर",
}
FIRST_PERSON = re.compile(r"\b(i|my|me|mine|mujhe|mera|meri|mere|maine|hum|hamara)\b|मैं|मेरा|मेरी|मुझे", re.IGNORECASE)


def dafWords(profile: dict | None) -> set[str]:
    """Words that name the candidate's own background: hometown, institutions, jobs, hobbies, optional subject."""
    if not profile:
        return set()
    text = " ".join(
        [str(profile.get("hometown") or ""), str(profile.get("optional_subject") or "")]
        + [str(item) for key in ("education", "work_experience", "hobbies") for item in profile.get(key) or []]
    )
    return set(significantWords(text)) - {"from", "with", "and", "for", "hons", "intern", "present", "school"}


def leadIn(evidence: str, answer: str, words: int = 6) -> str:
    """The few words just before the phrase: 'However, surveillance can hurt privacy' quoted without 'However'."""
    text, phrase = normalise(answer), normalise(evidence)
    start = text.find(phrase)
    return " ".join(text[:start].split()[-words:]) if start > 0 else ""


def readsLike(item: str, evidence: str, profile: dict | None, answer: str = "") -> bool:
    if item == "stand":
        return True
    if item == "daf_link":
        words = set(normalise(evidence).split())
        return bool(FIRST_PERSON.search(evidence)) and bool(words & dafWords(profile))
    if item == "example" and (re.search(r"\d", evidence) or re.search(r"(?<=\s)[A-Z][a-z]{2,}", evidence)):
        return True  # a number or a name (not just the first word) is a specific example
    context = f"{leadIn(evidence, answer)} {evidence}".lower()
    return bool(re.search(CHECKLIST_MARKERS[item], context, re.IGNORECASE))


def verifyChecklist(written: object, answer: str, profile: dict | None = None) -> list[dict]:
    """[{item, label, ok, evidence}] for every item; ok only when the evidence phrase is really in the answer AND
    reads like what it claims."""
    given = written if isinstance(written, dict) else {}
    checklist = []
    for item, label in CHECKLIST_ITEMS.items():
        evidence = str(given.get(item) or "").strip()
        ok = (
            len(normalise(evidence).split()) >= 3
            and quoteInAnswer(evidence, answer)
            and readsLike(item, evidence, profile, answer)
        )
        if not ok:
            # The model pointed at the wrong phrase (or none): look for a sentence that shows it, so a ✗ is never
            # a false accusation of "no reason given" when the answer does give one.
            evidence = findEvidence(item, answer, profile)
            ok = bool(evidence)
        checklist.append({"item": item, "label": label, "ok": ok, "evidence": shortenQuote(evidence) if ok else ""})
    return checklist


def splitSentences(answer: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?।])\s+", answer or "") if len(part.split()) >= 3]


def findEvidence(item: str, answer: str, profile: dict | None) -> str:
    """The first sentence of the answer that reads like this item ('' when none does). A conclusion is looked for
    only at the end; a stand is a sentence that takes a view, else the opening claim."""
    sentences = splitSentences(answer)
    if item == "stand":
        for sentence in sentences:
            if re.search(CHECKLIST_MARKERS["stand"], sentence, re.IGNORECASE):
                return sentence
        return sentences[0] if sentences and len(sentences[0].split()) >= 6 else ""  # the opening claim
    if item == "conclusion":
        sentences = sentences[-2:]
    for sentence in sentences:
        if readsLike(item, sentence, profile, ""):
            return sentence
    return ""


def judgeLength(answer: str) -> dict:
    """A board answer runs about 45-90 seconds when spoken: roughly 80-180 words."""
    words = len(normalise(answer).split())
    if words < 40:
        seconds = max(1, words * 60 // 150)
        verdict = "too_short"
        note = f"{words} word{'s' if words != 1 else ''} (about {seconds} second{'s' if seconds != 1 else ''}) — aim for 45-90 seconds."
    elif words < 80:
        verdict, note = "short", f"{words} words — good start; one more example or a conclusion would round it off."
    elif words <= 200:
        verdict, note = "good", f"{words} words — a good length for a board answer."
    else:
        verdict, note = "too_long", f"{words} words — over 90 seconds; boards prefer crisp answers."
    return {"words": words, "verdict": verdict, "note": note}


def shortenQuote(quote: str, limit: int = 22) -> str:
    """A quote points at one phrase; a whole paragraph points at nothing."""
    words = quote.split()
    return quote if len(words) <= limit else " ".join(words[:limit]) + " …"


THIRD_PERSON = [
    (re.compile(r"\bThe candidate's\b"), "Your"), (re.compile(r"\bthe candidate's\b"), "your"),
    (re.compile(r"\bThe candidate\b"), "You"), (re.compile(r"\bthe candidate\b"), "you"),
    (re.compile(r"\bCandidate's\b"), "Your"),
]  # fmt: skip


def toSecondPerson(text: str) -> str:
    """'The candidate demonstrated...' -> 'You demonstrated...'; quoted words are left exactly as spoken."""
    parts = re.split(r'("[^"]*"|“[^”]*”)', text)
    for index in range(0, len(parts), 2):
        for pattern, replacement in THIRD_PERSON:
            parts[index] = pattern.sub(replacement, parts[index])
    return "".join(parts)


# ---------- reliability: model output we cannot trust, and a model that does not answer at all ----------

def parseScore(value: object) -> int | None:
    """7, "7", "7/10", "7.5", "Score: 7" -> 7 or 8 (rounded); None when there is no number at all."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(value)
    found = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    return round(float(found.group(0))) if found else None


CLARITY_SCORE = {"clear": 7, "vague": 4}


def deriveScore(entries: list[dict]) -> int:
    """A fair score from the per-answer verdicts alone: clear answers 7, vague ones 4."""
    values = [CLARITY_SCORE.get(entry.get("clarity") or "", 0) for entry in entries]
    return round(sum(values) / len(values)) if values else 0


def fallbackEvaluation(answer: str) -> dict:
    """The evaluator model failed (timeout, rate limit, broken JSON): judge the answer's build by code instead of
    stopping the interview. Clear = a reason AND a specific example; otherwise vague."""
    checks = {row["item"]: row["ok"] for row in verifyChecklist({}, answer)}
    clear = checks["reason"] and checks["example"] and len(normalise(answer).split()) >= MIN_CLEAR_WORDS
    return {
        "clarity": "clear" if clear else "vague",
        "factual_consistency": "unknown",
        "notes": "Checked automatically (the AI evaluator was briefly unavailable): "
        + ("a reason and a specific example are there." if clear else "add a clear reason and one specific example."),
    }


def buildFallbackReport(evaluation_log: list[dict], daf_flags: list, profile: dict | None) -> dict:
    """The report model failed: the candidate still gets a full report, built from the per-answer checks by code."""
    report = {
        "overall_summary": "Your report was built from the per-answer checks (the AI coach was briefly unavailable), "
        "so the advice is shorter than usual; the scores follow the same rules.",
        "strengths": [],
        "improvements": [
            entry["notes"] for entry in evaluation_log if isSubstantive(entry) and entry.get("notes")
        ][:3] or ["Give a reason and one specific example in every answer."],
        "priority_actions": ["Answer every question, with a clear stand, a reason and one specific example."],
        "scores": {},
        "question_feedback": [],
    }
    report = calibrateFeedbackScores(report, evaluation_log, daf_flags)
    return groundQuestionFeedback(report, evaluation_log, profile)
