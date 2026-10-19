from festin.chat.provider import absorb_reasoning_details, reasoning_text


def test_streamed_thinking_keeps_a_delta_seen_earlier():
    bucket = []
    for piece in ["it's inbound. ", "Printed with", " it", ", then"]:
        absorb_reasoning_details(bucket, [{"type": "reasoning.text", "index": 0, "text": piece}])
    assert bucket[0]["text"] == "it's inbound. Printed with it, then"


def test_thinking_sent_twice_shows_once():
    msg = {
        "reasoning": "Read the card first.",
        "reasoning_details": [{"type": "reasoning.text", "text": "Read the card first.", "signature": "s"}],
    }
    assert reasoning_text(msg) == "Read the card first."
    assert reasoning_text({"reasoning": "Plain only."}) == "Plain only."
