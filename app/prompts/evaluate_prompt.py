EVALUATE_USER_TEMPLATE = """Evaluate this UPSC Personality Test spoken answer.

Question: {question}
Answer: {answer}

DAF profile:
{profile}

UPSC boards expect answers that are structured (context → point → example → conclusion),
typically 45-90 seconds when spoken (roughly 80-180 words). Short one-liners are weak unless
the question only needs a brief clarification.

Return JSON:
{{
  "clarity": "clear" | "vague" | "off_topic",
  "factual_consistency": "consistent" | "contradicts_daf" | "unknown",
  "notes": "2-3 sentences: what was good, what to improve (depth, structure, DAF link, honesty)"
}}

Important — factual_consistency rules:
- Use "contradicts_daf" ONLY when the candidate states a concrete fact that conflicts with the DAF
  (wrong degree, wrong hometown, hobby they did not list, job they did not mention, etc.).
- General criticism of government, vague rants, emotional opinions, or poor structure → NOT contradicts_daf.
  Use clarity "vague" or "off_topic" instead and coach them in notes.
- Hinglish/Hindi answers are valid — judge content, not language mix."""
