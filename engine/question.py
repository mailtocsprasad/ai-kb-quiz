from dataclasses import dataclass


VALID_QUESTION_TYPES = {"conceptual", "code", "fill_in"}


@dataclass
class Question:
    type: str
    text: str
    correct_answer: str
    kb_excerpt: str
    source_file: str

    def __post_init__(self):
        if self.type not in VALID_QUESTION_TYPES:
            raise ValueError(f"Invalid question type '{self.type}'. Must be one of {VALID_QUESTION_TYPES}")
        if not self.text.strip():
            raise ValueError("text cannot be empty")
        if not self.correct_answer.strip():
            raise ValueError("correct_answer cannot be empty")


@dataclass
class Chunk:
    text: str
    source_file: str
    heading: str


@dataclass
class Score:
    value: float
    feedback: str
    correct_answer: str

    def __post_init__(self):
        if self.value not in {0.0, 0.5, 1.0}:
            raise ValueError(f"Score value must be 0.0, 0.5, or 1.0 — got {self.value}")


@dataclass
class PTCResult:
    compressed_text: str
    raw_tokens: int
    compressed_tokens: int

    @property
    def compression_ratio(self) -> float:
        if self.raw_tokens == 0:
            return 0.0
        return round(1.0 - self.compressed_tokens / self.raw_tokens, 4)


@dataclass
class ProgToolResult:
    output_text: str
    script: str
    fallback_used: bool


@dataclass
class QuestionLog:
    question_num: int
    question_type: str
    question_text: str
    user_answer: str
    correct_answer: str
    score: float
    model_used: str
    tokens_local: int
    tokens_premium: int
    ptc_compression_ratio: float
    error: str | None = None
