"""Prompt for the end-of-interview report: per-question feedback with quotes and a board checklist."""

FEEDBACK_USER_TEMPLATE = """You are a senior UPSC Personality Test coach writing a post-mock debrief for the candidate.

Interview mode: {interview_mode} ({question_count} answers recorded)
Mode context: Quick drill = short practice (~5 questions). Full board = longer simulation (~12 questions).
Score relative to the mode — do not penalise quick-drill answers for brevity if they are relevant.

Candidate profile (DAF):
{profile}

Full transcript:
{history}

Per-turn evaluator notes (use these as primary evidence for scores):
{evaluation_log}

DAF consistency flags raised during interview:
{daf_flags}

Return JSON:
{{
  "overall_summary": "3-5 sentences spoken TO the candidate as 'you' (never 'the candidate'): honest and encouraging; name your strongest answer and your main gap",
  "question_feedback": [
    {{
      "turn": 1,
      "quote": "the ONE phrase (5-20 words) copied EXACTLY from the answer that best shows its quality (empty if not answered)",
      "checklist": {{
        "stand": "a 4-15 word phrase copied EXACTLY from the answer where you take a clear position, or empty",
        "reason": "phrase copied EXACTLY where you justify it, or empty",
        "example": "phrase copied EXACTLY with a specific example, fact, scheme, number or personal experience, or empty",
        "balance": "phrase copied EXACTLY where you consider another side or a limitation, or empty",
        "daf_link": "phrase copied EXACTLY where you connect the answer to your own background, or empty",
        "conclusion": "phrase copied EXACTLY where you sum up or say what should be done, or empty"
      }},
      "what_worked": "what this specific answer did well, pointing at the quote",
      "improve": "the one most useful change for THIS answer (structure, a missing example, a DAF link, a fact)",
      "better_answer": "2-3 lines: how a strong candidate would answer this question"
    }}
  ],
  "strengths": ["3-5 strengths, each naming the turn and quoting a 5-20 word phrase of the answer in \"double quotes\""],
  "improvements": ["3-5 specific, actionable improvements tied to particular turns — not generic advice"],
  "priority_actions": ["top 3 things to practice before the next mock"],
  "daf_consistency": "2-3 sentences on how answers aligned with the DAF",
  "subject_depth": "2-3 sentences on optional/subject answers",
  "current_affairs_awareness": "2-3 sentences on CA phase performance",
  "scores": {{
    "clarity": 0,
    "structure": 0,
    "daf_consistency": 0,
    "subject_depth": 0,
    "current_affairs": 0,
    "confidence": 0
  }},
  "phase_breakdown": {{
    "daf_opening": "...",
    "subject_probe": "...",
    "current_affairs": "...",
    "closing": "..."
  }}
}}

Give one question_feedback item for EVERY turn, in order.

Evidence rules (the report is checked by code):
- Every strength and every "what_worked" must quote words the candidate actually said. A quote that is not in
  the transcript is deleted, and praise without a real quote is dropped.
- A turn marked NOT ANSWERED scores 0 and has no strengths. Do not soften this, but still coach it:
  - "improve": how to handle this kind of question in a real board instead of skipping. Admitting honestly
    ("I am not aware of the details, sir") and then offering what you DO know (a related fact, your approach,
    your view) is valued; silence or "skip" is not.
  - "better_answer": the 2-3 points a strong candidate would have covered for THIS question.
- If most turns were not answered, say so plainly in the improvements and make the first priority action about
  answering every question, even briefly.
- Never invent facts about the candidate beyond the DAF and the transcript.
- Checklist phrases are verified by code: a phrase that is not in the answer is removed and that item counts as
  missing. Leave an item empty rather than stretch it.
- Write every field to the candidate as "you" / "your" — this report is read by the candidate.

Scoring rubric (integers 0-10), judged ONLY from answers that were actually given:
- 9-10: Exceptional — structured, concrete examples, strong DAF/CA linkage
- 7-8: Good — clear and relevant with minor gaps
- 5-6: Adequate — answered but thin, unstructured, or under-developed
- 3-4: Weak — vague, very short, or partially off-topic
- 1-2: Poor — barely an answer
- 0: not answered or wholly off-topic

Calibration rules:
- Quick mode: a concise but relevant 20-40 word answer can score 5-6 on clarity/structure.
- DAF consistency: 10 = no contradictions; 7-9 = minor inconsistencies; 6 or less if flags were raised.
- Confidence: infer from fluency and completeness across turns, not voice quality.
- Code caps every score by the share of questions answered and marks phases never reached as "not assessed".
- Be constructive — this is practice, not a final rejection."""
