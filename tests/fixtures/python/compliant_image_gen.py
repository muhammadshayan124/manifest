"""Same generation call, but with a real watermarking step before the result is
returned -- should pass as needs_review, not likely_violation."""

import openai
import piexif

client = openai.OpenAI()


def generate_product_photo(prompt: str) -> str:
    result = client.images.generate(model="dall-e-3", prompt=prompt)
    image_url = result.data[0].url
    embed_c2pa_manifest(image_url, generator="dall-e-3")
    return image_url


def embed_c2pa_manifest(image_url: str, generator: str) -> None:
    ...  # real implementation would attach a C2PA Content Credentials manifest here
