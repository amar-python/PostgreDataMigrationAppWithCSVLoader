"""The screens a signed-in person can open. Each is views/<url_path>.py with a render()."""

import auth

# (action in auth.PERMISSIONS that lets a role see it, sidebar title, url path). Later issues add theirs.
SCREENS: list[tuple[str, str, str]] = [
    ("read_rows", "Review", "review"),
    ("list_files", "Import history", "history"),
]


def allowed_screens(role: str) -> list[str]:
    """URL paths of the screens this role may open, in SCREENS order."""
    return [path for action, _title, path in SCREENS if role in auth.PERMISSIONS[action]]
