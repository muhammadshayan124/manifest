"""A Flask chat endpoint with no AI-disclosure language anywhere -- should be flagged."""

from flask import Flask, request, jsonify
import openai

app = Flask(__name__)
client = openai.OpenAI()


@app.route("/chat", methods=["POST"])
def chat():
    user_message = request.json["message"]
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": user_message}],
    )
    return jsonify({"reply": response.choices[0].message.content})
