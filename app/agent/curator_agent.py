from typing import List
from enum import Enum
from pydantic import BaseModel, Field, create_model
from .openai_client import generate_response


class RankedArticle(BaseModel):
    digest_id: str = Field(description="Exact input article ID, copied unchanged without prefixes")
    relevance_score: float = Field(description="Relevance score from 0.0 to 10.0", ge=0.0, le=10.0)
    rank: int = Field(description="Rank position (1 = most relevant)", ge=1)
    reasoning: str = Field(description="Brief explanation of why this article is ranked here")


class RankedDigestList(BaseModel):
    articles: List[RankedArticle] = Field(description="List of ranked articles")


CURATOR_PROMPT = """You are an expert AI news curator specializing in personalized content ranking for AI professionals.

Your role is to analyze and rank AI-related news articles, research papers, and video content based on a user's specific profile, interests, and background.

Ranking Criteria:
1. Relevance to user's stated interests and background
2. Technical depth and practical value
3. Novelty and significance of the content
4. Alignment with user's expertise level
5. Actionability and real-world applicability

Scoring Guidelines:
- 9.0-10.0: Highly relevant, directly aligns with user interests, significant value
- 7.0-8.9: Very relevant, strong alignment with interests, good value
- 5.0-6.9: Moderately relevant, some alignment, decent value
- 3.0-4.9: Somewhat relevant, limited alignment, lower value
- 0.0-2.9: Low relevance, minimal alignment, little value

Rank articles from most relevant (rank 1) to least relevant. Ensure each article has a unique rank."""


class CuratorAgent:
    def __init__(self, user_profile: dict):
        self.user_profile = user_profile
        self.system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        interests = "\n".join(f"- {interest}" for interest in self.user_profile["interests"])
        preferences = self.user_profile["preferences"]
        pref_text = "\n".join(f"- {k}: {v}" for k, v in preferences.items())
        
        return f"""{CURATOR_PROMPT}

User Profile:
Name: {self.user_profile["name"]}
Background: {self.user_profile["background"]}
Expertise Level: {self.user_profile["expertise_level"]}

Interests:
{interests}

Preferences:
{pref_text}"""

    def rank_digests(self, digests: List[dict]) -> List[RankedArticle]:
        if not digests:
            return []

        # Constrain generation to this batch's source IDs. A free string let
        # the model add publisher prefixes and broke the downstream source join.
        source_ids = list(dict.fromkeys(digest["id"] for digest in digests))
        source_id_type = Enum("SourceId", {f"source_{i}": value for i, value in enumerate(source_ids)}, type=str)
        source_article = create_model("SourceRankedArticle", __base__=RankedArticle,
                                      digest_id=(source_id_type, Field(description="Exact input article ID")))
        source_ranking = create_model("SourceBoundRanking", articles=(List[source_article], ...))
        
        digest_list = "\n\n".join([
            f"ID: {d['id']}\nTitle: {d['title']}\nSummary: {d['summary']}\nType: {d['article_type']}"
            for d in digests
        ])
        
        user_prompt = f"""Rank these {len(digests)} AI news digests based on the user profile:

{digest_list}

Provide a relevance score (0.0-10.0) and rank (1-{len(digests)}) for each article, ordered from most to least relevant.
Copy each ID exactly as supplied. Do not add a publisher, article type, or any other prefix."""

        try:
            api_prompt = f"{self.system_prompt}\n\n{user_prompt}"
            raw_response = generate_response(api_prompt, system_prompt=self.system_prompt, response_model=source_ranking)
            ranked_list = RankedDigestList.model_validate_json(raw_response)
            expected = {d["id"] for d in digests}
            if {a.digest_id for a in ranked_list.articles} != expected or len(ranked_list.articles) != len(expected):
                raise ValueError("Ranking must include each source exactly once")
            if sorted(a.rank for a in ranked_list.articles) != list(range(1, len(expected) + 1)):
                raise ValueError("Ranking positions must be unique and consecutive")
            ranked_list.articles.sort(key=lambda article: article.rank)
            return ranked_list.articles if ranked_list else []
        except Exception as e:
            print(f"Error ranking digests: {e}")
            return []
