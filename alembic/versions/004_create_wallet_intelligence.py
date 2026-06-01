"""create_wallet_intelligence_tables

Revision ID: 004_wallet_intelligence
Revises: 003_wallet_metrics
Create Date: 2026-05-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "004_wallet_intelligence"
down_revision: Union[str, None] = "003_wallet_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # wallet_nodes
    op.create_table(
        "wallet_nodes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("wallet_address", sa.String(44), unique=True, nullable=False),
        sa.Column("interaction_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("cluster_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("cluster_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("wallet_type", sa.String(20), nullable=False, server_default="UNKNOWN"),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("metadata", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_wallet_nodes_wallet", "wallet_nodes", ["wallet_address"], unique=True)
    op.create_index("ix_wallet_nodes_cluster", "wallet_nodes", ["cluster_id"])
    op.create_index("ix_wallet_nodes_type", "wallet_nodes", ["wallet_type"])

    # wallet_edges
    op.create_table(
        "wallet_edges",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("from_wallet", sa.String(44), nullable=False),
        sa.Column("to_wallet", sa.String(44), nullable=False),
        sa.Column("edge_type", sa.String(20), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False, server_default="0"),
        sa.Column("decay_weight", sa.Float(), nullable=False, server_default="0"),
        sa.Column("interaction_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_interaction", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_wallet_edges_from", "wallet_edges", ["from_wallet"])
    op.create_index("ix_wallet_edges_to", "wallet_edges", ["to_wallet"])
    op.create_index("ix_wallet_edges_pair", "wallet_edges", ["from_wallet", "to_wallet"], unique=True)
    op.create_index("ix_wallet_edges_type", "wallet_edges", ["edge_type"])

    # wallet_clusters
    op.create_table(
        "wallet_clusters",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("cluster_id", sa.String(64), nullable=False),
        sa.Column("wallet_address", sa.String(44), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cluster_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_wallet_clusters_cluster", "wallet_clusters", ["cluster_id"])
    op.create_index("ix_wallet_clusters_wallet", "wallet_clusters", ["wallet_address"])
    op.create_index("ix_wallet_clusters_version", "wallet_clusters", ["cluster_id", "cluster_version"])

    # wallet_cluster_history
    op.create_table(
        "wallet_cluster_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("cluster_id", sa.String(64), nullable=False),
        sa.Column("wallet_address", sa.String(44), nullable=False),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("old_cluster_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("new_cluster_id", sa.String(64), nullable=False),
        sa.Column("confidence_shift", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reason", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_cluster_history_cluster", "wallet_cluster_history", ["cluster_id"])
    op.create_index("ix_cluster_history_wallet", "wallet_cluster_history", ["wallet_address"])
    op.create_index("ix_cluster_history_time", "wallet_cluster_history", ["created_at"])

    # wallet_features
    op.create_table(
        "wallet_features",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("wallet_address", sa.String(44), nullable=False),
        sa.Column("time_window", sa.String(10), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False, server_default="0"),
        sa.Column("tx_frequency", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("avg_interval", sa.Float(), nullable=False, server_default="0"),
        sa.Column("token_diversity", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("buy_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("sell_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("transfer_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("buy_sell_ratio", sa.Float(), nullable=False, server_default="0"),
        sa.Column("interaction_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("features_json", JSONB(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_wallet_features_wallet", "wallet_features", ["wallet_address"])
    op.create_index("ix_wallet_features_window", "wallet_features", ["wallet_address", "time_window"])
    op.create_index("ix_wallet_features_time", "wallet_features", ["computed_at"])


def downgrade() -> None:
    op.drop_table("wallet_features")
    op.drop_table("wallet_cluster_history")
    op.drop_table("wallet_clusters")
    op.drop_table("wallet_edges")
    op.drop_table("wallet_nodes")
