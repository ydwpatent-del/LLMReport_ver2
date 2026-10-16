"""마크다운 불릿 기호 체계(네모-동그라미-하이픈) 및 옵션 A GFM 각주 분리 표기 단위 테스트."""

import pytest
from app.utils import clean_markdown_typography


def test_clean_double_bullets_to_hierarchical_symbols():
    """- ○ 이중기호를 ○ 단일기호로 복원하고, - - 중복 하이픈을 단일 - 로 정돈하여
    네모(□) - 동그라미(○) - 하이픈(-) 3단계 계층을 정확히 확립하는지 검증."""
    raw_md = (
        "### 1. 기술 동향\n\n"
        "□ 멀티모달 생성형 AI는 일부 기술이 상용화되기 시작하는 단계임\n\n"
        "- ○ '24년에는 부천국제판타스틱영화제에서 AI 영화 부문 도입\n"
        "- ○ Big-Tech 기업뿐 아니라 스타트업들도 두각을 나타냄\n"
        "- - Vision Encoder와 LLM을 결합한 단순 구조\n"
        "- - 130만 개의 공개 데이터셋 활용\n"
    )

    cleaned = clean_markdown_typography(raw_md)

    # 1. '- ○' 이중기호가 앞선 '- '를 제거하고 '○ ' 단일기호로 복원되었는지 검증
    assert "- ○" not in cleaned
    assert "○ '24년에는 부천국제판타스틱영화제에서" in cleaned
    assert "○ Big-Tech 기업뿐 아니라" in cleaned

    # 2. '- -' 중복 하이픈이 단일 '- '로 정돈되었는지 검증
    assert "- -" not in cleaned
    assert "- Vision Encoder와 LLM을 결합한 단순 구조" in cleaned
    assert "- 130만 개의 공개 데이터셋 활용" in cleaned

    # 3. 1단계 네모(□) 기호가 온전하게 보존되었는지 검증
    assert "□ 멀티모달 생성형 AI는 일부 기술이 상용화되기 시작하는 단계임" in cleaned

    # 4. 마크다운 수평선(---)이 중복 불릿으로 치환되지 않고 그대로 보존되며 2단계 들여쓰기가 적용되는지 검증
    hr_md = "# 제목\n\n---\n\n- ○ 내용"
    cleaned_hr = clean_markdown_typography(hr_md)
    assert "---\n\n  ○ 내용" in cleaned_hr


def test_isolate_footnotes_to_gfm_standard_option_a():
    """본문 중간에 혼입된 각주 설명을 본문에서 분리하고, 본문 인용부(단어1))를
    표준 GFM 각주(단어[^1]) 및 문서 최하단 [^1]: **용어**: 설명으로 정돈하는지 검증."""
    raw_md = (
        "### 2. 모델 구조\n\n"
        "LLM의 기반이 되는 모델 구조인 Transformer1)와 더불어 Diffusion2) 방식이 널리 사용되고 있으며 최근 DiT3) 구조가 각광받음.\n\n"
        "□ 향후 발전 방향\n\n"
        "- ○ 아직 생성 결과물의 품질이 미흡한 경우가 잦아 품질 개선이 요구됨.\n"
        "- 1) Transformer: 정보의 중요도에 따라 가중치를 다르게 주어 집중하게 하는 구조임.\n"
        "- 2) Diffusion: 노이즈를 점진적으로 제거하여 원하는 데이터를 생성하는 방식임.\n"
        "- 3) DiT: Diffusion과 Transformer를 결합한 고성능 아키텍처임.\n\n"
        "### 3. 다음 섹션\n\n"
        "○ 후속 연구가 지속되고 있음 (arXiv 2023).\n"
    )

    cleaned = clean_markdown_typography(raw_md)

    # 1. 본문 인용부가 표준 GFM 문법으로 치환되었는지 검증
    assert "Transformer[^1]와" in cleaned
    assert "Diffusion[^2] 방식이" in cleaned
    assert "DiT[^3] 구조가" in cleaned

    # 연도 2023이 202[^3]으로 오인 치환되지 않고 보존되는지 검증
    assert "2023" in cleaned
    assert "202[^3]" not in cleaned

    # 2. 본문 중간(### 3. 다음 섹션 이전)에서 '- 1) Transformer:' 각주 정의가 제거되었는지 검증
    body_before_next_section = cleaned.split("### 3. 다음 섹션")[0]
    assert "- 1) Transformer:" not in body_before_next_section
    assert "- 2) Diffusion:" not in body_before_next_section
    assert "- 3) DiT:" not in body_before_next_section

    # 3. 문서 최하단에 각주 섹션 및 GFM 정의가 올바르게 생성되었는지 검증
    assert "### 📌 각주 (Footnotes)" in cleaned
    assert "[^1]: **Transformer**: 정보의 중요도에 따라 가중치를 다르게 주어 집중하게 하는 구조임." in cleaned
    assert "[^2]: **Diffusion**: 노이즈를 점진적으로 제거하여 원하는 데이터를 생성하는 방식임." in cleaned
    assert "[^3]: **DiT**: Diffusion과 Transformer를 결합한 고성능 아키텍처임." in cleaned


def test_zero_information_loss_in_typography_cleaning():
    """서식 정규화 후에도 본문과 각주의 핵심 키워드 및 문장이 100% 무손실 보존되는지 검증."""
    original_text = (
        "□ 개요\n"
        "- ○ 반도체 공정에서 식각제4)의 역할은 매우 중요함.\n"
        "- 4) 식각제: 회로 패턴을 형성하기 위해 불필요한 부분을 화학적으로 깎아내는 약품.\n"
    )

    cleaned = clean_markdown_typography(original_text)

    # 핵심 단어 및 설명이 단 하나도 소실되지 않았는지 검증
    assert "반도체 공정에서" in cleaned
    assert "식각제[^4]의 역할은 매우 중요함" in cleaned
    assert "회로 패턴을 형성하기 위해 불필요한 부분을 화학적으로 깎아내는 약품" in cleaned


def test_markdown_bullet_trailing_spaces_for_hard_breaks():
    """불릿 기호 라인 끝에 마크다운 표준 줄바꿈을 위한 스페이스 2개가 부여되는지 검증."""
    raw = "□ 대항목 1\n○ 중항목 1\n- 소항목 1"
    cleaned = clean_markdown_typography(raw)
    lines = cleaned.split("\n")

    assert lines[0] == "□ 대항목 1  "
    assert lines[1] == "  ○ 중항목 1  "
    assert lines[2] == "    - 소항목 1  "


def test_circuit_breaker_triggers_on_abnormal_output_length(tmp_path):
    """청크당 LLM 응답이 30,000자를 초과하는 비정상 무한 루프 환각 발생 시
    서킷 브레이커가 동작하여 None을 반환(룰베이스 폴백 유도)하는지 검증."""
    from unittest.mock import MagicMock
    from app.kordoc_wiki_agent import KordocWikiAgent

    agent = KordocWikiAgent(docs_dir=tmp_path / "docs", assets_dir=tmp_path / "assets", api_key="dummy-key")

    mock_client = MagicMock()
    mock_chat = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "반복되는 텍스트 내용 " * 3500  # 약 42,000자
    mock_chat.send_message.return_value = mock_response
    mock_client.chats.create.return_value = mock_chat

    import google.genai as genai
    original_client_cls = genai.Client
    try:
        genai.Client = MagicMock(return_value=mock_client)
        result = agent._call_llm_for_wiki_ingest(
            raw_md="### 테스트 문서 본문\n내용입니다.",
            doc_id="test_doc_01",
            original_filename="test.pdf",
            file_hash="hash123",
            images_info=[]
        )
        assert result is None
    finally:
        genai.Client = original_client_cls


def test_deduplicate_and_isolate_gfm_footnotes_to_end():
    """본문 중간(표 사이 등)에 끼어있는 GFM 각주 정의([^N]: ...) 및 중복 각주를 수거하여
    본문 중간에서는 완전히 제거하고 문서 최하단에 단일 표준 각주 섹션으로 배치하는지 검증."""
    raw_md = (
        "## 1. 개요\n\n"
        "AI 모델[^1]의 성능 향상을 위해서는 양질의 라벨링[^2] 데이터셋이 필요함.\n\n"
        "| 업체명 | 내용 |\n"
        "|---|---|\n"
        "| Scale AI | 데이터 라벨링 서비스 제공 |\n\n"
        "---\n"
        "[^1]: **AI 모델**: 수학적, 통계적 기법으로 구현된 구조임.\n"
        "[^2]: **라벨링**: 원시 데이터에 의미를 부여하는 작업임.\n\n"
        "| Cogito Tech | 인공지능 훈련 데이터 전문 |\n"
        "|---|---|\n\n"
        "비즈니스 규칙[^3] 기반의 자동화가 적용됨.\n\n"
        "---\n"
        "[^1]: **AI 모델**: (요약) 학습용 구조임.\n"
        "[^2]: **라벨링**: 원시 데이터에 정답 태그를 부여하여 학습 가능하게 만드는 작업임.\n"
        "[^3]: **비즈니스 규칙**: 의사결정에서 사용하는 경험 기반의 규칙임.\n"
    )

    cleaned = clean_markdown_typography(raw_md)

    # 1. 본문 중간의 각주 정의 블록이 제거되었는지 검증
    body_part = cleaned.split("### 📌 각주 (Footnotes)")[0]
    assert "[^1]:" not in body_part
    assert "[^2]:" not in body_part
    assert "[^3]:" not in body_part

    # 2. 최하단 각주 섹션에 1, 2, 3번 각주가 각각 단 1개씩만 존재하는지 검증
    import re
    fn_defs = re.findall(r'^\s*\[\^(\d+)\]:\s*(.+)$', cleaned, re.MULTILINE)
    assert len(fn_defs) == 3
    assert [int(n) for n, _ in fn_defs] == [1, 2, 3]

    # 3. 중복 각주 중 더 상세하고 긴 설명이 보존되었는지 검증 (Zero Information Loss)
    assert "**라벨링**: 원시 데이터에 정답 태그를 부여하여 학습 가능하게 만드는 작업임." in cleaned

    # 4. 표 사이의 각주 제거로 인해 표와 내용의 연속성이 자연스러운지 검증
    assert "Scale AI" in body_part
    assert "Cogito Tech" in body_part


def test_validate_red_flags_detects_inline_and_duplicate_footnotes():
    """validate_red_flags가 본문 내 각주 정의 잔존 및 전체 중복 각주 정의를 Red Flag로 탐지하는지 검증."""
    from app.utils import validate_red_flags

    # 1. 본문 중간에 각주 정의가 남아있는 경우
    bad_md1 = (
        "## 본문\n"
        "내용입니다.[^1]\n\n"
        "[^1]: **용어**: 설명입니다.\n\n"
        "### 다음 섹션\n"
        "이어지는 내용입니다.\n"
    )
    flags1 = validate_red_flags(bad_md1)
    assert any("각주 서식 위반" in f for f in flags1)

    # 2. 각주 정의가 중복된 경우
    bad_md2 = (
        "## 본문\n"
        "내용입니다.[^1]\n\n"
        "---\n\n"
        "### 📌 각주 (Footnotes)\n\n"
        "[^1]: **용어**: 설명 1\n"
        "[^1]: **용어**: 설명 2\n"
    )
    flags2 = validate_red_flags(bad_md2)
    assert any("각주 서식 위반: 각주 정의 중복 삽입" in f for f in flags2)

    # 3. 정상 정돈된 문서의 경우 각주 관련 위반이 없어야 함
    good_md = clean_markdown_typography(bad_md1)
    flags3 = validate_red_flags(good_md)
    assert not any("각주 서식 위반" in f for f in flags3)


def test_malformed_table_header_detection_and_self_healing():
    """줄바꿈 누락으로 앞 텍스트/출처와 붙은 표 헤더를 Red Flags로 감지하고,
    clean_markdown_typography를 통해 독립된 정상 표로 자율 치유하는지 검증."""
    from app.utils import validate_red_flags

    malformed_md = (
        "## 1. 개요\n"
        "이차전지 핵심 소재 설명입니다.\n\n"
        "*(자료: 기관)* <출처: [보고서](/api/doc)>| 구분 | 설명 | 기능 |\n"
        "|:---|:---|:---|\n"
        "| 양극재 | 배터리 출력 | 에너지 밀도 |\n"
        "| 음극재 | 리튬 흡수 | 배터리 수명 |\n"
    )

    # 1. 치유 전: Red Flags 감지
    flags_before = validate_red_flags(malformed_md, check_metadata=False)
    assert any("표 문법 파손: 개행 누락으로 본문/출처와 결합된 파손 표 헤더 감지" in f for f in flags_before)

    # 2. 치유 후: 빈 줄(\n\n)이 삽입되어 표가 정상 분리됨
    healed_md = clean_markdown_typography(malformed_md)
    assert "*(자료: 기관)* <출처: [보고서](/api/doc)>\n\n| 구분 | 설명 | 기능 |" in healed_md

    # 3. 치유 후: Red Flags 미검출
    flags_after = validate_red_flags(healed_md, check_metadata=False)
    assert not any("표 문법 파손" in f for f in flags_after)


def test_table_with_hyphen_cell_is_not_split_and_broken_table_is_healed():
    """표 내부에 빈 셀(| |)과 하이픈 셀(| - |)이 연속될 때 표 헤더로 오인하여
    표를 두 동강 내지 않으며, 이미 쪼개진 표도 자동 봉합하는지 검증."""
    from app.utils import validate_red_flags

    # 1. 정상 표가 clean_markdown_typography에 의해 파손되지 않아야 함
    valid_table_md = (
        "| 구분 | As-Is | 구분 | To-Be(예시) |\n"
        "|:---|:---|:---|:---|\n"
        "| HBM | | HBM | 최근 맥락 데이터(KV 캐시), AI 모델 가중치 |\n"
        "| | Hot 데이터주1) | | Hot 데이터 |\n"
        "| | | | Warm 데이터 일부 |\n"
        "| - | 성능 공백주2) | HBF | Warm 데이터 |\n"
        "| SSD | Warm 데이터 일부 | SSD | 운영 및 사용 기록 |\n"
    )
    cleaned = clean_markdown_typography(valid_table_md)
    flags = validate_red_flags(cleaned, check_metadata=False)
    assert not any("표 문법 파손" in f for f in flags), f"정상 표가 파손되었습니다: {flags}\n{cleaned}"
    assert "| \n\n| | | Warm 데이터 일부 |" not in cleaned

    # 2. 과거 버그로 이미 두 동강 난 표(| \n\n| | | ...)도 clean_markdown_typography로 자동 봉합되어야 함
    already_broken_md = (
        "| 구분 | As-Is | 구분 | To-Be(예시) |\n"
        "|:---|:---|:---|:---|\n"
        "| HBM | | HBM | 최근 맥락 데이터(KV 캐시), AI 모델 가중치 |\n"
        "| | Hot 데이터주1) | | Hot 데이터 |\n"
        "| \n\n"
        "| | | Warm 데이터 일부 |\n"
        "| - | 성능 공백주2) | HBF | Warm 데이터 |\n"
        "| SSD | Warm 데이터 일부 | SSD | 운영 및 사용 기록 |\n"
    )
    repaired = clean_markdown_typography(already_broken_md)
    repaired_flags = validate_red_flags(repaired, check_metadata=False)
    assert not any("표 문법 파손" in f for f in repaired_flags), f"파손된 표가 복구되지 않았습니다: {repaired_flags}\n{repaired}"


def test_clean_markdown_typography_no_redos_on_large_tables():
    """200페이지급 대형 문서에서 파이프(|)와 일반 줄이 수백 번 반복될 때
    Catastrophic Backtracking(무한 루프) 없이 즉시(0.5초 이내) 처리되는지 검증."""
    import time
    from app.utils import validate_red_flags

    large_adversarial_md = "앞문장 | " + ("가나다 라마바 사아자 |\n일반줄 텍스트 " * 300) + "\n끝"
    t0 = time.time()
    cleaned = clean_markdown_typography(large_adversarial_md)
    validate_red_flags(cleaned, check_metadata=False)
    elapsed = time.time() - t0
    assert elapsed < 0.5, f"정규식 Catastrophic Backtracking(ReDoS) 감지: {elapsed:.2f}초 소요"


def test_clean_markdown_typography_heals_consecutive_images_with_captions():
    """설명 문맥 없이 연속으로 배치된 이미지 태그들에 대해
    각 이미지의 alt 기반 캡션을 부여하여 Visual Context Inlining 결함을 자율 치유하는지 검증."""
    from app.utils import validate_red_flags

    consecutive_images_md = (
        "## 1. 과학 연구에서의 AI 활용\n\n"
        "AI는 새로운 물리 법칙 발견과 이론 검증을 가속화하는 역할을 직접적으로 증명함.\n\n"
        "![도표/인포그래픽 (AI는 한 달 분량의 LIGO 데이터를 단 7분 만에 분석)](/api/assets/doc1/p1_image_010.png)\n\n"
        "![도표/인포그래픽 (AI는 한 달 분량의 LIGO 데이터를 단 7분 만에 분석)](/api/assets/doc1/p1_image_011.png)\n\n"
        "## 2. 다음 장\n"
    )

    # 1. 원본 상태에서는 이미지 연속 덤프 Red Flag가 발생해야 함
    initial_flags = validate_red_flags(consecutive_images_md, check_metadata=False)
    assert any("이미지 연속 덤프" in f for f in initial_flags)

    # 2. clean_markdown_typography 적용 후 각 이미지 태그에 캡션이 명시되어 Red Flag가 해소되어야 함
    cleaned = clean_markdown_typography(consecutive_images_md)
    cleaned_flags = validate_red_flags(cleaned, check_metadata=False)
    assert not any("이미지 연속 덤프" in f for f in cleaned_flags), f"연속 덤프 결함이 남아있습니다: {cleaned_flags}\n{cleaned}"
    assert "/api/assets/doc1/p1_image_010.png" in cleaned
    assert "/api/assets/doc1/p1_image_011.png" in cleaned
    assert "*(" in cleaned  # 캡션 라인 생성 확인





