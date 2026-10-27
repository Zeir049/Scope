"""analysis_results.visual_json — LLM 원본 시각화 JSON 전용 컬럼

raw_output은 실패 기록({error, stage}) 용도로 되돌리고, 시각화 원본
(prompt_result_1 포맷)은 전용 컬럼에 보관한다 (용도 혼재 해소).

Revision ID: 0003_visual_json
Revises: 0002_extensions
Create Date: 2026-08-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_visual_json"
down_revision: Union[str, None] = "0002_extensions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "analysis_results",
        sa.Column("visual_json", postgresql.JSONB, nullable=True),
    )
    # 기존에 raw_output에 들어간 시각화 원본(성공 케이스)을 새 컬럼으로 이관.
    # 실패 기록({error, stage})은 raw_output에 그대로 둔다.
    op.execute(
        """
        UPDATE analysis_results
        SET visual_json = raw_output, raw_output = NULL
        WHERE raw_output IS NOT NULL AND NOT (raw_output ? 'error')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE analysis_results
        SET raw_output = visual_json
        WHERE visual_json IS NOT NULL AND raw_output IS NULL
        """
    )
    op.drop_column("analysis_results", "visual_json")
