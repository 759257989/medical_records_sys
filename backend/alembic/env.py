# backend/alembic/env.py
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# 让 alembic 能 import 到 app 包（从 backend/ 运行）
sys.path.append(os.getcwd())

from app.core.config import settings           # noqa: E402
from app.models import Base                     # noqa: E402  (导入即注册了全部表)

config = context.config

# Alembic 用同步驱动跑迁移：把运行时的 +asyncpg 换成 +psycopg
config.set_main_option(
    "sqlalchemy.url",
    settings.database_url.replace("+asyncpg", "+psycopg"),
)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()