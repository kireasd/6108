"""Claude로 쇼츠 각색: 후킹 제목 + 한국어 자막 + 업로드용 메타데이터."""
from typing import List

import anthropic
from pydantic import BaseModel


class SubLine(BaseModel):
    i: int
    text: str


class ShortsPlan(BaseModel):
    title_line1: str
    title_line2: str
    highlight_word: str
    subtitles: List[SubLine]
    upload_title: str
    description: str
    hashtags: List[str]


SYSTEM = """너는 한국 유튜브 쇼츠 전문 편집자다. 해외 영상의 정보를 받아 한국 시청자용 쇼츠로 각색한다.
규칙:
- title_line1, title_line2: 영상 상단에 크게 들어갈 2줄 후킹 제목. 각 줄 12자 이내. 과장/허위 금지, 영상 내용에 근거할 것.
- highlight_word: 제목 안에 실제로 포함된 단어 하나 (색으로 강조됨).
- subtitles: 입력 자막의 각 i에 대해 자연스러운 한국어 구어체 번역. 한 항목 최대 24자. 입력에 있는 i만 사용.
  입력 자막이 없으면 빈 배열.
- upload_title: 업로드용 제목 (40자 이내, 끝에 #shorts 금지).
- description: 2~3문장 설명.
- hashtags: '#' 없이 5개 내외."""


def make_plan(api_key, model, tone, source_title, source_desc, segments, translate=True):
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    if translate:
        sub_text = "\n".join(f"{i}\t{s.start:.1f}-{s.end:.1f}\t{s.text}" for i, s in enumerate(segments))
    else:
        sub_text = "(자막 번역 안 함 - subtitles는 빈 배열로)"
    user = f"""채널 말투: {tone}

[원본 제목]
{source_title}

[원본 설명]
{(source_desc or '')[:1500]}

[원본 자막: 번호\\t시간\\t내용]
{sub_text or '(없음)'}"""

    response = client.beta.messages.parse(
        model=model,
        max_tokens=16000,
        system=SYSTEM,
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": user}],
        output_format=ShortsPlan,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("AI가 이 영상의 각색을 거절했습니다.")
    plan = response.parsed_output
    if plan is None:
        raise RuntimeError("AI 응답을 해석하지 못했습니다.")
    return plan
