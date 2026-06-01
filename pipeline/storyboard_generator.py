"""
Storyboard generation: builds detailed image generation prompts for each scene
in either Japanese Anime or École Belge (Hergé/Moebius) style.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

VALID_STYLES = ("japanese_anime", "ecole_belge")


class StoryboardGenerator:
    """Generates image prompts and storyboard data for each visual scene."""

    def __init__(self, config: dict) -> None:
        self.config = config
        self.styles_config = config.get("styles", {})
        logger.info("StoryboardGenerator initialized.")

    def _get_style_config(self, style: str) -> dict:
        """Retrieve style configuration, falling back to japanese_anime."""
        if style not in self.styles_config:
            logger.warning("Style '%s' not found in config, using japanese_anime.", style)
            style = "japanese_anime"
        return self.styles_config[style]

    def build_image_prompt(self, scene: dict, style: str) -> str:
        """
        Build a detailed English image generation prompt for a scene.

        Incorporates style keywords, mood, colors, and composition rules from config.
        """
        style_cfg = self._get_style_config(style)
        keywords = style_cfg.get("keywords", [])
        color_palette = style_cfg.get("color_palette", {})
        composition_rules = style_cfg.get("composition_rules", [])

        # Core style anchor
        if style == "japanese_anime":
            style_anchor = (
                "Studio Ghibli, Makoto Shinkai, painterly, cel-shading, vibrant"
            )
        else:
            style_anchor = (
                "ligne claire, Hergé, Moebius, clean lines, flat colors, Franco-Belgian comic"
            )

        # Extract scene details
        visual_description = scene.get("visual_description", "")
        mood = scene.get("mood", "mélancolique")
        setting = scene.get("setting", "")
        action = scene.get("action", "")
        lighting = scene.get("lighting", "soft natural light")
        dominant_colors = scene.get("dominant_colors_suggestion", [])
        characters = scene.get("characters", [])
        scene_number = scene.get("scene_number", 1)

        # Map French mood to English descriptor
        mood_map = {
            "sombre": "dark, somber, ominous atmosphere",
            "lumineux": "bright, luminous, radiant atmosphere",
            "mystérieux": "mysterious, enigmatic, ethereal atmosphere",
            "romantique": "romantic, tender, warm atmosphere",
            "tragique": "tragic, sorrowful, dramatic atmosphere",
            "émerveillé": "wondrous, awe-inspiring, magical atmosphere",
            "mélancolique": "melancholic, wistful, nostalgic atmosphere",
            "épique": "epic, grandiose, majestic atmosphere",
        }
        mood_en = mood_map.get(mood.lower(), f"{mood} atmosphere")

        # Select relevant composition rule (cycle through them)
        comp_rule = composition_rules[(scene_number - 1) % len(composition_rules)] if composition_rules else ""

        # Build color string
        color_str = ""
        if dominant_colors:
            color_str = f"color palette featuring {', '.join(dominant_colors[:3])}"
        elif color_palette.get("primary"):
            primaries = color_palette["primary"][:3]
            color_str = f"color palette {', '.join(primaries)}"

        # Build character string
        char_str = ""
        if characters:
            char_str = f"featuring {', '.join(characters[:2])}"

        # Assemble the prompt
        prompt_parts = [
            f"{style_anchor},",
            f"{', '.join(keywords[:5])},",
            visual_description,
        ]

        if setting:
            prompt_parts.append(f"set in {setting},")
        if action:
            prompt_parts.append(f"{action},")
        if char_str:
            prompt_parts.append(f"{char_str},")

        prompt_parts += [
            f"{mood_en},",
            f"inspired by classic French literature,",
            f"{lighting},",
        ]

        if color_str:
            prompt_parts.append(f"{color_str},")
        if comp_rule:
            prompt_parts.append(f"composition: {comp_rule},")

        prompt_parts.append("masterpiece, best quality, highly detailed, 8k")

        prompt = " ".join(prompt_parts)
        # Clean up multiple spaces and trailing commas
        prompt = " ".join(prompt.split())
        return prompt

    def _build_negative_prompt(self, style: str) -> str:
        """Build the negative prompt for a given style."""
        style_cfg = self._get_style_config(style)
        base_negatives = [
            "photo",
            "realistic",
            "3d render",
            "watermark",
            "text",
            "signature",
            "low quality",
            "blurry",
            "deformed",
            "ugly",
            "bad anatomy",
            "bad proportions",
            "extra limbs",
            "cloned face",
            "mutated",
            "jpeg artifacts",
            "cropped",
        ]
        style_extras = style_cfg.get("negative_prompt_extras", [])
        all_negatives = list(dict.fromkeys(base_negatives + style_extras))
        return ", ".join(all_negatives)

    def generate_storyboard(self, scenes: list, style: str) -> list:
        """
        For each scene, add 'image_prompt' and 'negative_prompt' fields.

        Returns the enriched scenes list.
        """
        if style not in VALID_STYLES:
            logger.warning(
                "Unknown style '%s'. Valid styles: %s. Defaulting to japanese_anime.",
                style,
                VALID_STYLES,
            )
            style = "japanese_anime"

        style_label = self._get_style_config(style).get("label", style)
        logger.info(
            "Generating storyboard for %d scenes in '%s' style...",
            len(scenes),
            style_label,
        )

        negative_prompt = self._build_negative_prompt(style)
        enriched_scenes = []

        for scene in scenes:
            scene_copy = dict(scene)
            scene_number = scene_copy.get("scene_number", "?")

            try:
                image_prompt = self.build_image_prompt(scene_copy, style)
                scene_copy["image_prompt"] = image_prompt
                scene_copy["negative_prompt"] = negative_prompt
                scene_copy["style"] = style
                scene_copy["style_label"] = style_label
                logger.debug(
                    "Scene %s prompt built (%d chars): %s...",
                    scene_number,
                    len(image_prompt),
                    image_prompt[:80],
                )
            except Exception as exc:
                logger.error(
                    "Error building prompt for scene %s: %s", scene_number, exc
                )
                scene_copy["image_prompt"] = (
                    f"{style_label} illustration, classic French literature scene, "
                    "masterpiece, best quality"
                )
                scene_copy["negative_prompt"] = negative_prompt
                scene_copy["style"] = style
                scene_copy["style_label"] = style_label

            enriched_scenes.append(scene_copy)

        logger.info("Storyboard generation complete: %d scenes enriched.", len(enriched_scenes))
        return enriched_scenes
