"""Generates an image with OpenAI and returns it directly -- no watermarking/labeling
step anywhere. Should be flagged."""

import openai

client = openai.OpenAI()


def generate_product_photo(prompt: str) -> str:
    result = client.images.generate(model="dall-e-3", prompt=prompt)
    return result.data[0].url
