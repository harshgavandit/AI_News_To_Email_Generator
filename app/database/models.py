from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class YouTubeVideo(Base):
    __tablename__ = "youtube_videos"

    video_id = Column(String(50), primary_key=True)
    title = Column(String(500), nullable=False)
    url = Column(String(500), nullable=False)
    channel_id = Column(String(100), nullable=False)
    published_at = Column(DateTime, nullable=False)
    description = Column(Text)
    transcript = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class OpenAIArticle(Base):
    __tablename__ = "openai_articles"

    guid = Column(String(255), primary_key=True)
    title = Column(String(500), nullable=False)
    url = Column(String(500), nullable=False)
    description = Column(Text)
    published_at = Column(DateTime, nullable=False)
    category = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AnthropicArticle(Base):
    __tablename__ = "anthropic_articles"

    guid = Column(String(255), primary_key=True)
    title = Column(String(500), nullable=False)
    url = Column(String(500), nullable=False)
    description = Column(Text)
    published_at = Column(DateTime, nullable=False)
    category = Column(String(100), nullable=True)
    markdown = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Digest(Base):
    __tablename__ = "digests"

    id = Column(String(255), primary_key=True)
    article_type = Column(String(50), nullable=False)
    article_id = Column(String(255), nullable=False)
    url = Column(String(500), nullable=False)
    title = Column(String(500), nullable=False)
    summary = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)