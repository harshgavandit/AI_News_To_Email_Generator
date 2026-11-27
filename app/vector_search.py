"""Optional PostgreSQL HNSW retrieval; portable archives keep their bounded fallback."""
import json
import struct

from sqlalchemy import Column, Float, MetaData, String, Table, and_, cast, inspect, literal, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.types import UserDefinedType

DIMENSIONS = 384
FORMAT = struct.Struct(f"<{DIMENSIONS}f")


class Vector(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **kw):
        return 'public.vector(384)'


vectors = Table("brief_semantic_index", MetaData(), Column("id", String(40), primary_key=True),
    Column("encoder", String(100), nullable=False), Column("title", String), Column("description", String),
    Column("embedding", Vector()))


def install(conn):
    try:
        with conn.begin_nested():
            conn.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
            conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
            namespace = conn.exec_driver_sql("SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='vector'").scalar()
            if namespace != "public":
                return False
            conn.exec_driver_sql("""CREATE TABLE IF NOT EXISTS brief_semantic_index (
                id varchar(40) PRIMARY KEY, encoder varchar(100) NOT NULL,
                title text NOT NULL, description text NOT NULL, embedding public.vector(384) NOT NULL)""")
            conn.exec_driver_sql("""CREATE INDEX IF NOT EXISTS brief_semantic_hnsw
                ON brief_semantic_index USING hnsw (embedding public.vector_cosine_ops)""")
        return True
    except DBAPIError:
        # Optional extension/permissions must not disable discovery or keyword search.
        return False


def ready(store):
    if store.engine.dialect.name != "postgresql":
        return False
    if not hasattr(store, "_semantic_index_ready"):
        store._semantic_index_ready = inspect(store.engine).has_table(vectors.name)
    return store._semantic_index_ready


def upsert(store, encoder, rows, *, conn=None):
    if not rows or not ready(store):
        return
    from sqlalchemy.dialects.postgresql import insert
    values = [{"id": row["id"], "encoder": encoder, "title": row["title"], "description": row["description"],
               "embedding": cast(literal(json.dumps(FORMAT.unpack(blob))), Vector())}
              for row, blob in rows if len(blob) == FORMAT.size]
    if not values:
        return
    stmt = insert(vectors).values(values)
    stmt = stmt.on_conflict_do_update(index_elements=[vectors.c.id],
        set_={key: stmt.excluded[key] for key in ("encoder", "title", "description", "embedding")})
    if conn is not None:
        conn.execute(stmt)
    else:
        with store.engine.begin() as connection:
            connection.execute(stmt)


def backfill(store, encoder, *, maximum=256):
    if not ready(store):
        return 0
    from app.launch_store import research_vectors
    joined = and_(research_vectors.c.id == vectors.c.id, research_vectors.c.encoder == vectors.c.encoder,
                  research_vectors.c.title == vectors.c.title, research_vectors.c.description == vectors.c.description)
    stmt = select(research_vectors).outerjoin(vectors, joined).where(research_vectors.c.encoder == encoder,
        vectors.c.id.is_(None)).limit(maximum)
    with store.engine.connect() as conn:
        rows = conn.execute(stmt).mappings().all()
    upsert(store, encoder, [(row, row["embedding"]) for row in rows])
    return len(rows)


def nearest(store, encoder, query_vector, *, hours, threshold=.42, limit=32, **filters):
    if not ready(store):
        return None
    from app.launch_store import articles
    value = cast(literal(json.dumps(FORMAT.unpack(query_vector))), Vector())
    # The extension lives in public even when the archive uses a different search path.
    distance = vectors.c.embedding.op("OPERATOR(public.<=>)", return_type=Float())(value)
    stmt = store.query(hours, **filters).join(vectors, and_(articles.c.id == vectors.c.id,
        vectors.c.encoder == encoder, articles.c.title == vectors.c.title,
        articles.c.description == vectors.c.description)).add_columns(distance.label("semantic_distance"))
    stmt = stmt.where(distance <= 1 - threshold).order_by(distance).limit(limit)
    with store.engine.connect() as conn:
        return [dict(row) for row in conn.execute(stmt).mappings()]
