"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-11-23 09:21:18.611913
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('app_settings',
    sa.Column('key', sa.String(length=48), nullable=False),
    sa.Column('value', sa.JSON(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_app_settings'))
    )
    op.create_table('bank_rates',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('symbol', sa.String(length=24), nullable=False),
    sa.Column('buy', sa.Numeric(precision=38, scale=12), nullable=True),
    sa.Column('sell', sa.Numeric(precision=38, scale=12), nullable=True),
    sa.Column('cross_rate', sa.Numeric(precision=38, scale=12), nullable=True),
    sa.Column('source_ts', sa.DateTime(timezone=True), nullable=True),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_bank_rates'))
    )
    op.create_index('ix_bank_rates_source_symbol_received', 'bank_rates', ['source', 'symbol', 'received_at'], unique=False)
    op.create_table('exchange_rates',
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('symbol', sa.String(length=24), nullable=False),
    sa.Column('bid', sa.Numeric(precision=38, scale=12), nullable=True),
    sa.Column('ask', sa.Numeric(precision=38, scale=12), nullable=True),
    sa.Column('last', sa.Numeric(precision=38, scale=12), nullable=True),
    sa.Column('bid_size', sa.Numeric(precision=38, scale=12), nullable=True),
    sa.Column('ask_size', sa.Numeric(precision=38, scale=12), nullable=True),
    sa.Column('volume_24h', sa.Numeric(precision=38, scale=12), nullable=True),
    sa.Column('quote_volume_24h', sa.Numeric(precision=38, scale=12), nullable=True),
    sa.Column('source_ts', sa.DateTime(timezone=True), nullable=True),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('source', 'symbol', name=op.f('pk_exchange_rates'))
    )
    op.create_table('exchange_status',
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('kind', sa.String(length=8), nullable=False),
    sa.Column('is_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('ws_connected', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('consecutive_errors', sa.Integer(), server_default='0', nullable=False),
    sa.Column('total_errors', sa.Integer(), server_default='0', nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('source', name=op.f('pk_exchange_status'))
    )
    op.create_table('price_history',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('symbol', sa.String(length=24), nullable=False),
    sa.Column('resolution', sa.String(length=2), nullable=False),
    sa.Column('bucket_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('price_kind', sa.String(length=8), nullable=False),
    sa.Column('open', sa.Numeric(precision=38, scale=12), nullable=False),
    sa.Column('high', sa.Numeric(precision=38, scale=12), nullable=False),
    sa.Column('low', sa.Numeric(precision=38, scale=12), nullable=False),
    sa.Column('close', sa.Numeric(precision=38, scale=12), nullable=False),
    sa.Column('bid', sa.Numeric(precision=38, scale=12), nullable=True),
    sa.Column('ask', sa.Numeric(precision=38, scale=12), nullable=True),
    sa.Column('samples', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_price_history')),
    sa.UniqueConstraint('source', 'symbol', 'resolution', 'bucket_start', name='uq_price_history_bucket')
    )
    op.create_index('ix_price_history_resolution_bucket', 'price_history', ['resolution', 'bucket_start'], unique=False)
    op.create_table('source_errors',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_source_errors'))
    )
    op.create_index(op.f('ix_source_errors_created_at'), 'source_errors', ['created_at'], unique=False)
    op.create_index('ix_source_errors_source_created', 'source_errors', ['source', 'created_at'], unique=False)
    op.create_table('tracked_assets',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('symbol', sa.String(length=24), nullable=False),
    sa.Column('kind', sa.String(length=8), nullable=False),
    sa.Column('base', sa.String(length=12), nullable=False),
    sa.Column('quote', sa.String(length=12), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('added_by', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tracked_assets')),
    sa.UniqueConstraint('symbol', name=op.f('uq_tracked_assets_symbol'))
    )
    op.create_table('users',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('telegram_id', sa.BigInteger(), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=True),
    sa.Column('first_name', sa.String(length=128), nullable=True),
    sa.Column('is_blocked', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    op.create_index(op.f('ix_users_telegram_id'), 'users', ['telegram_id'], unique=True)
    op.create_table('alerts',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('type', sa.String(length=24), nullable=False),
    sa.Column('symbol', sa.String(length=24), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=True),
    sa.Column('threshold', sa.Numeric(precision=38, scale=12), nullable=False),
    sa.Column('window_minutes', sa.Integer(), nullable=True),
    sa.Column('cooldown_minutes', sa.Integer(), server_default='15', nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('armed', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('last_triggered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_alerts_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_alerts'))
    )
    op.create_index('ix_alerts_active', 'alerts', ['is_active'], unique=False)
    op.create_index(op.f('ix_alerts_user_id'), 'alerts', ['user_id'], unique=False)
    op.create_table('user_settings',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('language', sa.String(length=2), server_default='ru', nullable=False),
    sa.Column('display_currency', sa.String(length=8), server_default='USDT', nullable=False),
    sa.Column('notify_interval_min', sa.Integer(), server_default='5', nullable=False),
    sa.Column('alerts_muted_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('arb_min_net_pct', sa.Numeric(precision=10, scale=4), server_default='0.3', nullable=False),
    sa.Column('chart_period', sa.String(length=4), server_default='24h', nullable=False),
    sa.Column('chart_theme', sa.String(length=8), server_default='dark', nullable=False),
    sa.Column('watchlist', sa.JSON(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_settings_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_user_settings'))
    )
    op.create_table('alert_history',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('alert_id', sa.BigInteger(), nullable=True),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('alert_type', sa.String(length=24), nullable=False),
    sa.Column('symbol', sa.String(length=24), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('value', sa.Numeric(precision=38, scale=12), nullable=True),
    sa.Column('delivered', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('triggered_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['alert_id'], ['alerts.id'], name=op.f('fk_alert_history_alert_id_alerts'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_alert_history_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_alert_history'))
    )
    op.create_index('ix_alert_history_user_triggered', 'alert_history', ['user_id', 'triggered_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_alert_history_user_triggered', table_name='alert_history')
    op.drop_table('alert_history')
    op.drop_table('user_settings')
    op.drop_index(op.f('ix_alerts_user_id'), table_name='alerts')
    op.drop_index('ix_alerts_active', table_name='alerts')
    op.drop_table('alerts')
    op.drop_index(op.f('ix_users_telegram_id'), table_name='users')
    op.drop_table('users')
    op.drop_table('tracked_assets')
    op.drop_index('ix_source_errors_source_created', table_name='source_errors')
    op.drop_index(op.f('ix_source_errors_created_at'), table_name='source_errors')
    op.drop_table('source_errors')
    op.drop_index('ix_price_history_resolution_bucket', table_name='price_history')
    op.drop_table('price_history')
    op.drop_table('exchange_status')
    op.drop_table('exchange_rates')
    op.drop_index('ix_bank_rates_source_symbol_received', table_name='bank_rates')
    op.drop_table('bank_rates')
    op.drop_table('app_settings')
