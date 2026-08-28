#!/usr/bin/env python3
"""
Cleanup Agent - removes old renders and output directories.

Usage:
    python3 cleanup.py                    # Clean output older than 7 days
    python3 cleanup.py --days 3           # Clean output older than 3 days
    python3 cleanup.py --dry-run          # Show what would be deleted
"""

import argparse
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
RENDERS_DIR = PROJECT_ROOT / "producer" / "renders"
CACHE_DIR = PROJECT_ROOT / "producer" / "node_modules" / ".cache"


def cleanup_output(days: int, dry_run: bool) -> list[str]:
    removed = []
    if not OUTPUT_DIR.exists():
        return removed

    cutoff = datetime.now() - timedelta(days=days)
    for run_dir in sorted(OUTPUT_DIR.iterdir()):
        if not run_dir.is_dir():
            continue
        # Parse run_id timestamp: YYYYMMDD_HHMMSS or YYYYMMDD_HHMMSS_xxxx
        # (the latter includes a uniqueness suffix). Legacy "agent-*" dirs and
        # anything else are left untouched.
        ts = run_dir.name
        if ts.startswith("agent-"):
            continue
        dir_time = None
        try:
            dir_time = datetime.strptime(ts[:15], "%Y%m%d_%H%M%S")
        except ValueError:
            continue
        if dir_time < cutoff:
            size = sum(f.stat().st_size for f in run_dir.rglob("*") if f.is_file())
            size_mb = size / 1024 / 1024
            if dry_run:
                print(f"  [dry-run] Would delete: {run_dir.name} ({size_mb:.1f} MB)")
            else:
                shutil.rmtree(run_dir)
                print(f"  Deleted: {run_dir.name} ({size_mb:.1f} MB)")
            removed.append(run_dir.name)
    return removed


def cleanup_renders(dry_run: bool) -> int:
    count = 0
    if not RENDERS_DIR.exists():
        return count
    for render_dir in RENDERS_DIR.iterdir():
        if not render_dir.is_dir():
            continue
        size = sum(f.stat().st_size for f in render_dir.rglob("*") if f.is_file())
        size_mb = size / 1024 / 1024
        if dry_run:
            print(f"  [dry-run] Would delete render: {render_dir.name} ({size_mb:.1f} MB)")
        else:
            shutil.rmtree(render_dir)
            print(f"  Deleted render: {render_dir.name} ({size_mb:.1f} MB)")
        count += 1
    return count


def cleanup_cache(dry_run: bool) -> bool:
    if not CACHE_DIR.exists():
        return False
    size = sum(f.stat().st_size for f in CACHE_DIR.rglob("*") if f.is_file())
    size_mb = size / 1024 / 1024
    if dry_run:
        print(f"  [dry-run] Would delete cache: {size_mb:.1f} MB")
    else:
        shutil.rmtree(CACHE_DIR)
        print(f"  Deleted cache: {size_mb:.1f} MB")
    return True


def main():
    parser = argparse.ArgumentParser(description="Cleanup old output and cache")
    parser.add_argument("--days", type=int, default=7, help="Delete output older than N days")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted")
    args = parser.parse_args()

    mode = "[DRY RUN] " if args.dry_run else ""
    print(f"{mode}Cleaning output older than {args.days} days...")
    removed_output = cleanup_output(args.days, args.dry_run)
    print(f"  Removed {len(removed_output)} output directories")

    print(f"\n{mode}Cleaning old renders...")
    removed_renders = cleanup_renders(args.dry_run)
    print(f"  Removed {removed_renders} render directories")

    print(f"\n{mode}Cleaning webpack cache...")
    cleanup_cache(args.dry_run)

    print("\nDone.")


if __name__ == "__main__":
    main()
