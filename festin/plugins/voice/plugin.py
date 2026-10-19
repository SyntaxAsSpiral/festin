"""Voice plugin. Listen on replies; TTS provider and voice in settings."""

from __future__ import annotations

from festin.plugins.voice import speak

PLUGIN_ID = "voice"
PLUGIN_NAME = "Voice"


class VoicePlugin:
    id = PLUGIN_ID
    name = PLUGIN_NAME

    def settings_schema(self) -> list[dict]:
        local_on = speak.local_tts_configured()
        providers = ["openrouter", "elevenlabs"]
        choices = [
            {"id": "openrouter", "description": "OpenRouter"},
            {"id": "elevenlabs", "description": "ElevenLabs"},
        ]
        if local_on:
            providers = ["local"] + providers
            choices = [{"id": "local", "description": "Local"}] + choices
        default = "local" if local_on else "openrouter"
        help_text = (
            "How Babette reads a reply aloud. OpenRouter reuses the kitchen model key; "
            "ElevenLabs uses ELEVENLABS_API_KEY on the host. Keys are never stored in Settings."
        )
        if local_on:
            help_text += (
                " Local uses llama-tts with FESTIN_TTS_MODEL, FESTIN_TTS_PROJECTOR, "
                "and FESTIN_VOICE_REFERENCE on the host."
            )
        else:
            help_text += (
                " Local appears here only when the host sets FESTIN_TTS_MODEL, "
                "FESTIN_TTS_PROJECTOR, and FESTIN_VOICE_REFERENCE."
            )
        return [
            {
                "key": "provider",
                "type": "string",
                "default": default,
                "label": "Provider",
                "help": help_text,
                "enum": providers,
                "choices": choices,
            },
            {
                "key": "model",
                "type": "string",
                "default": "",
                "label": "Cloud model",
                "help": (
                    "OpenRouter or ElevenLabs model id. Leave empty for the provider default "
                    f"({speak.DEFAULT_OPENROUTER_MODEL} / {speak.DEFAULT_ELEVEN_MODEL})."
                ),
            },
            {
                "key": "voice",
                "type": "string",
                "default": "",
                "label": "Cloud voice",
                "help": (
                    "OpenRouter or ElevenLabs voice id. Leave empty for the OpenRouter default "
                    f"({speak.DEFAULT_OPENROUTER_VOICE}); ElevenLabs needs a voice id."
                ),
            },
        ]

    def register(self, registry) -> None:
        return

    def actions(self) -> dict:
        return {}

    def feed(self) -> dict:
        return {"localConfigured": speak.local_tts_configured()}


PLUGIN = VoicePlugin()
