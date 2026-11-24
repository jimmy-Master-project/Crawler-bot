from browser_bots.base import run_conversation


def scripted(*answers):
    sent = []

    def send(message):
        sent.append(message)
        return answers[len(sent) - 1], 10

    return send, sent


def test_stops_when_no_pattern_matches():
    send, sent = scripted("Dogs travel in the cabin.")
    result = run_conversation(send, "Can I bring my dog?", "Economy", 5, [r"which class\?"])
    assert sent == ["Can I bring my dog?"]
    assert result == {
        "turns": [{"user": "Can I bring my dog?", "assistant": "Dogs travel in the cabin.", "latency_ms": 10, "follow_up": False}],
        "ended": "answered",
        "latency_ms": 10,
    }


def test_replies_to_follow_up_questions_case_insensitively():
    send, sent = scripted("Which CLASS are you flying?", "Economy includes one bag.")
    result = run_conversation(send, "Baggage?", "Economy", 5, [r"which class"])
    assert sent == ["Baggage?", "Economy"]
    assert [t["follow_up"] for t in result["turns"]] == [True, False]
    assert result["ended"] == "answered"
    assert result["latency_ms"] == 20


def test_stops_at_max_turns():
    send, sent = scripted("Which class?", "Which route?", "Which date?")
    result = run_conversation(send, "Baggage?", "Economy", 2, [r"^which"])
    assert sent == ["Baggage?", "Economy"]
    assert [t["follow_up"] for t in result["turns"]] == [True, True]
    assert result["ended"] == "max_turns"


def test_no_patterns_is_one_turn():
    send, sent = scripted("Which class?")
    assert run_conversation(send, "Baggage?", "Economy", 5, [])["ended"] == "answered"
    assert sent == ["Baggage?"]
