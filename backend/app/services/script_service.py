import re


def split_script_into_beats(script_text: str) -> list[dict[str, object]]:
    """Split a script into ordered paragraphs, or sentences when needed."""
    paragraphs = [
        re.sub(r"\s+", " ", paragraph).strip()
        for paragraph in re.split(r"\n\s*\n", script_text.strip())
    ]
    paragraphs = [paragraph for paragraph in paragraphs if paragraph]

    if len(paragraphs) == 1:
        paragraphs = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", paragraphs[0])
            if sentence.strip()
        ]

    return [
        {"beat_number": index, "text": paragraph}
        for index, paragraph in enumerate(paragraphs, start=1)
    ]
