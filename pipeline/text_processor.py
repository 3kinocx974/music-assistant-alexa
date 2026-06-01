"""
Text processing pipeline: loads French literary texts, detects author/period,
segments into visual scenes, and generates narration scripts using Claude API.
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)


class TextProcessor:
    """Processes classic French literary texts for visual scene generation."""

    MODEL = "claude-sonnet-4-6"

    def __init__(self, config: dict) -> None:
        self.config = config
        api_key = config.get("api_keys", {}).get("anthropic")
        if not api_key or api_key.startswith("${"):
            import os
            api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("Anthropic API key not found in config or environment.")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.video_config = config.get("video", {})
        logger.info("TextProcessor initialized.")

    def load_text(self, text_or_path: str) -> str:
        """Load text from a string or a file path."""
        path = Path(text_or_path)
        if path.exists() and path.is_file():
            logger.info("Loading text from file: %s", path)
            return path.read_text(encoding="utf-8").strip()
        logger.info("Using provided text string (%d chars).", len(text_or_path))
        return text_or_path.strip()

    def detect_author_period(self, text: str) -> dict:
        """
        Use Claude to detect author, period, genre from a French literary text.

        Returns a dict with keys: author, period, genre, movement, language_style.
        """
        logger.info("Detecting author and period via Claude API...")

        prompt = (
            "Tu es un expert en littérature française classique. "
            "Analyse ce texte et identifie les informations suivantes. "
            "Réponds UNIQUEMENT en JSON valide avec ces champs:\n"
            "{\n"
            '  "author": "Nom de l\'auteur (ex: Victor Hugo, Baudelaire) ou "Inconnu"",\n'
            '  "period": "Période littéraire (ex: Romantisme, Symbolisme, Baroque)",\n'
            '  "century": "Siècle (ex: XIXe siècle)",\n'
            '  "genre": "roman | poème | théâtre | nouvelle | essai | autre",\n'
            '  "movement": "Mouvement littéraire précis",\n'
            '  "language_style": "Description courte du style d\'écriture",\n'
            '  "themes": ["thème1", "thème2", "thème3"],\n'
            '  "mood": "atmosphère générale du texte en un mot",\n'
            '  "title_suggestion": "Titre suggéré pour la vidéo"\n'
            "}\n\n"
            f"Texte:\n{text[:2000]}"
        )

        try:
            message = self.client.messages.create(
                model=self.MODEL,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text.strip()
            # Extract JSON from response
            json_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                logger.info(
                    "Detected: author=%s, period=%s, genre=%s",
                    result.get("author"),
                    result.get("period"),
                    result.get("genre"),
                )
                return result
            logger.warning("Could not extract JSON from Claude response; using defaults.")
        except anthropic.APIError as exc:
            logger.error("Claude API error during author detection: %s", exc)
        except json.JSONDecodeError as exc:
            logger.error("JSON decode error during author detection: %s", exc)

        return {
            "author": "Auteur inconnu",
            "period": "Littérature française",
            "century": "XIXe siècle",
            "genre": "poème",
            "movement": "Classique",
            "language_style": "Prose poétique",
            "themes": ["nature", "amour", "temps"],
            "mood": "mélancolique",
            "title_suggestion": "Extrait de la littérature française",
        }

    def segment_into_scenes(self, text: str, n_scenes: int = 15) -> list:
        """
        Use Claude to split the text into N visual scenes.

        Each scene dict contains:
          scene_number, text_excerpt, mood, dominant_colors_suggestion,
          visual_description, duration_seconds
        """
        scene_duration = self.video_config.get("scene_duration_seconds", 6)
        logger.info("Segmenting text into %d scenes via Claude API...", n_scenes)

        prompt = (
            f"Tu es un expert en adaptation cinématographique de textes littéraires français. "
            f"Découpe ce texte en exactement {n_scenes} scènes visuelles pour une vidéo de "
            f"{n_scenes * scene_duration} secondes ({scene_duration}s par scène).\n\n"
            f"Pour chaque scène, génère un objet JSON avec ces champs OBLIGATOIRES:\n"
            "{\n"
            '  "scene_number": <entier 1 à ' + str(n_scenes) + '>,\n'
            '  "text_excerpt": "<extrait du texte original pour cette scène>",\n'
            '  "mood": "<ambiance: sombre|lumineux|mystérieux|romantique|tragique|émerveillé|mélancolique|épique>",\n'
            '  "dominant_colors_suggestion": ["<couleur1>", "<couleur2>", "<couleur3>"],\n'
            '  "visual_description": "<description visuelle détaillée en anglais de 2-3 phrases pour la génération d\'image>",\n'
            '  "duration_seconds": ' + str(scene_duration) + ',\n'
            '  "setting": "<lieu ou décor principal>",\n'
            '  "characters": ["<personnage1>", "<personnage2>"],\n'
            '  "action": "<action principale visible dans la scène>",\n'
            '  "lighting": "<description de l\'éclairage>"\n'
            "}\n\n"
            f"Réponds UNIQUEMENT avec un tableau JSON valide de {n_scenes} objets scène.\n\n"
            f"Texte à découper:\n{text}"
        )

        try:
            message = self.client.messages.create(
                model=self.MODEL,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text.strip()
            # Extract JSON array
            json_match = re.search(r"\[.*\]", raw, re.DOTALL)
            if json_match:
                scenes = json.loads(json_match.group())
                if isinstance(scenes, list) and len(scenes) > 0:
                    # Ensure scene_number is sequential and duration is set
                    for i, scene in enumerate(scenes):
                        scene["scene_number"] = i + 1
                        scene.setdefault("duration_seconds", scene_duration)
                    logger.info("Successfully segmented text into %d scenes.", len(scenes))
                    return scenes
        except anthropic.APIError as exc:
            logger.error("Claude API error during scene segmentation: %s", exc)
        except json.JSONDecodeError as exc:
            logger.error("JSON decode error during scene segmentation: %s", exc)

        logger.warning("Falling back to naive text segmentation.")
        return self._fallback_segment(text, n_scenes, scene_duration)

    def _fallback_segment(self, text: str, n_scenes: int, scene_duration: int) -> list:
        """Naive fallback: split text evenly if Claude API fails."""
        words = text.split()
        chunk_size = max(1, len(words) // n_scenes)
        scenes = []
        for i in range(n_scenes):
            start = i * chunk_size
            end = start + chunk_size if i < n_scenes - 1 else len(words)
            excerpt = " ".join(words[start:end])
            scenes.append(
                {
                    "scene_number": i + 1,
                    "text_excerpt": excerpt,
                    "mood": "mélancolique",
                    "dominant_colors_suggestion": ["bleu nuit", "or", "blanc"],
                    "visual_description": (
                        f"A scene from classic French literature. "
                        f"Scene {i + 1}: {excerpt[:100]}..."
                    ),
                    "duration_seconds": scene_duration,
                    "setting": "paysage français",
                    "characters": [],
                    "action": "contemplation",
                    "lighting": "lumière dorée du crépuscule",
                }
            )
        return scenes

    def generate_narration_script(self, text: str, scenes: list) -> list:
        """
        Generate a short French narration sentence per scene (max 15 words each).

        Returns a list of narration strings, one per scene.
        """
        logger.info("Generating narration scripts for %d scenes via Claude API...", len(scenes))

        scenes_summary = "\n".join(
            f"Scène {s['scene_number']}: {s.get('text_excerpt', '')[:200]}"
            for s in scenes
        )

        prompt = (
            "Tu es un narrateur littéraire français au style élégant et poétique. "
            f"Génère exactement {len(scenes)} phrases de narration, une par scène, "
            "en français. Chaque phrase doit:\n"
            "- Être courte (maximum 15 mots)\n"
            "- Capturer l'essence poétique de la scène\n"
            "- Être adaptée à une lecture à voix haute\n"
            "- Avoir un style littéraire élégant\n\n"
            "Réponds UNIQUEMENT avec un tableau JSON de chaînes de caractères:\n"
            '["Phrase scène 1", "Phrase scène 2", ...]\n\n'
            f"Scènes:\n{scenes_summary}"
        )

        try:
            message = self.client.messages.create(
                model=self.MODEL,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text.strip()
            json_match = re.search(r"\[.*\]", raw, re.DOTALL)
            if json_match:
                scripts = json.loads(json_match.group())
                if isinstance(scripts, list):
                    # Pad or trim to match scene count
                    while len(scripts) < len(scenes):
                        scripts.append(scenes[len(scripts)].get("text_excerpt", "")[:80])
                    scripts = scripts[: len(scenes)]
                    logger.info("Generated %d narration scripts.", len(scripts))
                    return scripts
        except anthropic.APIError as exc:
            logger.error("Claude API error during narration generation: %s", exc)
        except json.JSONDecodeError as exc:
            logger.error("JSON decode error during narration generation: %s", exc)

        logger.warning("Falling back to excerpt-based narration.")
        return [s.get("text_excerpt", "")[:80] for s in scenes]
