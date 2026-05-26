"""
Music Assistant Alexa Skill — AWS Lambda Handler
Python 3.12 | ask-sdk-core

Required environment variables:
  API_URL          : Public add-on URL       (e.g. https://alexa-api.yourdomain.com)
  API_USERNAME     : Basic Auth username     (configured in the HA add-on)
  API_PASSWORD     : Basic Auth password     (configured in the HA add-on)
  STREAM_URL       : Public stream URL       (e.g. https://stream.yourdomain.com)
  HA_WEBHOOK_URL   : HA webhook URL to notify playback state changes (optional)
                     (e.g. https://yourdomain.com/api/webhook/your-webhook-id)
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
API_URL        = os.environ.get("API_URL", "https://alexa-api.yourdomain.com")
API_USERNAME   = os.environ.get("API_USERNAME", "")
API_PASSWORD   = os.environ.get("API_PASSWORD", "")
STREAM_URL     = os.environ.get("STREAM_URL", "https://stream.yourdomain.com")
HA_WEBHOOK_URL = os.environ.get("HA_WEBHOOK_URL", "")


# ── Helpers ───────────────────────────────────────────────────────────────────

def rewrite_url(url: str) -> str:
    """Rewrite internal stream URLs (http://IP:PORT) to public HTTPS URL."""
    if not url:
        return url
    rewritten = re.sub(r"http://[^/]+:\d+", STREAM_URL, url)
    logger.info("URL rewrite: %s -> %s", url, rewritten)
    return rewritten


def get_latest_stream() -> dict | None:
    """Query the HA add-on for the current stream metadata."""
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


def notify_ha_playback(stream_data: dict) -> None:
    """Notify Home Assistant that playback has started on Alexa.
    
    Sends a POST request to HA_WEBHOOK_URL with the current stream metadata.
    HA can use this to update the Music Assistant player state in real time.
    """
    if not HA_WEBHOOK_URL:
        return
    try:
        payload = {
            "title":     stream_data.get("title", ""),
            "artist":    stream_data.get("artist", ""),
            "album":     stream_data.get("album", ""),
            "imageUrl":  stream_data.get("imageUrl", ""),
            "streamUrl": stream_data.get("streamUrl", ""),
        }
        req = urllib.request.Request(
            HA_WEBHOOK_URL,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            logger.info("HA notified of playback: %s (status %s)", payload["title"], resp.status)
    except Exception as e:
        logger.error("Failed to notify HA: %s", e)


def build_play_response(handler_input: HandlerInput) -> Response:
    """Build the AudioPlayer response from the current stream."""
    stream_data = get_latest_stream()

    if not stream_data or not stream_data.get("streamUrl"):
        return (
            handler_input.response_builder
            .speak(
                "No stream available. "
                "Please start playback from Music Assistant first."
            )
            .response
        )

    logger.info("Playing stream: %s", stream_data["streamUrl"])

    return (
        handler_input.response_builder
        .speak(f"Playing {stream_data.get('title', 'Music Assistant')}")
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
    """Skill opened → start playback."""

    def can_handle(self, handler_input):
        return ask_utils.is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        logger.info("LaunchRequest received")
        return build_play_response(handler_input)


class PlayAudioIntentHandler(AbstractRequestHandler):
    """Explicit PlayAudio intent."""

    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("PlayAudio")(handler_input)

    def handle(self, handler_input):
        return build_play_response(handler_input)


class PauseIntentHandler(AbstractRequestHandler):
    """Pause / Stop / Cancel → stop playback."""

    def can_handle(self, handler_input):
        return any([
            ask_utils.is_intent_name("AMAZON.PauseIntent")(handler_input),
            ask_utils.is_intent_name("AMAZON.StopIntent")(handler_input),
            ask_utils.is_intent_name("AMAZON.CancelIntent")(handler_input),
        ])

    def handle(self, handler_input):
        return handler_input.response_builder.add_directive(StopDirective()).response


class ResumeIntentHandler(AbstractRequestHandler):
    """Resume → restart current stream."""

    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("AMAZON.ResumeIntent")(handler_input)

    def handle(self, handler_input):
        return build_play_response(handler_input)


class AudioPlayerEventHandler(AbstractRequestHandler):
    """Handle all AudioPlayer events."""

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

        # Notify HA immediately when playback starts → reduces display latency
        if event == "AudioPlayer.PlaybackStarted":
            stream_data = get_latest_stream()
            if stream_data:
                notify_ha_playback(stream_data)

        # Re-enqueue the stream when nearly finished (continuous playback)
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
                "Just say 'Alexa, open Music Assistant' "
                "to start playing the current stream."
            )
            .response
        )


class FallbackIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("AMAZON.FallbackIntent")(handler_input)

    def handle(self, handler_input):
        return (
            handler_input.response_builder
            .speak("Say 'open Music Assistant' to start playback.")
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
                "An error occurred. "
                "Please make sure Music Assistant is playing something."
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
