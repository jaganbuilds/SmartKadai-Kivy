"""
SmartKadai Isolated Test UI Launcher.

Purpose:
Launches the SmartKadai Kivy UI strictly against an isolated temporary copy
of 'smartkadai_test.db', guaranteeing zero reads/writes to 'smartkadai.db'.

Strict Safety Rules:
1. Never connects to or modifies the live database ('smartkadai.db').
2. Resolves paths to absolute paths and asserts temp DB != live DB.
3. Clones a fresh temporary database exclusively from 'smartkadai_test.db'.
4. Verifies SHA-256 match before launching.
5. Overrides main.DB_PATH before SmartKadaiApp construction or execution.
6. Preserves the session database for post-test inspection without automatic deletion.
7. Does not copy session data back to the template or live database.
"""

import hashlib
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path


def calculate_sha256(file_path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest().upper()


def prepare_isolated_test_database(project_root: Path) -> Path:
    """Create and verify a fresh isolated temporary database from smartkadai_test.db."""
    live_db_path = (project_root / "smartkadai.db").resolve()
    test_template_path = (project_root / "smartkadai_test.db").resolve()

    # Rule 1: Assert live DB and test template exist
    if not live_db_path.exists():
        raise FileNotFoundError(f"Live database not found at: {live_db_path}")
    if not test_template_path.exists():
        raise FileNotFoundError(f"Test template database not found at: {test_template_path}")

    # Rule 1 & 2: Assert paths are different
    assert live_db_path != test_template_path, (
        "CRITICAL ERROR: Test template path points to live database!"
    )

    # Generate isolated session DB path
    session_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_db_path = (project_root / f"smartkadai_ui_session_{session_ts}.db").resolve()

    # Safety assertion against collision with live database
    assert session_db_path != live_db_path, (
        "CRITICAL ERROR: Session DB resolved to live database path!"
    )
    assert not session_db_path.exists(), (
        f"Session DB already exists at: {session_db_path}"
    )

    # Rule 2: Copy exclusively from test template, NEVER live DB
    shutil.copy2(test_template_path, session_db_path)

    # Rule 3: Verify temporary copy exists and SHA-256 matches test template
    if not session_db_path.exists():
        raise RuntimeError(f"Failed to create session database at: {session_db_path}")

    template_hash = calculate_sha256(test_template_path)
    session_hash = calculate_sha256(session_db_path)

    if template_hash != session_hash:
        # Clean up corrupted copy before failing
        if session_db_path.exists():
            session_db_path.unlink()
        raise ValueError(
            f"SHA-256 mismatch! Template: {template_hash}, Session: {session_hash}"
        )

    return session_db_path


def main_launcher(check_only: bool = False):
    """Main launcher entry point."""
    project_root = Path(__file__).parent.resolve()
    live_db_path = (project_root / "smartkadai.db").resolve()

    print("=" * 65)
    print(" SmartKadai Safe Test UI Launcher")
    print("=" * 65)

    # 1. Prepare and verify isolated test database
    session_db = prepare_isolated_test_database(project_root)
    session_hash = calculate_sha256(session_db)

    print(f"[OK] Live Database (Untouched) : {live_db_path}")
    print(f"[OK] Test Template Source     : {project_root / 'smartkadai_test.db'}")
    print(f"[OK] Active UI Session DB     : {session_db}")
    print(f"[OK] Initial SHA-256 Hash     : {session_hash}")

    # 2. Safety Refusal Gate
    if session_db == live_db_path or session_db.name == "smartkadai.db":
        raise SystemExit(
            "FATAL SAFETY ABORT: Active DB path matches live database! Launch refused."
        )

    # 3. Configure environment and import main
    os.environ["KIVY_NO_ARGS"] = "1"
    sys.path.insert(0, str(project_root))

    import main

    # 4. Enforce runtime database redirection
    main.DB_PATH = session_db
    print(f"[OK] Confirmed main.DB_PATH   : {main.DB_PATH}")

    # Final assertion before launch
    assert main.DB_PATH == session_db
    assert main.DB_PATH != live_db_path

    if check_only:
        print("\n[SUCCESS] All static/runtime safety checks PASSED.")
        print(f"[INFO] Preserved test session DB for inspection: {session_db}")
        print("[INFO] Check-only mode: UI launch skipped pending approval.")
        return session_db

    if "--skip-login" in sys.argv or "--bypass-login" in sys.argv:
        print("[INFO] --skip-login specified: launching directly to Dashboard.")
        def custom_build(self):
            self.auth = main.load_auth()
            self.setup_mode = False
            self.root = main.BoxLayout()
            self.show_dashboard()
            return self.root
        main.SmartKadaiApp.build = custom_build

    # 5. Launch the Kivy Application
    print("\n[LAUNCH] Starting SmartKadai Kivy UI against isolated test session DB...")
    app = main.SmartKadaiApp()
    try:
        app.run()
    finally:
        print("\n" + "=" * 65)
        print(" SmartKadai Test Session Closed")
        print("=" * 65)
        print(f"[INFO] Preserved session DB: {session_db}")
        print(f"[INFO] Post-session SHA-256: {calculate_sha256(session_db)}")
        print("[INFO] Live database remains pristine and untouched.")


if __name__ == "__main__":
    is_check = "--check-only" in sys.argv
    main_launcher(check_only=is_check)
