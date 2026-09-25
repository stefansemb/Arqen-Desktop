"""Which tools the model is offered for a request, out of the whole catalogue."""

from arqen.connectors import store
from arqen.tools.builtins import create_builtin_registry
from arqen.tools.schema import build_relevant_tool_schemas


def _offered(context: str, focus: str = "") -> list[str]:
    return [schema["function"]["name"] for schema in build_relevant_tool_schemas(create_builtin_registry(), context, focus=focus)]


def _connect_everything() -> None:
    store.save_credentials("telegram", {"bot_token": "123456:abcdef", "chat_id": "7377448330"})
    store.save_credentials("github", {"token": "ghp_testtoken123"})
    store.save_credentials("google", {"client_id": "client-id", "client_secret": "secret-1", "refresh_token": "refresh-1"})


def test_a_named_service_is_offered_despite_a_word_many_tools_share():
    """'Arqen' appears in many descriptions; it once pushed Telegram out of the top 12."""
    _connect_everything()
    request = "skicka 'test från Arqen' till Telegram"
    assert "telegram_send_message" in _offered(request, focus=request)


def test_the_latest_request_outweighs_earlier_talk():
    _connect_everything()
    history = "vilka mejl har jag i inkorgen? läs mejlet från anna. sök i drive efter budget"
    # Enough Google talk to fill the list on its own, were it all that counted.
    history = " ".join([history] * 3) + " kalender möte händelser filer dokument utkast"
    assert "telegram_send_message" in _offered(history, focus="skicka hej till telegram")


def test_the_conversation_still_counts_when_the_request_is_vague():
    _connect_everything()
    assert "gmail_read_message" in _offered("läs mejlet från anna i gmail", focus="gör det igen")


def test_inflected_swedish_words_find_their_tools():
    _connect_everything()
    request = "vad har jag i kalendern i veckan?"
    offered = _offered(request, focus=request)
    assert "calendar_list_events" in offered
    assert len(offered) < 20  # a focused choice, not the whole catalogue
