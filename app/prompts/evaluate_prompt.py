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
}}"""
