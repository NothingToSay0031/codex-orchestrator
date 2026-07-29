#!/usr/bin/env python3
"""
Codex Orchestrator -- Installer
Pip install: none (stdlib only: tomllib, pathlib, shutil, re, datetime)
Requires: Python 3.11+
"""

import shutil
import re
import sys
from datetime import datetime
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
AGENT_SRC = SOURCE / ".codex" / "agents"
INJECT_FILE = SOURCE / "config-inject.toml"
BACKUP_SUFFIX = datetime.now().strftime("%Y%m%d-%H%M%S")


def target_dir(scope: str, project_dir: str = "") -> Path:
    if scope == "project":
        return Path(project_dir or ".") / ".codex"
    return Path.home() / ".codex"


def backup_root(target: Path) -> Path:
    return target / ".backup" / f"codex-orchestrator-{BACKUP_SUFFIX}"


def read_text(path: Path) -> str:
    """Read file, normalize line endings to \n."""
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def write_text(path: Path, content: str) -> None:
    """Write file with platform-native line endings."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.replace("\n", "\r\n"), encoding="utf-8")


# ── Step 1: Install agent TOML files ──────────────────────────────

def install_agents(target: Path, bk_root: Path, dry_run: bool = False) -> None:
    agent_target = target / "agents"
    if not dry_run:
        agent_target.mkdir(parents=True, exist_ok=True)

    installed, updated, skipped = 0, 0, 0

    for src in sorted(AGENT_SRC.glob("*.toml")):
        dst = agent_target / src.name
        src_content = src.read_text(encoding="utf-8")

        if dst.exists():
            dst_content = dst.read_text(encoding="utf-8")
            if src_content == dst_content:
                print(f"  SKIP   {src.name} (unchanged)")
                skipped += 1
                continue
            # Backup old before overwrite
            if not dry_run:
                backup_path = bk_root / "agents" / src.name
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, backup_path)
            print(f"  UPDATE {src.name}")
            updated += 1
        else:
            print(f"  INSTALL {src.name}")
            installed += 1

        if not dry_run:
            dst.write_text(src_content, encoding="utf-8")

    print(f"  Result: {installed} installed, {updated} updated, {skipped} unchanged")


# ── Step 2: Merge config.toml ─────────────────────────────────────

def extract_agents_block(content: str) -> str | None:
    """Extract the entire [agents] section from content."""
    m = re.search(r"(?m)^\[agents\].*?(?=^\s*\[(?!agents\.?)\w|\Z)", content, re.DOTALL)
    return m.group(0).rstrip() if m else None


def replace_agents_section(content: str, block: str) -> str:
    """Replace or insert the [agents] section."""
    m = re.search(r"(?m)^\[agents\].*?(?=^\s*\[(?!agents\.?)\w|\Z)", content, re.DOTALL)
    if m:
        return content[:m.start()] + block + content[m.end():]
    else:
        # Insert before [memories] or at end
        m_mem = re.search(r"(?m)^\[memories\]", content)
        if m_mem:
            return content[:m_mem.start()] + block + "\n\n" + content[m_mem.start():]
        return content.rstrip() + "\n\n" + block + "\n"


def sync_string_block(content: str, key: str, inject_content: str) -> str | None:
    """Sync a multi-line string block (key = \"\"\"...\"\"\"). Returns new content or None."""
    # Extract from inject
    inject_pattern = rf'(?m)^{re.escape(key)}\s*=\s*"""\s*\n(.*?)\n\s*"""'
    inj_m = re.search(inject_pattern, inject_content, re.DOTALL)
    if not inj_m:
        return None  # Not in inject, skip
    inject_val = inj_m.group(1).rstrip()

    # Extract from content
    cur_m = re.search(inject_pattern, content, re.DOTALL)
    if not cur_m:
        print(f"  {key:30s} MISSING  -> inserting")
        # Insert after personality/approval_policy line
        anchor = re.search(r"(?m)^(?:personality|approval_policy)\s*=\s*.+$", content)
        if anchor:
            pos = anchor.end()
            block = f'\n\n{key} = """\n{inject_val}\n"""'
            return content[:pos] + block + content[pos:]
        return f'{key} = """\n{inject_val}\n"""\n\n{content}'

    cur_val = cur_m.group(1).rstrip()
    if cur_val != inject_val:
        print(f"  {key:30s} DIFFERS  -> replacing")
        repl = f'{key} = """\n{inject_val}\n"""'
        pattern = rf'(?m)^{re.escape(key)}\s*=\s*""".*?"""'
        return re.sub(pattern, repl, content, count=1, flags=re.DOTALL)

    print(f"  {key:30s} MATCH    (no change)")
    return None


def merge_config(target: Path, bk_root: Path, dry_run: bool = False) -> None:
    config_toml = target / "config.toml"
    if not config_toml.exists():
        print("  Config not found. Creating from inject...")
        if not dry_run:
            write_text(config_toml, INJECT_FILE.read_text(encoding="utf-8"))
        print("  Config written.")
        return

    content = config_toml.read_text(encoding="utf-8")
    inject = INJECT_FILE.read_text(encoding="utf-8")
    original = content
    changed = False

    # 2a: [agents] section — full replace
    inject_agents = extract_agents_block(inject)
    cur_agents = extract_agents_block(content)
    if inject_agents and cur_agents != inject_agents:
        print(f"  {'[agents]':30s} DIFFERS  -> replacing")
        content = replace_agents_section(content, inject_agents)
        changed = True
    else:
        print(f"  {'[agents]':30s} MATCH    (no change)")

    # 2b: instructions
    for key in ("instructions",):
        result = sync_string_block(content, key, inject)
        if result is not None:
            content = result
            changed = True

    # 2c: top-level key-value pairs (only sync if key exists in inject)
    kv_keys = ["model", "model_reasoning_effort", "model_context_window",
               "model_auto_compact_token_limit"]
    for key in kv_keys:
        inj_m = re.search(rf'(?m)^{re.escape(key)}\s*=\s*(.+)$', inject)
        if not inj_m:
            continue  # not managed by inject
        inject_val = inj_m.group(1).strip()
        cur_m = re.search(rf'(?m)^{re.escape(key)}\s*=\s*(.+)$', content)
        if not cur_m:
            print(f"  {key:30s} MISSING  -> inserting")
            content = f"{key} = {inject_val}\n{content}"
            changed = True
        elif cur_m.group(1).strip() != inject_val:
            print(f"  {key:30s} DIFFERS  -> replacing ({cur_m.group(1).strip()} -> {inject_val})")
            content = content.replace(cur_m.group(0), f"{key} = {inject_val}", 1)
            changed = True
        else:
            print(f"  {key:30s} MATCH    (no change)")

    if changed:
        if not dry_run:
            # Backup
            config_backup = bk_root / "config.toml"
            config_backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(config_toml, config_backup)
            print(f"  Backed up to: {config_backup}")
            # Write
            config_toml.write_text(content, encoding="utf-8")
            print("  Config written.")
        else:
            print("  (dry-run: would write config)")
    else:
        print("  All settings match. No changes needed.")


# ── Step 3: Check MCP duplication ─────────────────────────────────

def check_mcp_duplication(target: Path) -> None:
    librarian = target / "agents" / "librarian.toml"
    if not librarian.exists():
        return
    lib_content = librarian.read_text(encoding="utf-8")
    lib_mcps = re.findall(r"(?m)^\[mcp_servers\.(\w+)\]", lib_content)

    config_toml = target / "config.toml"
    if not config_toml.exists():
        return
    cfg_content = config_toml.read_text(encoding="utf-8")

    dup = [m for m in lib_mcps if re.search(rf"(?m)^\[mcp_servers\.{re.escape(m)}\]", cfg_content)]
    if dup:
        print("  NOTE: These MCP servers are in BOTH global config and librarian:")
        for d in dup:
            print(f"    - {d}")
        print("  Since librarian has its own [mcp_servers], you can remove them")
        print("  from config.toml to avoid duplication.")
        print("  (This script will NOT modify global MCP servers automatically.)")
    else:
        print("  OK: No duplicate MCP servers between global and librarian.")


# ── Backup cleanup ────────────────────────────────────────────────

def remove_backup_if_empty(bk_root: Path) -> None:
    """Remove the backup directory tree if it's completely empty (no changes made)."""
    if not bk_root.exists():
        return
    # Check if any files exist
    any_files = any(p.is_file() for p in bk_root.rglob("*"))
    if not any_files:
        shutil.rmtree(bk_root)
        # Also clean parent .backup dir if empty
        parent = bk_root.parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()


# ── Main ──────────────────────────────────────────────────────────

def main():
    dry_run = "--dry-run" in sys.argv
    scope = "global"
    project_dir = ""

    for arg in sys.argv[1:]:
        if arg == "--dry-run":
            continue
        if arg == "--project":
            scope = "project"
        if arg.startswith("--project-dir="):
            scope = "project"
            project_dir = arg.split("=", 1)[1]

    target = target_dir(scope, project_dir)
    bk_root = backup_root(target)

    print("=" * 50)
    print(" Codex Orchestrator Installer")
    print("=" * 50)
    print(f"Source : {SOURCE}")
    print(f"Target : {target / 'agents'}")
    print(f"Scope  : {scope}")
    if dry_run:
        print("Mode   : DRY RUN")
    print()

    # Phase 1: Full backup before any writes
    changed_anything = False

    print("[1/3] Installing specialist agents...")
    print()
    install_agents(target, bk_root, dry_run)
    print()

    print("[2/3] Checking config.toml merge status...")
    print()
    merge_config(target, bk_root, dry_run)
    print()

    print("[3/3] Checking MCP server placement...")
    print()
    check_mcp_duplication(target)
    print()

    # Cleanup: remove backup if nothing was changed
    remove_backup_if_empty(bk_root)

    print("=" * 50)
    print(" Installation Complete")
    print("=" * 50)
    print()
    print("Registered specialist agents:")
    for f in sorted(AGENT_SRC.glob("*.toml")):
        print(f"  {f.stem}")
    print()
    print("Default session IS the Orchestrator. Start coding:")
    print("  codex")


if __name__ == "__main__":
    main()
