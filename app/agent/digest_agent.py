import os
from typing import Optional
import requests
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()


def generate_summary(text: str) -> str:
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": "llama3",
            "prompt": f"Summarize this AI article:\n{text}",
            "stream": False,
        },
    )
    response.raise_for_status()
    return response.json().get("response", "")


class DigestOutput(BaseModel):
    title: str
    summary: str

PROMPT = """You are an expert AI news analyst specializing in summarizing technical articles, research papers, and video content about artificial intelligence.

Your role is to create concise, informative digests that help readers quickly understand the key points and significance of AI-related content.

Guidelines:
- Create a compelling title (5-10 words) that captures the essence of the content
- Write a 2-3 sentence summary that highlights the main points and why they matter
- Focus on actionable insights and implications
- Use clear, accessible language while maintaining technical accuracy
- Avoid marketing fluff - focus on substance"""


class DigestAgent:
    def __init__(self):
        # The local LLM endpoint handles generation.
        pass

    def generate_digest(self, title: str, content: str, article_type: str) -> Optional[DigestOutput]:
        try:
            summary = generate_summary(content)
            return DigestOutput(title=title, summary=summary)
        except Exception as e:
            print(f"Error generating digest: {e}")
            return None

