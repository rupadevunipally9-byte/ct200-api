from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def now():
    return datetime.now(timezone.utc)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)


class Version(Base):
    __tablename__ = "versions"
    __table_args__ = (UniqueConstraint("document_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    number: Mapped[int]
    source_file: Mapped[str] = mapped_column(String)
    file_sha256: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(default=now)


class LogicalNode(Base):
    """The identity of a section that stays the same across versions."""
    __tablename__ = "logical_nodes"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))


class NodeVersion(Base):
    """One section as it looks in one specific version. Never edited after saving."""
    __tablename__ = "node_versions"
    __table_args__ = (UniqueConstraint("version_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    logical_id: Mapped[int] = mapped_column(ForeignKey("logical_nodes.id"))
    version_id: Mapped[int] = mapped_column(ForeignKey("versions.id"))
    number: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    level: Mapped[int]
    position: Mapped[int]          # order of appearance in the PDF
    page: Mapped[int]
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("node_versions.id"), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String)
    change_status: Mapped[str] = mapped_column(String)   # new / added / unchanged / changed
    match_method: Mapped[str] = mapped_column(String)    # new / number+title / title-only