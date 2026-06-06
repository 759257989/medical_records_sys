# app/models/base.py
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有模型的基类；Base.metadata 汇总了全部表结构，供 Alembic 使用。"""
    pass