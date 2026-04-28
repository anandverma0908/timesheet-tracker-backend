"""
scripts/rekey_tickets.py

Reassigns jira_key for every existing ticket so each space (pod) has its own
sequential prefix:  DPAI -> DPAI-1, DPAI-2 …  TRK -> TRK-1, TRK-2 …

Run once from the backend root:
    python3 -m scripts.rekey_tickets
    python3 -m scripts.rekey_tickets --dry-run   # preview only
"""

import os
import sys
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.core.database import engine


def _extract_num(jira_key: str) -> int:
    try:
        return int(jira_key.rsplit("-", 1)[-1])
    except (ValueError, IndexError):
        return 0


def run(dry_run: bool = False):
    # Use raw psycopg2 connection for reliable DDL + DML in one transaction
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()

        # ── 1. Load all tickets ───────────────────────────────────────────────
        cur.execute(
            "SELECT id, org_id, jira_key, project_key, pod "
            "FROM jira_tickets ORDER BY org_id, pod NULLS LAST, jira_key"
        )
        rows = cur.fetchall()
        # rows: (id, org_id, jira_key, project_key, pod)

        groups: dict = defaultdict(list)
        for row in rows:
            id_, org_id, jira_key, project_key, pod = row
            bucket = (pod or project_key or "TRKLY").strip().upper()
            groups[(org_id, bucket)].append(row)

        for k in groups:
            groups[k].sort(key=lambda r: _extract_num(r[2]))  # sort by jira_key number

        # ── 2. Build mapping ──────────────────────────────────────────────────
        key_map: dict[str, str] = {}
        updates: list[dict] = []

        for (org_id, pod), ticket_rows in groups.items():
            for n, row in enumerate(ticket_rows, start=1):
                id_, _, jira_key, project_key, _ = row
                new_key = f"{pod}-{n}"
                key_map[jira_key] = new_key
                if jira_key != new_key:
                    updates.append({"id": id_, "new_key": new_key, "new_proj": pod})

        print(f"Tickets to rekey: {len(updates)} / {len(rows)}")

        if dry_run:
            id_to_key = {r[0]: r[2] for r in rows}
            for u in updates[:40]:
                print(f"  {id_to_key[u['id']]:20s}  →  {u['new_key']}")
            if len(updates) > 40:
                print(f"  … and {len(updates) - 40} more")
            print("Dry run – no changes committed.")
            return

        # ── 3. Apply all updates in a single transaction ───────────────────────
        # Drop unique constraint to allow intermediate states
        print("Dropping unique constraint uq_org_jira_key …")
        cur.execute("ALTER TABLE jira_tickets DROP CONSTRAINT IF EXISTS uq_org_jira_key")

        # Pass 1: rename to temp keys
        print("Pass 1: rename to temp keys …")
        for u in updates:
            cur.execute(
                "UPDATE jira_tickets SET jira_key = %s, project_key = %s WHERE id = %s",
                (f"__tmp__{u['id']}", u["new_proj"], u["id"]),
            )

        # Pass 2: assign final keys
        print("Pass 2: assign final keys …")
        for u in updates:
            cur.execute(
                "UPDATE jira_tickets SET jira_key = %s WHERE id = %s",
                (u["new_key"], u["id"]),
            )

        # Restore unique constraint
        print("Restoring unique constraint …")
        cur.execute(
            "ALTER TABLE jira_tickets ADD CONSTRAINT uq_org_jira_key UNIQUE (org_id, jira_key)"
        )

        # Update ticket_links.target_key
        print("Updating ticket_links …")
        cur.execute("SELECT id, target_key FROM ticket_links")
        for lid, target_key in cur.fetchall():
            new_target = key_map.get(target_key)
            if new_target and new_target != target_key:
                cur.execute(
                    "UPDATE ticket_links SET target_key = %s WHERE id = %s",
                    (new_target, lid),
                )

        # Update tests.ticket_key
        try:
            cur.execute("SELECT id, ticket_key FROM tests WHERE ticket_key IS NOT NULL")
            for tid, ticket_key in cur.fetchall():
                new_tk = key_map.get(ticket_key)
                if new_tk and new_tk != ticket_key:
                    cur.execute(
                        "UPDATE tests SET ticket_key = %s WHERE id = %s",
                        (new_tk, tid),
                    )
        except Exception:
            pass

        raw.commit()
        print(f"Done. {len(updates)} tickets rekeyed.")

    except Exception as e:
        raw.rollback()
        print(f"ERROR – rolled back: {e}")
        raise
    finally:
        raw.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
