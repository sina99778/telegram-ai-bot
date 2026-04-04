"""
app/services/security/content_filter.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Pre-API content safety filter that screens user prompts BEFORE
they reach the Gemini API. This is the primary defence against
policy-violating content that could get the API key banned.

Layers:
  1. Keyword / phrase blocklist (multi-language)
  2. Regex pattern detection (obfuscation-resistant)
  3. Image-specific prompt filter (stricter rules for generation)

All checks run locally — zero API calls, zero latency cost.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import ClassVar

logger = logging.getLogger(__name__)


@dataclass
class FilterDecision:
    allowed: bool
    reason: str | None = None
    category: str | None = None  # e.g. "sexual", "violence", "illegal"


class ContentFilterService:
    """Local keyword and regex-based content filter.

    This runs BEFORE any prompt reaches the Gemini API to prevent
    policy-violating content from ever being sent to Google.
    """

    # ── Blocked keyword phrases (case-insensitive, multi-language) ──
    # These are partial matches checked against the lowercased prompt.
    # Organized by policy category for auditability.

    _SEXUAL_KEYWORDS: ClassVar[list[str]] = [
        # English explicit
        "write me porn", "erotic story", "sex story", "sexual roleplay",
        "erotic roleplay", "sex chat", "nude photo", "nude image",
        "naked photo", "naked image", "explicit sex", "graphic sex",
        "nsfw image", "nsfw photo", "hentai", "rule34", "rule 34",
        "pornographic", "xxx image", "xxx photo", "sex scene",
        "sexual fantasy", "fetish content", "bdsm story",
        "generate nude", "generate naked", "undress", "deepfake",
        "deep fake nude", "fake nude", "strip her", "strip him",
        # Persian explicit
        "داستان سکسی", "داستان پورن", "عکس لخت", "عکس سکسی",
        "فیلم سکسی", "محتوای بزرگسال", "تصویر لخت",
        "رابطه جنسی", "چت سکسی", "رل پلی جنسی",
    ]

    _CSAM_KEYWORDS: ClassVar[list[str]] = [
        # Absolute zero-tolerance — child exploitation
        "child porn", "cp image", "underage sex", "underage nude",
        "minor nude", "minor naked", "loli", "lolicon", "shotacon",
        "child nude", "child naked", "kid nude", "kid naked",
        "teen nude", "teen naked", "پورن بچه", "عکس لخت بچه",
        "کودک لخت", "نوجوان لخت",
    ]

    _VIOLENCE_KEYWORDS: ClassVar[list[str]] = [
        "how to make a bomb", "how to build a bomb", "bomb making",
        "make explosives", "build explosives", "how to make poison",
        "how to poison someone", "how to kill someone",
        "how to murder", "hire a hitman", "hire an assassin",
        "how to make meth", "how to cook meth", "how to make drugs",
        "synthesize fentanyl", "make fentanyl",
        "how to make a gun", "3d print gun", "ghost gun",
        "mass shooting plan", "terrorist attack plan",
        "biological weapon", "chemical weapon", "nerve agent",
        "ساخت بمب", "ساختن بمب", "ساخت مواد منفجره",
        "ساخت سم", "کشتن", "تروریستی",
        "ساخت مواد مخدر", "ساخت شیشه",
    ]

    _HARASSMENT_KEYWORDS: ClassVar[list[str]] = [
        "write hate speech", "generate hate speech",
        "racist joke about", "sexist joke about",
        "harass this person", "bully this person",
        "doxx this person", "dox this person", "doxxing",
        "swat this person", "swatting",
        "death threat to", "rape threat",
    ]

    _FRAUD_KEYWORDS: ClassVar[list[str]] = [
        "phishing email template", "scam email template",
        "write a phishing", "craft a phishing",
        "social engineering script", "how to hack into",
        "hack someone's account", "crack password",
        "bypass security", "exploit vulnerability",
        "write malware", "create ransomware", "write a virus",
        "keylogger code", "rat trojan",
        "ایمیل فیشینگ", "هک اکانت", "هک حساب",
    ]

    _SELF_HARM_KEYWORDS: ClassVar[list[str]] = [
        "how to kill myself", "suicide method", "suicide plan",
        "how to hang myself", "painless suicide",
        "self harm method", "cut myself",
        "خودکشی", "روش خودکشی",
    ]

    # ── Image-specific blocked terms (stricter) ──
    _IMAGE_BLOCKED_KEYWORDS: ClassVar[list[str]] = [
        "nude", "naked", "nsfw", "explicit", "porn", "pornographic",
        "sexy", "erotic", "hentai", "xxx", "topless", "bottomless",
        "lingerie", "underwear model", "bikini model",
        "gore", "blood", "decapitation", "dismember", "corpse",
        "dead body", "mutilation", "torture",
        "child", "kid", "minor", "teen", "underage", "young girl",
        "young boy", "little girl", "little boy", "baby",
        "deepfake", "deep fake", "fake photo of",
        "real person", "real photo of", "photograph of",
        "celebrity", "politician",
        "gun", "weapon", "knife attack", "shooting",
        "drug", "cocaine", "heroin", "meth",
        "لخت", "سکسی", "پورن", "بچه", "کودک",
        "نوجوان", "سلاح", "اسلحه", "مواد مخدر",
        "خون", "جسد", "شکنجه",
    ]

    # ── Regex patterns for obfuscation-resistant detection ──
    _OBFUSCATION_PATTERNS: ClassVar[list[re.Pattern]] = [
        # Spaced-out attempts: "n u d e", "p o r n"
        re.compile(r"\bn\s*u\s*d\s*e\b", re.IGNORECASE),
        re.compile(r"\bp\s*o\s*r\s*n\b", re.IGNORECASE),
        re.compile(r"\bs\s*e\s*x\b", re.IGNORECASE),
        re.compile(r"\bn\s*s\s*f\s*w\b", re.IGNORECASE),
        # Leet-speak: "pr0n", "s3x", "nud3"
        re.compile(r"\bpr[0o]n\b", re.IGNORECASE),
        re.compile(r"\bs[3e]x\b", re.IGNORECASE),
        re.compile(r"\bnud[3e]\b", re.IGNORECASE),
        # Prompt injection patterns
        re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|rules?|prompts?)", re.IGNORECASE),
        re.compile(r"forget\s+(all\s+)?(your|previous|prior)\s+(instructions?|rules?|prompts?)", re.IGNORECASE),
        re.compile(r"you\s+are\s+now\s+(dan|evil|unfiltered|uncensored|jailbroken)", re.IGNORECASE),
        re.compile(r"act\s+as\s+(dan|evil|unfiltered|uncensored|jailbroken)", re.IGNORECASE),
        re.compile(r"pretend\s+(you\s+are|to\s+be)\s+(dan|evil|unfiltered|uncensored)", re.IGNORECASE),
        re.compile(r"disable\s+(your\s+)?(safety|content)\s+(filter|guidelines)", re.IGNORECASE),
        re.compile(r"jailbreak", re.IGNORECASE),
        re.compile(r"\bDAN\s*mode\b", re.IGNORECASE),
        re.compile(r"developer\s+mode\s+(enabled|activated|on)", re.IGNORECASE),
    ]

    @classmethod
    def _check_keywords(cls, text_lower: str, keywords: list[str], category: str) -> FilterDecision | None:
        """Check if any keyword phrase appears in the lowercased text."""
        for keyword in keywords:
            if keyword.lower() in text_lower:
                return FilterDecision(
                    allowed=False,
                    reason="Your request contains content that violates our usage policy.",
                    category=category,
                )
        return None

    @classmethod
    def _check_patterns(cls, text: str) -> FilterDecision | None:
        """Check regex patterns for obfuscation and prompt injection."""
        for pattern in cls._OBFUSCATION_PATTERNS:
            if pattern.search(text):
                return FilterDecision(
                    allowed=False,
                    reason="Your request contains content that violates our usage policy.",
                    category="obfuscation_or_injection",
                )
        return None

    @classmethod
    def check_text_prompt(cls, prompt: str) -> FilterDecision:
        """Screen a text chat or search prompt. Returns FilterDecision."""
        text_lower = prompt.lower()

        # Priority order: CSAM > self-harm > violence > sexual > harassment > fraud > patterns
        checks = [
            (cls._CSAM_KEYWORDS, "csam"),
            (cls._SELF_HARM_KEYWORDS, "self_harm"),
            (cls._VIOLENCE_KEYWORDS, "violence"),
            (cls._SEXUAL_KEYWORDS, "sexual"),
            (cls._HARASSMENT_KEYWORDS, "harassment"),
            (cls._FRAUD_KEYWORDS, "fraud"),
        ]

        for keywords, category in checks:
            result = cls._check_keywords(text_lower, keywords, category)
            if result:
                logger.warning(
                    "Content filter BLOCKED text prompt category=%s prompt_preview=%.80s",
                    category,
                    prompt[:80],
                )
                return result

        # Check obfuscation / prompt injection patterns
        pattern_result = cls._check_patterns(prompt)
        if pattern_result:
            logger.warning(
                "Content filter BLOCKED text prompt category=%s prompt_preview=%.80s",
                pattern_result.category,
                prompt[:80],
            )
            return pattern_result

        return FilterDecision(allowed=True)

    @classmethod
    def check_image_prompt(cls, prompt: str) -> FilterDecision:
        """Screen an image generation prompt. STRICTER than text filter."""
        # First run the standard text filter
        text_result = cls.check_text_prompt(prompt)
        if not text_result.allowed:
            return text_result

        # Then apply stricter image-specific keyword blocking
        text_lower = prompt.lower()
        result = cls._check_keywords(text_lower, cls._IMAGE_BLOCKED_KEYWORDS, "image_policy")
        if result:
            result.reason = "This image prompt contains content that is not allowed. Please try a different description."
            logger.warning(
                "Content filter BLOCKED image prompt category=%s prompt_preview=%.80s",
                result.category,
                prompt[:80],
            )
            return result

        return FilterDecision(allowed=True)
