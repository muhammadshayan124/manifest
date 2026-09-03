import OpenAI from "openai";

const client = new OpenAI();

// Shown to the user before the first message: "You're chatting with an AI assistant."
export async function handleChatMessage(userMessage: string) {
  const response = await client.chat.completions.create({
    model: "gpt-4",
    messages: [{ role: "user", content: userMessage }],
  });
  return response.choices[0].message.content;
}
