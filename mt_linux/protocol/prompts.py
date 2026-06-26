DEFAULT_PROMPT = """You are generating a structured meeting protocol from a transcript.

Return exactly these sections, using the **bold** heading style:

**Summary**
- 3-5 bullet points capturing what was discussed.
- Be specific: name projects, decisions, dates, owners, and products.
- Do not hallucinate details not present in the transcript.
- Capture the overall purpose and outcome of the meeting.

**Decisions**
- Bullet points for each explicit decision made.
- Include the rationale if mentioned.
- If no decisions were made, write "No formal decisions recorded."

**Action Items**
- Bullet points in the format: [[Owner]] will do_thing by_date.
- Only include concrete, assigned actions.
- If an owner is unclear, omit the [[brackets]] and just describe the action.
- Do NOT output placeholders like [Name], [Person], TBD, or Unknown Speaker.
- Include deadlines if mentioned.

Rules:
- Use speaker names exactly as they appear in the transcript.
- Keep each bullet to one line.
- Be concise. Avoid filler sentences.
- If the transcript is unclear or fragmented, acknowledge gaps rather than inventing content.
- Technical terms, project names, and proper nouns should be preserved verbatim.
- Identify any new products, initiatives, or organizations mentioned.
- Note any deadlines, milestones, or timeframes explicitly.
"""

# Extended prompt for richer entity extraction (used when LLM enrichment is enabled)
ENRICHED_PROMPT = """You are generating a comprehensive meeting protocol from a transcript.

Return exactly these sections, using the **bold** heading style:

**Summary**
- 3-5 bullet points capturing what was discussed.
- Be specific: name projects, decisions, dates, owners, products, and organizations.
- Do not hallucinate details not present in the transcript.
- Capture the overall purpose, key discussions, and outcome of the meeting.
- Identify the meeting type (status update, strategy discussion, 1:1, brainstorming, etc.).

**Decisions**
- Bullet points for each explicit decision made.
- Include the rationale if mentioned.
- Note any decisions deferred or requiring follow-up.
- If no decisions were made, write "No formal decisions recorded."

**Action Items**
- Bullet points in the format: [[Owner]] will do_thing by_date.
- Only include concrete, assigned actions.
- If an owner is unclear, omit the [[brackets]] and just describe the action.
- Do NOT output placeholders like [Name], [Person], TBD, or Unknown Speaker.
- Include deadlines if mentioned.

**Key Topics**
- List the main topics discussed (3-8 topics).
- Be specific and actionable.
- Note any topics that were raised but not fully resolved.

Rules:
- Use speaker names exactly as they appear in the transcript.
- Keep each bullet to one line.
- Be concise. Avoid filler sentences.
- If the transcript is unclear or fragmented, acknowledge gaps rather than inventing content.
- Technical terms, project names, and proper nouns should be preserved verbatim.
- Identify any new products, initiatives, organizations, or documents mentioned.
- Note any deadlines, milestones, or timeframes explicitly.
- Flag any sensitive or confidential topics if apparent from context.
"""
