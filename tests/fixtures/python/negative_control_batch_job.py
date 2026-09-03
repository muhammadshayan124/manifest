"""Uses the OpenAI chat-completions API, but as a batch summarization job with no route
decorator and no chat/bot/assistant-like naming -- Article 50(1) doesn't apply here since
this never interacts directly with a natural person. Should NOT be flagged at all; this
fixture exists to prove the user-facing gate actually suppresses false positives."""

import openai

client = openai.OpenAI()


def summarize_overnight_reports(report_text: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": f"Summarize: {report_text}"}],
    )
    return response.choices[0].message.content
