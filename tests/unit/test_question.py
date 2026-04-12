import pytest
from engine.question import Question, Chunk, Score, PTCResult, ProgToolResult, QuestionLog


def test_question_valid():
    q = Question(type="conceptual", text="What is SSDT?",
                 correct_answer="System Service Descriptor Table",
                 kb_excerpt="SSDT maps syscall numbers...", source_file="windows-internals.md")
    assert q.type == "conceptual"
    assert q.text == "What is SSDT?"


def test_question_invalid_type():
    with pytest.raises(ValueError, match="Invalid question type"):
        Question(type="unknown", text="Q", correct_answer="A",
                 kb_excerpt="E", source_file="f.md")


def test_question_empty_text():
    with pytest.raises(ValueError, match="text cannot be empty"):
        Question(type="fill_in", text="", correct_answer="A",
                 kb_excerpt="E", source_file="f.md")


def test_chunk_fields():
    c = Chunk(text="some content", source_file="topic_a.md", heading="SSDT Hooking")
    assert c.heading == "SSDT Hooking"


def test_score_valid_values():
    for v in [0.0, 0.5, 1.0]:
        s = Score(value=v, feedback="ok", correct_answer="A")
        assert s.value == v


def test_score_invalid_value():
    with pytest.raises(ValueError, match="Score value must be"):
        Score(value=0.7, feedback="ok", correct_answer="A")


def test_ptc_result():
    r = PTCResult(compressed_text="compact", raw_tokens=1000, compressed_tokens=200)
    assert r.compression_ratio == pytest.approx(0.8)


def test_prog_tool_result():
    r = ProgToolResult(output_text="out", script="print('x')", fallback_used=False)
    assert not r.fallback_used


def test_question_empty_correct_answer():
    with pytest.raises(ValueError, match="correct_answer cannot be empty"):
        Question(type="fill_in", text="What is SSDT?", correct_answer="",
                 kb_excerpt="E", source_file="f.md")


def test_ptc_result_zero_raw_tokens():
    r = PTCResult(compressed_text="", raw_tokens=0, compressed_tokens=0)
    assert r.compression_ratio == 0.0


def test_question_log_defaults():
    log = QuestionLog(
        question_num=1, question_type="fill_in", question_text="What is SSDT?",
        user_answer="SSDT", correct_answer="System Service Descriptor Table",
        score=1.0, model_used="local", tokens_local=50, tokens_premium=0,
        ptc_compression_ratio=0.6
    )
    assert log.error is None
