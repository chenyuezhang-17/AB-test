"""Shared data models for pipeline stages."""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class ScannedTweet:
    """Scanner → Reasoner"""
    tweet_id: str
    author: str
    original_text: str
    author_bio: str = ""
    recent_tweets: list[str] | None = None  # last 10-20 tweets for context


@dataclass
class AnalyzedTweet:
    """Reasoner → Bridge"""
    tweet_id: str
    author: str
    intent: str  # hiring | looking_for | recommendation
    search_query: str
    original_text: str
    confidence: float


@dataclass
class PreparedReply:
    """Bridge → Action"""
    tweet_id: str
    lessie_url: str
    reply_text: str
    confidence: float
