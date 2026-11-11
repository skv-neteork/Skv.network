"""Collision-safe account name -> storage name mapping.
The storage name of an account (db file, hnsw index, staging dir) is account_name(email): letters, digits, '_' and '-'
(case kept). Different emails can map to the same name ("a.b@x.io" and "ab@x.io"), and older helper mappings (lower-cased,
hyphen-less, '+') can equal ANOTHER account's real name ("bench-locomo@..." -> "benchlocomo..."). 2026-11-11: purging
"bench-locomo" deleted the db file of "benchlocomo". Rules:
  * a new account whose storage name equals an existing account's is refused at registration;
  * a purge never removes a name that is the primary storage name of another registered account, and is refused when
    its own primary storage name is shared with another registered account (the data cannot be told apart);
  * every mapper of the code base uses account_name (memory_lines used a different one)."""
import re


def account_name(user_id) -> str:
    """Canonical storage name (identical to account_memory.account_db_name / semantic.account_name before this module)."""
    return "".join(c for c in (user_id or "") if c.isalnum() or c in ("_", "-"))


def legacy_names(user_id) -> set:
    """Other names old code paths derived from the same email (purge cleans files under them when they are not
    another account's real name)."""
    u = user_id or ""
    return {
        re.sub(r"[^a-z0-9_]", "", u.lower()),                               # old memory_lines mapping
        "".join(c for c in u if c.isalnum() or c in ("_", "-", "+")),
        "".join(c for c in u if c.isalnum() or c in ("_", "-", "+", "@", ".")),
    }


def conflicting_accounts(user_id, registered) -> list:
    """Registered emails (other than user_id) whose primary storage name equals the primary name of user_id."""
    me = account_name(user_id)
    return sorted(e for e in registered if e != user_id and me and account_name(e) == me)


def protected_names(user_id, registered) -> set:
    """Primary storage names of all OTHER registered accounts: a purge of user_id must never touch them."""
    return {account_name(e) for e in registered if e != user_id and account_name(e)}


def collisions(registered) -> list:
    """Groups of registered emails sharing a storage name, also counting the legacy lower-cased/hyphen-less mapping
    when it equals another account's real name (for reports; names only)."""
    reg = list(registered)
    by = {}
    for e in reg:
        by.setdefault(account_name(e), []).append(e)
    out = [sorted(v) for v in by.values() if len(v) > 1]
    prim = {account_name(e): e for e in reg}
    for e in reg:
        for n in legacy_names(e):
            o = prim.get(n)
            if o and o != e and sorted([e, o]) not in out:
                out.append(sorted([e, o]))
    return out


def registered_emails(conn) -> list:
    try:
        return [r[0] for r in conn.execute("select email from users")]
    except Exception:
        return []
