import OpenAI from "openai";

const client = new OpenAI();

export async function handleChatMessage(userMessage: string) {
  const response = await client.chat.completions.create({
    model: "gpt-4",
    messages: [{ role: "user", content: userMessage }],
  });
  return response.choices[0].message.content;
}
