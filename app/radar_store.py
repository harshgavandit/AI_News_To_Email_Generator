"""Private verified-mailbox preferences and accepted catch-up delivery history."""
import json
import time

from sqlalchemy import Column, Float, Integer, String, Table, Text, delete, inspect, select

from app.launch_store import schema

mail_radars = Table("brief_mail_radars", schema,
    Column("mailbox", String(64), primary_key=True), Column("profile", Text, nullable=False),
    Column("updated", Float, nullable=False))
mail_seen = Table("brief_mail_seen_events", schema,
    Column("mailbox", String(64), primary_key=True), Column("event_id", String(32), primary_key=True),
    Column("version", String(12), nullable=False), Column("accepted_at", Float, nullable=False))
mail_event_reservations = Table("brief_mail_event_reservations", schema,
    Column("delivery_id", String(64), primary_key=True), Column("mailbox", String(64), primary_key=True),
    Column("events", Text, nullable=False), Column("created", Float, nullable=False))


def ready(store):
    if not hasattr(store, "_radar_tables_ready"):
        store._radar_tables_ready = all(inspect(store.engine).has_table(table.name) for table in
            (mail_radars, mail_seen, mail_event_reservations))
    return store._radar_tables_ready


def profiles(store, mailboxes):
    if not mailboxes or not ready(store):
        return {}
    with store.engine.connect() as conn:
        return {row.mailbox: json.loads(row.profile) for row in conn.execute(
            select(mail_radars).where(mail_radars.c.mailbox.in_(mailboxes)))}


def histories(store, mailboxes):
    if not mailboxes or not ready(store):
        return {}
    with store.engine.connect() as conn:
        rows = conn.execute(select(mail_seen).where(mail_seen.c.mailbox.in_(mailboxes),
            mail_seen.c.accepted_at >= time.time() - 90 * 86400))
        result = {}
        for row in rows:
            result.setdefault(row.mailbox, {})[row.event_id] = row.version
        return result


def save_profile(store, mailbox, profile):
    with store.engine.begin() as conn:
        stmt = store.insert(mail_radars).values(mailbox=mailbox, profile=json.dumps(profile, ensure_ascii=False), updated=time.time())
        conn.execute(stmt.on_conflict_do_update(index_elements=[mail_radars.c.mailbox],
            set_={"profile": stmt.excluded.profile, "updated": stmt.excluded.updated}))


def remove_profile(store, mailbox):
    with store.engine.begin() as conn:
        for table in (mail_radars, mail_seen, mail_event_reservations):
            conn.execute(delete(table).where(table.c.mailbox == mailbox))


def reserve_events(conn, store, delivery_id, mailbox, entries):
    if entries:
        stmt = store.insert(mail_event_reservations).values(delivery_id=delivery_id, mailbox=mailbox,
            events=json.dumps(entries), created=time.time())
        conn.execute(stmt.on_conflict_do_nothing())


def accept_events(conn, store, delivery_id, *, allowed_mailboxes=None):
    rows = conn.execute(select(mail_event_reservations).where(mail_event_reservations.c.delivery_id == delivery_id)).mappings().all()
    for row in rows:
        if allowed_mailboxes is not None and row["mailbox"] not in allowed_mailboxes:
            continue
        for item in json.loads(row["events"]):
            stmt = store.insert(mail_seen).values(mailbox=row["mailbox"], event_id=item["id"],
                version=item["version"], accepted_at=time.time())
            # A delayed acceptance must not regress a newer accepted event version.
            conn.execute(stmt.on_conflict_do_update(index_elements=[mail_seen.c.mailbox, mail_seen.c.event_id],
                set_={"version": stmt.excluded.version, "accepted_at": stmt.excluded.accepted_at},
                where=mail_seen.c.version.cast(Integer) <= int(item["version"])))
    completed = [row["mailbox"] for row in rows if allowed_mailboxes is None or row["mailbox"] in allowed_mailboxes]
    if completed:
        conn.execute(delete(mail_event_reservations).where(mail_event_reservations.c.delivery_id == delivery_id,
            mail_event_reservations.c.mailbox.in_(completed)))


def prune(conn, now):
    conn.execute(delete(mail_seen).where(mail_seen.c.accepted_at < now - 90 * 86400))
    conn.execute(delete(mail_event_reservations).where(mail_event_reservations.c.created < now - 7 * 86400))
