"""Profiles model — reusable SSH credentials (login name + keyring-stored password).

Profiles are stored in ~/.sshmap_profiles.json and shared across all projects.
Passwords are NOT saved to disk — they're stored in the system credential store (keyring) via CredentialManager.
This prevents plaintext passwords from appearing in config files.
"""

import json
import os
from dataclasses import dataclass, asdict
from typing import Optional, List


@dataclass
class Profile:
    """Reusable SSH profile: login name and password (password stored in keyring)."""
    id: str  # unique identifier (8-char short UUID)
    name: str  # human-readable label shown in combobox
    user: str  # SSH username
    password: str = ""  # SSH password (optional — only used locally during edit, never persisted to disk)

    def __post_init__(self):
        # AUDIT v0.7.2 (medium #13): id is generated ONLY for new profiles.
        # Earlier any id whose length ≠ 8 was silently replaced on load — the link between
        # the profile and the keyring entry ("profile:{id}") was lost and the password
        # "disappeared". Now an existing id (of any length) is kept as-is.
        if not self.id:
            import uuid
            self.id = str(uuid.uuid4())[:8]


# ── Persistence helpers ────────────────────────────────────────────

def _profiles_path() -> str:
    """Return the path to the profiles JSON file."""
    home = os.path.expanduser("~")
    return os.path.join(home, ".sshmap_profiles.json")


# ── Credential Manager integration (lazy import) ────────────────

def _get_credential_manager():
    """Lazy-load credential manager singleton. Falls back gracefully."""
    try:
        from services.credential_manager import get_credential_manager as gcm
        return gcm()
    except Exception:
        # If keyring is unavailable, return None — password won't be persisted
        return None


# ── Persistence ────────────────────────────────────────────────

def load_profiles() -> List[Profile]:
    """Load all profiles from disk. Returns empty list on failure."""
    try:
        with open(_profiles_path(), "r", encoding="utf-8") as f:
            raw = json.load(f)
        # AUDIT v0.7.2 (medium #13): the id from the file is kept as-is — only an empty one
        # is generated (__post_init__). Corrupt entries are skipped, without breaking the load.
        profiles = []
        for p in raw or []:
            if not isinstance(p, dict):
                continue
            profiles.append(Profile(
                id=str(p.get("id") or ""),
                name=str(p.get("name", "")),
                user=str(p.get("user", "")),
            ))
        return profiles
    except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
        return []


def save_profiles(profiles: List[Profile]) -> None:
    """Save all profiles to disk.

    Passwords are stripped before saving — they live only in the system credential store (keyring).
    This prevents plaintext passwords from appearing in ~/.sshmap_profiles.json.
    """
    # Save passwords to keyring BEFORE stripping them from memory
    cm = _get_credential_manager()
    for p in profiles:
        if p.password:  # Only save non-empty passwords
            if cm and not cm.save_password(f"profile:{p.id}", p.password):
                pass  # Credential manager unavailable — password lost on restart

    data = []
    for p in profiles:
        d = asdict(p)
        d.pop("password", None)  # the password lives only in the keyring, not in the JSON
        data.append(d)
    # v0.9.4-fix: atomic write (tmp + fsync + os.replace) — like in storage/project.py;
    # a crash mid-way through a direct open/write corrupted the entire profiles file.
    tmp_path = _profiles_path() + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, _profiles_path())


def add_profile(name: str, user: str, password: str = "") -> Profile:
    """Create a new profile and persist it."""
    profiles = load_profiles()
    import uuid
    p = Profile(
        id=str(uuid.uuid4())[:8],
        name=name.strip(),
        user=user.strip(),
        password=password,
    )
    profiles.append(p)

    # AUDIT v0.7.2 (low #14): there is no separate keyring write anymore — save_profiles()
    # below does it in the same pass for all profiles with a non-empty password. Earlier the
    # new profile's password was written twice (here and in save_profiles) — useless extra I/O.
    save_profiles(profiles)
    return p


def update_profile(profile_id: str, name: str, user: str,
                   password: Optional[str] = None) -> Optional[Profile]:
    """Update an existing profile by ID.

    password:
        None — do not change the stored password (the keyring entry is kept as-is);
        ""   — clear the password;
        str  — set a new password.
    """
    profiles = load_profiles()
    for i, p in enumerate(profiles):
        if p.id == profile_id:
            p.name = name.strip()
            p.user = user.strip()

            if password is None:
                # "Do not change": keep the current password (from the keyring) for in-memory use
                p.password = get_profile_password(profile_id) or ""
            elif password:
                # Save password to keyring BEFORE potentially clearing it from memory
                cm = _get_credential_manager()
                if cm and not cm.save_password(f"profile:{p.id}", password):
                    pass  # Credential manager unavailable — password lost on restart
                p.password = password
            else:
                # Empty password means user wants to clear it
                cm = _get_credential_manager()
                if cm:
                    cm.delete_password(f"profile:{p.id}")
                p.password = ""

            save_profiles(profiles)
            return p
    return None


def delete_profile(profile_id: str) -> bool:
    """Remove a profile by ID. Returns True if deleted."""
    profiles = load_profiles()
    new_profiles = [p for p in profiles if p.id != profile_id]
    if len(new_profiles) == len(profiles):
        return False  # not found

    # Clean up credential store entry too
    cm = _get_credential_manager()
    if cm:
        cm.delete_password(f"profile:{profile_id}")

    save_profiles(new_profiles)
    return True


def get_profile_by_id(profile_id: str) -> Optional[Profile]:
    """Load a single profile by ID, including password from keyring."""
    # First load without password (from JSON)
    profiles = load_profiles()
    for p in profiles:
        if p.id == profile_id:
            # Try to restore password from credential manager
            cm = _get_credential_manager()
            if cm:
                saved_pw = cm.load_password(f"profile:{p.id}")
                if saved_pw:
                    p.password = saved_pw
            return p
    return None


def get_profile_password(profile_id: str) -> Optional[str]:
    """Directly retrieve a profile's password from the credential store.

    Use this when you need only the password (e.g., for SSH connect without editing).
    Returns None if no keyring backend is available or the profile has no stored password.
    """
    cm = _get_credential_manager()
    if not cm:
        return None
    return cm.load_password(f"profile:{profile_id}")
