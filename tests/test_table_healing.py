"""마크다운 표(Table) 들여쓰기 평탄화 및 표 행 분리 방지 자가 치유 단위 테스트."""

import re
from pathlib import Path
import pytest

from app.utils import heal_markdown_table_boundaries, clean_markdown_typography


SAMPLE_INDENTED_TABLE_MD = """## 4. 주요업체

- **SK하이닉스 (000660)**  
    HBM의 세대별 성능은 다음과 같습니다:

    | 특징 | HBM3 | HBM3E | HBM4 |
|:---|:---|:---|:---|
    | 스택당 최대 대역폭 (GB/s) | 819 | >1,229 | >2,048 |
    | I/O (버스) 폭 (bits) | 1024 | 1024 | 2048 |
    | 핀당 최대 속도 (Gbps) | 6.4 | 9.8 | 8.0+ |
    | 최대 적층 단수 (Dies) | 12 | 16 | 16 |
    | 스택당 최대 용량 (GB) | 24 | 48 | 64 |
    | 베이스 다이 공정 | 레거시(Legacy) | 레거시(Legacy) | 첨단 로직 |

- **삼성전자 (005930)**
"""

SAMPLE_TORN_TABLE_MD = """| 구분 | GEN1 | GEN2 |
| :--- | :--- | :--- |

| 용량 (GB) | 512 | 768 |

| 대역폭 (GB/s) | 1,228.8 | 1,781.8 |
"""


def test_indented_table_rows_flattened_to_line_start():
    """불릿 하위의 4칸 들여쓰기된 표 행들이 라인 시작부(^|)로 평탄화되어 단일 마크다운 표로 치유되는지 검증."""
    healed = heal_markdown_table_boundaries(SAMPLE_INDENTED_TABLE_MD)

    # 1. 모든 표 행의 앞 들여쓰기가 제거되어 '^|'로 정렬되어야 함
    lines = [line for line in healed.splitlines() if "|" in line]
    assert len(lines) >= 8
    for line in lines:
        assert line.startswith("|"), f"표 행이 라인 맨 앞(|)에서 시작하지 않습니다: '{line}'"

    # 2. 표 데이터 행 사이에 빈 줄이 끼어있지 않아야 함
    table_block_match = re.search(r'(\| 특징 \|[\s\S]+?\| 베이스 다이 공정[^\n]+\|)', healed)
    assert table_block_match is not None
    table_block = table_block_match.group(1)
    assert "\n\n" not in table_block, f"표 블록 내부에 빈 줄이 존재합니다:\n{table_block}"


def test_torn_table_rows_sutured_into_single_table():
    """행마다 빈 줄(\\n\\n)이 들어가 두 동강 난 표가 단일 연속 표로 봉합되는지 검증."""
    healed = heal_markdown_table_boundaries(SAMPLE_TORN_TABLE_MD)

    # 행 사이 빈 줄이 모두 제거되어 단일 표 블록이 되어야 함
    assert "\n\n" not in healed.strip()
    table_lines = healed.strip().splitlines()
    assert len(table_lines) == 4
    for line in table_lines:
        assert line.startswith("|") and line.endswith("|")


def test_app_js_regex_does_not_tear_indented_table():
    """app.js의 전처리기 정규식이 들여쓰기된 표 행 뒤에 빈 줄을 삽입하지 않는지 검증."""
    app_js = Path("app/static/app.js").read_text(encoding="utf-8")

    # 1. 기존 버그 정규식(/(\|[^\n]*\|)[ \t]*\n(?=[^|\n])/g)이 제거되었는지 확인
    assert r"text.replace(/(\|[^\n]*\|)[ \t]*\n(?=[^|\n])/g" not in app_js

    # 2. 표 들여쓰기 평탄화 정규식이 존재하는지 확인
    assert r"text.replace(/^[ \t]+(\|[^\n]+\|[ \t]*)$/gm" in app_js or "replace(/^[ \\t]+(\\|[^\\n]+\\|[ \\t]*)$/gm" in app_js
