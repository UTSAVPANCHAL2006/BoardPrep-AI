PANEL_PERSONA = (
    "You are a senior UPSC Personality Test board member — calm, probing, respectful. "
    "Real UPSC boards combine DAF-based questions, optional-subject depth, and current affairs. "
    "Ask ONE short focused question at a time. Never bundle multiple topics."
)

ROUTER_HINTS = {
    "probe": "Last answer was vague. Probe the SAME topic — one clarifying question.",
    "daf_probe": "Candidate may contradict DAF. Ask ONE polite reconciliation question.",
    "pivot": "Answer was clear. Ask ONE new follow-up on a fresh single angle.",
    "advance_phase": "New phase begins. Ask ONE short opening question for this phase.",
}

DAF_QUESTION_TEMPLATE = """Phase: {phase}
Router: {router_hint}
DAF focus (ONLY this detail from their form): {focus_anchor}

Candidate DAF profile:
{profile}

Recent conversation:
{history}

Write ONE realistic UPSC board question anchored to the DAF focus above.

STRICT RULES:
- ONLY about "{focus_anchor}" — one DAF detail, no other fields
- English: max 25 words, 1-2 sentences, ONE "?"
- question: crisp formal ENGLISH for screen
- question_voice: same meaning in HINDI/HINGLISH (max 30 words, NOT English)
- No compound questions

Return JSON: {{"question": "...", "question_voice": "..."}}"""

SUBJECT_QUESTION_TEMPLATE = """Phase: subject_probe
Router: {router_hint}
Optional subject from DAF: {optional_subject}

Candidate DAF profile:
{profile}

Recent conversation:
{history}

Syllabus context (use for conceptual depth):
{context}

Write ONE UPSC board question testing optional-subject knowledge linked to their DAF.

STRICT RULES:
- Test conceptual depth in {optional_subject} — use syllabus context above
- Link to ONE DAF detail (education or work) where natural
- English: max 28 words, ONE "?"
- question_voice: HINDI/HINGLISH (max 32 words, NOT English)
- No compound questions

Return JSON: {{"question": "...", "question_voice": "..."}}"""

CA_QUESTION_USER_TEMPLATE = """Phase: current_affairs
Router: {router_hint}

Featured news article (MUST base question on THIS):
{featured_article}

Candidate DAF profile:
{profile}

Recent conversation:
{history}

Additional retrieved context:
{context}

Write ONE short UPSC current-affairs question. Pick ONE angle only:
(A) the news event itself, OR (B) a brief DAF touch ({daf_anchor}) — never both in one question.

STRICT RULES:
- MUST name or clearly reference the news event / policy in the featured article
- Max ONE short DAF hint if used — no second follow-up clause ("and how would you integrate…")
- English: max 20 words, ONE "?", ONE sentence
- question_voice: HINDI/HINGLISH (max 26 words, NOT English)
- No compound questions; no "and also" / "aur aap" second parts
- No generic polity questions unrelated to the featured article

Return JSON: {{"question": "...", "question_voice": "..."}}"""

CA_RETRY_SUFFIX = """
CRITICAL: Your question did NOT reference the required news event.
You MUST clearly mention: "{article_title}" or its core policy/issue."""
