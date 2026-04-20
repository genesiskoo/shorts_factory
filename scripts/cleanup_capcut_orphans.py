"""CapCut 시스템 경로의 고아 프로젝트 폴더 + root_meta_info 항목 정리.

사용법 (Git Bash / cmd / PowerShell):
    python scripts/cleanup_capcut_orphans.py             # dry-run (기본)
    python scripts/cleanup_capcut_orphans.py --apply     # 실제 삭제

정리 대상:
1. 고정 화이트리스트 이름의 폴더 (v1_informative, v2_empathy, 샥즈 오픈닷 원 E310 오픈형,
   test_capcut_builder 등) — 사용자 현 환경 기준
2. root_meta_info.json 에서 해당 draft_name 엔트리 제거

안전 가드:
- CapCut 프로세스가 실행 중이면 경고 + 중단 (root_meta_info 파일 잠금 위험)
- root_meta_info.json 백업을 .bak 으로 보존
- dry-run이 기본. --apply 명시해야 실제 수정
- 보존 화이트리스트: 샤오미모니터등(참조용 정상 프로젝트) + 날짜 기반 (0322-copy-*, 0330, 0407, 0812)는 건드리지 않음
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

CAPCUT_PROJECTS = Path.home() / "AppData/Local/CapCut/User Data/Projects/com.lveditor.draft"
ROOT_META = CAPCUT_PROJECTS / "root_meta_info.json"

# shorts_factory가 만든 고아로 판정되는 폴더명 (정확 매칭)
ORPHAN_NAMES = {
    "v1_informative",
    "v2_empathy",
    "v3_scenario",
    "v4_review",
    "v5_comparison",
    "test_capcut_builder",
    # product_name 기반 폴더 (Web UI 시험 중 잘못 만들어진 mirror)
    "샥즈 오픈닷 원 E310 오픈형",
    "샥즈 오픈닷 원 E310",
    "엔커사운드코어",
}


def _capcut_running() -> bool:
    """tasklist로 CapCut.exe 프로세스 존재 확인."""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq CapCut.exe"],
            capture_output=True, text=True, timeout=5,
        )
        return "CapCut.exe" in out.stdout
    except Exception:
        return False


def _load_root_meta() -> dict:
    return json.loads(ROOT_META.read_text(encoding="utf-8"))


def _save_root_meta(data: dict) -> None:
    ROOT_META.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제 삭제 실행")
    args = ap.parse_args()

    if not CAPCUT_PROJECTS.exists():
        print(f"[SKIP] CapCut projects dir not found: {CAPCUT_PROJECTS}")
        return 0

    print(f"CapCut projects dir: {CAPCUT_PROJECTS}")
    print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN (pass --apply to delete)'}")
    print()

    if args.apply and _capcut_running():
        print("[ERROR] CapCut.exe가 실행 중입니다. 종료 후 다시 시도하세요.")
        return 2

    # 1. 고아 폴더 스캔
    folders_to_remove: list[Path] = []
    for child in CAPCUT_PROJECTS.iterdir():
        if not child.is_dir():
            continue
        if child.name in ORPHAN_NAMES:
            folders_to_remove.append(child)

    print(f"[scan] orphan folders: {len(folders_to_remove)}")
    for f in folders_to_remove:
        size = sum(p.stat().st_size for p in f.rglob("*") if p.is_file())
        print(f"  - {f.name}  ({size // 1024} KB)")

    # 2. root_meta_info 엔트리 스캔
    meta = _load_root_meta() if ROOT_META.exists() else {"all_draft_store": []}
    store = meta.get("all_draft_store", [])
    entries_to_remove = [
        it for it in store
        if it.get("draft_name", "") in ORPHAN_NAMES
    ]
    print(f"[scan] root_meta_info entries: {len(entries_to_remove)}")
    for it in entries_to_remove:
        print(f"  - {it.get('draft_name')}  (draft_id={it.get('draft_id')})")

    if not folders_to_remove and not entries_to_remove:
        print("\n[DONE] nothing to clean.")
        return 0

    if not args.apply:
        print("\n[DRY-RUN] --apply 없이는 삭제하지 않습니다.")
        return 0

    # 3. 실제 삭제 — 백업 먼저
    if ROOT_META.exists():
        bak = ROOT_META.with_suffix(".json.bak")
        shutil.copy2(ROOT_META, bak)
        print(f"\n[backup] {bak}")

    # 4. 폴더 삭제
    removed_folders = 0
    for f in folders_to_remove:
        try:
            shutil.rmtree(f)
            removed_folders += 1
            print(f"[rm] {f.name}")
        except Exception as e:
            print(f"[FAIL rm] {f.name}: {e}")

    # 5. root_meta_info 갱신
    kept = [
        it for it in store
        if it.get("draft_name", "") not in ORPHAN_NAMES
    ]
    meta["all_draft_store"] = kept
    _save_root_meta(meta)
    print(f"[root_meta] removed {len(entries_to_remove)} entries, kept {len(kept)}")

    print(f"\n[DONE] folders removed: {removed_folders} / entries removed: {len(entries_to_remove)}")
    print("CapCut 재시작 후 프로젝트 목록에서 고아 항목이 사라진 것을 확인하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
