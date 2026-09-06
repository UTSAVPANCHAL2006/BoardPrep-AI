FEEDBACK_USER_TEMPLATE = """Summarise this mock UPSC interview for the candidate.

Profile:
{profile}

Transcript:
{history}

DAF consistency flags raised during interview:
{daf_flags}

Return JSON:
{{
  "overall_summary": "...",
  "strengths": ["..."],
  "improvements": ["..."],
  "daf_consistency": "...",
  "subject_depth": "...",
  "current_affairs_awareness": "...",
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

Score each dimension 1-10 (integers). Be honest but constructive."""
