"""Same endpoint, but with real AI-disclosure language in the function -- should pass
as needs_review (disclosure signal present), not likely_violation.
"""

from flask import Flask, request, jsonify
import openai

app = Flask(__name__)
client = openai.OpenAI()


@app.route("/chat", methods=["POST"])
def chat():
    user_message = request.json["message"]
    if request.json.get("first_message"):
        return jsonify({"reply": "You are chatting with an AI assistant, not a human support agent."})
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": user_message}],
    )
    return jsonify({"reply": response.choices[0].message.content})
