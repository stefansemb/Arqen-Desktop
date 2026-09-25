from arqen.tools.speech import _speech_clean


def test_degrees_are_spoken_as_words():
    assert _speech_clean("Mulet, 13 °C (känns som 11 °C)") == "Mulet, 13 grader (känns som 11 grader)"
    assert _speech_clean("1 °C") == "1 grad"
    assert _speech_clean("20 ℃ och 68 °F") == "20 grader och 68 grader Fahrenheit"
    assert _speech_clean("en vinkel på 90°") == "en vinkel på 90 grader"


def test_leading_minus_is_not_mistaken_for_a_bullet():
    assert _speech_clean("-4,5 °C i natt") == "-4,5 grader i natt"
    assert _speech_clean("- Morgon: 13 °C") == "Morgon: 13 grader"
