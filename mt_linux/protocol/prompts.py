DEFAULT_PROMPT = """You are generating a concise meeting protocol.

Return sections for:
- Summary
- Decisions
- Action Items

Keep the output grounded in the transcript.
Use speaker names exactly as they appear in the transcript when attribution is clear.
Do not output placeholders like [Name], [Person], TBD, or Unknown Speaker.
If attribution is unclear, write the action item or decision without inventing an actor.
"""
