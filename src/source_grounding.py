"""Verbatim content grounding within a single, explicitly attributed turn."""
import re


def whitespace(text):
    return re.sub(r'\s+', ' ', text).strip()


def split_speaker(text):
    # Supported transcript formats: '(PERSON2) text' and 'Nam (Backend): text'.
    match = re.match(r'^\s*(\(PERSON\d+\))\s*:?[ \t]*(.*)$', text, re.DOTALL)
    if not match:
        match = re.match(r'^\s*([^:\r\n.!?]{1,80}):[ \t]*(.*)$', text, re.DOTALL)
    if match:
        return whitespace(match[1]), whitespace(match[2])
    return None, whitespace(text)


def transcript_turns(transcript):
    turns = []
    speaker, chunks = None, []
    def flush():
        if chunks:
            turns.append((speaker, whitespace(' '.join(chunks))))
    for line in transcript.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        if re.match(r'^\s*Ngày họp\s*:', line, re.IGNORECASE):
            flush(); speaker, chunks = None, []
            continue
        who, content = split_speaker(line)
        if who is not None:
            flush(); speaker, chunks = who, [content]
        elif line.strip():
            chunks.append(line)
    flush()
    return turns


def citation_matches(excerpt, turns):
    speaker, content = split_speaker(excerpt.strip())
    if not content:
        return False
    return any((speaker is None or speaker == turn_speaker) and content in turn_content
               for turn_speaker, turn_content in turns)
