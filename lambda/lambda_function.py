"""
Music Assistant Alexa Skill — AWS Lambda Handler
Python 3.12 | ask-sdk-core

Variables d'environnement requises :
  API_URL       : URL publique de l'add-on  (ex: https://alexa-api.mondomaine.com)
  API_USERNAME  : identifiant Basic Auth     (configuré dans l'add-on HA)
  API_PASSWORD  : mot de passe Basic Auth    (configuré dans l'add-on HA)
  STREAM_URL    : URL publique du stream MA  (ex: https://stream.mondomaine.com)
"""

import os
import json
import logging
import urllib.request
import urllib.error
import base64
import re

import ask_sdk_core.utils as ask_utils
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.dispatch_components import (
    AbstractRequestHandler,
    AbstractExceptionHandler,
)
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response
from ask_sdk_model.interfaces.audioplayer import (
    PlayDirective,
    PlayBehavior,
    AudioItem,
    Stream,
    AudioItemMetadata,
    StopDirective,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ── Configuration ─────────────────────────────────────────────────────────────
API_URL      = os.environ.get("API_URL", "https://alexa-api.mondomaine.com")
API_USERNAME = os.environ.get("API_USERNAME", "")
API_PASSWORD = os.environ.get("API_PASSWORD", "")
STREAM_URL   = os.environ.get("STREAM_URL", "https://stream.mondomaine.com")


# ── Helpers ───────────────────────────────────────────────────────────────────

def rewrite_url(url: str) -> str:
    """Réécrit les URLs de stream internes (http://IP:PORT) en URL publique HTTPS."""
    if not url:
        return url
    rewritten = re.sub(r"http://[^/]+:\d+", STREAM_URL, url)
    logger.info("URL rewrite: %s -> %s", url, rewritten)
    return rewritten


def get_latest_stream() -> dict | None:
    """Interroge l'add-on timlaing pour obtenir le stream en cours."""
    url = f"{API_URL.rstrip('/')}/ma/latest-url"
    credentials = base64.b64encode(
        f"{API_USERNAME}:{API_PASSWORD}".encode()
    ).decode()
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Basic {credentials}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            if data.get("streamUrl"):
                data["streamUrl"] = rewrite_url(data["streamUrl"])
            if data.get("imageUrl"):
                data["imageUrl"] = rewrite_url(data["imageUrl"])
            return data
    except urllib.error.HTTPError as e:
        logger.error("HTTP error fetching stream: %s", e.code)
    except Exception as e:
        logger.error("Error fetching stream: %s", e)
    return None


def build_play_response(handler_input: HandlerInput) -> Response:
    """Construit la réponse AudioPlayer à partir du stream courant."""
    stream_data = get_latest_stream()

    if not stream_data or not stream_data.get("streamUrl"):
        return (
            handler_input.response_builder
            .speak(
                "Aucun stream disponible. "
                "Lance une lecture depuis Music Assistant d'abord."
            )
            .response
        )

    logger.info("Playing stream: %s", stream_data["streamUrl"])

    return (
        handler_input.response_builder
        .speak(f"Lecture de {stream_data.get('title', 'Music Assistant')}")
        .add_directive(
            PlayDirective(
                play_behavior=PlayBehavior.REPLACE_ALL,
                audio_item=AudioItem(
                    stream=Stream(
                        token="music-assistant-stream",
                        url=stream_data["streamUrl"],
                        offset_in_milliseconds=0,
                    ),
                    metadata=AudioItemMetadata(
                        title=stream_data.get("title", "Music Assistant"),
                        subtitle=stream_data.get("artist", ""),
                    ),
                ),
            )
        )
        .response
    )


# ── Request Handlers ──────────────────────────────────────────────────────────

class LaunchRequestHandler(AbstractRequestHandler):
    """Ouverture de la Skill → démarre la lecture."""

    def can_handle(self, handler_input):
        return ask_utils.is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        logger.info("LaunchRequest received")
        return build_play_response(handler_input)


class PlayAudioIntentHandler(AbstractRequestHandler):
    """Intent PlayAudio explicite."""

    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("PlayAudio")(handler_input)

    def handle(self, handler_input):
        return build_play_response(handler_input)


class PauseIntentHandler(AbstractRequestHandler):
    """Pause / Stop / Cancel → arrête la lecture."""

    def can_handle(self, handler_input):
        return any([
            ask_utils.is_intent_name("AMAZON.PauseIntent")(handler_input),
            ask_utils.is_intent_name("AMAZON.StopIntent")(handler_input),
            ask_utils.is_intent_name("AMAZON.CancelIntent")(handler_input),
        ])

    def handle(self, handler_input):
        return handler_input.response_builder.add_directive(StopDirective()).response


class ResumeIntentHandler(AbstractRequestHandler):
    """Resume → relance le stream courant."""

    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("AMAZON.ResumeIntent")(handler_input)

    def handle(self, handler_input):
        return build_play_response(handler_input)


class AudioPlayerEventHandler(AbstractRequestHandler):
    """Gère tous les événements AudioPlayer."""

    _EVENTS = [
        "AudioPlayer.PlaybackStarted",
        "AudioPlayer.PlaybackFinished",
        "AudioPlayer.PlaybackStopped",
        "AudioPlayer.PlaybackNearlyFinished",
        "AudioPlayer.PlaybackFailed",
    ]

    def can_handle(self, handler_input):
        return any(
            ask_utils.is_request_type(e)(handler_input) for e in self._EVENTS
        )

    def handle(self, handler_input):
        event = handler_input.request_envelope.request.object_type
        logger.info("AudioPlayer event: %s", event)

        # Ré-enqueue le stream quand il est presque terminé (flux continu)
        if event == "AudioPlayer.PlaybackNearlyFinished":
            stream_data = get_latest_stream()
            if stream_data and stream_data.get("streamUrl"):
                return (
                    handler_input.response_builder
                    .add_directive(
                        PlayDirective(
                            play_behavior=PlayBehavior.ENQUEUE,
                            audio_item=AudioItem(
                                stream=Stream(
                                    token="music-assistant-stream-next",
                                    url=stream_data["streamUrl"],
                                    offset_in_milliseconds=0,
                                    expected_previous_token="music-assistant-stream",
                                )
                            ),
                        )
                    )
                    .response
                )

        return handler_input.response_builder.response


class HelpIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
        return (
            handler_input.response_builder
            .speak(
                "Dis simplement 'Alexa, ouvre Music Assistant' "
                "pour lancer la lecture en cours."
            )
            .response
        )


class FallbackIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("AMAZON.FallbackIntent")(handler_input)

    def handle(self, handler_input):
        return (
            handler_input.response_builder
            .speak("Dis 'ouvre Music Assistant' pour lancer la lecture.")
            .response
        )


class SessionEndedRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input):
        logger.info("SessionEndedRequest received")
        return handler_input.response_builder.response


class CatchAllExceptionHandler(AbstractExceptionHandler):
    def can_handle(self, handler_input, exception):
        return True

    def handle(self, handler_input, exception):
        logger.error("Unhandled exception: %s", exception, exc_info=True)
        return (
            handler_input.response_builder
            .speak(
                "Une erreur s'est produite. "
                "Vérifiez que Music Assistant est en cours de lecture."
            )
            .response
        )


# ── Skill Builder ─────────────────────────────────────────────────────────────
sb = SkillBuilder()

sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(PlayAudioIntentHandler())
sb.add_request_handler(PauseIntentHandler())
sb.add_request_handler(ResumeIntentHandler())
sb.add_request_handler(AudioPlayerEventHandler())
sb.add_request_handler(HelpIntentHandler())
sb.add_request_handler(FallbackIntentHandler())
sb.add_request_handler(SessionEndedRequestHandler())
sb.add_exception_handler(CatchAllExceptionHandler())

lambda_handler = sb.lambda_handler()
