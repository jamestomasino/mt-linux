DEFAULT_PROMPT = """You are generating a structured meeting protocol from a transcript.

Return exactly these sections, using the **bold** heading style:

**Summary**
- 3-5 bullet points capturing what was discussed.
- Be specific: name projects, decisions, dates, and owners.
- Do not hallucinate details not present in the transcript.

**Decisions**
- Bullet points for each explicit decision made.
- If no decisions were made, write "No formal decisions recorded."

**Action Items**
- Bullet points in the format: [[Owner]] will do_thing by_date.
- Only include concrete, assigned actions.
- If an owner is unclear, omit the [[brackets]] and just describe the action.
- Do NOT output placeholders like [Name], [Person], TBD, or Unknown Speaker.

Rules:
- Use speaker names exactly as they appear in the transcript.
- Keep each bullet to one line.
- Be concise. Avoid filler sentences.
- If the transcript is unclear or fragmented, acknowledge gaps rather than inventing content.
- Technical terms, project names, and proper nouns should be preserved verbatim.
"""
