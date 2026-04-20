"""PROJECT_ROOT/.env가 backend config import 시점에 os.environ에 실리는지 검증.

이 테스트는 서브프로세스에서 `import config`만 실행해 .env 로드가
side-effect로 일어나는지(Typecast/ElevenLabs 키가 환경변수에 떠 있는지)
확인한다. 다른 테스트가 환경을 오염시켜도 독립 검증되도록 subprocess 사용.

실행:
    cd web/backend && venv_web/Scripts/python.exe tests/test_env_loading.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND.parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

results: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name}  {detail}")


print("\n[test 1] .env 파일 존재")
check("env 파일 존재", ENV_FILE.exists(), f"path={ENV_FILE}")


print("\n[test 2] .env에 TYPECAST_API_KEY 엔트리")
env_text = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
has_tc = "TYPECAST_API_KEY" in env_text
check("TYPECAST_API_KEY 선언됨", has_tc)


print("\n[test 3] 서브프로세스에서 config import만 해도 env 실림")
# 깨끗한 env (TYPECAST_API_KEY 제거)로 시작해 config import가 채우는지 확인
clean_env = {k: v for k, v in os.environ.items() if not k.startswith("TYPECAST")}
clean_env.pop("TYPECAST_API_KEY", None)
code = (
    "import sys, os; "
    f"sys.path.insert(0, r'{BACKEND}'); "
    "import config; "
    "print('TYPECAST=' + (os.environ.get('TYPECAST_API_KEY','') or 'EMPTY')); "
    "print('ELEVEN=' + (os.environ.get('ELEVENLABS_API_KEY','') or 'EMPTY'))"
)
res = subprocess.run(
    [sys.executable, "-c", code],
    capture_output=True,
    text=True,
    env=clean_env,
    check=False,
)
stdout = res.stdout
stderr = res.stderr
check("subprocess 종료 코드 0", res.returncode == 0, f"stderr={stderr[:200]}")

tc_line = next(
    (l for l in stdout.splitlines() if l.startswith("TYPECAST=")), ""
)
tc_val = tc_line.replace("TYPECAST=", "", 1)
check(
    "TYPECAST_API_KEY 주입됨",
    tc_val != "EMPTY" and len(tc_val) > 10,
    f"value_preview={tc_val[:12]}..." if tc_val and tc_val != "EMPTY" else f"val={tc_val!r}",
)

eleven_line = next(
    (l for l in stdout.splitlines() if l.startswith("ELEVEN=")), ""
)
eleven_val = eleven_line.replace("ELEVEN=", "", 1)
check(
    "ELEVENLABS_API_KEY 주입됨 (회귀)",
    eleven_val != "EMPTY",
    f"value_preview={eleven_val[:8]}..." if eleven_val and eleven_val != "EMPTY" else f"val={eleven_val!r}",
)


print("\n[test 4] 기존 os.environ 값이 있으면 덮어쓰지 않음")
# .env와 다른 값으로 미리 세팅 → .env 로드 후에도 원래 값이 유지되는지
override_env = clean_env.copy()
override_env["TYPECAST_API_KEY"] = "USER_OVERRIDE_VALUE"
res2 = subprocess.run(
    [sys.executable, "-c", code],
    capture_output=True,
    text=True,
    env=override_env,
    check=False,
)
tc_line2 = next(
    (l for l in res2.stdout.splitlines() if l.startswith("TYPECAST=")), ""
)
tc_val2 = tc_line2.replace("TYPECAST=", "", 1)
check(
    "기존 env 우선 (덮어쓰기 안 함)",
    tc_val2 == "USER_OVERRIDE_VALUE",
    f"got={tc_val2!r}",
)


print("\n" + "=" * 60)
total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
print(f"TOTAL: {passed}/{total} PASS")
if passed != total:
    for name, ok, detail in results:
        if not ok:
            print(f"  FAIL  {name}  {detail}")
    sys.exit(1)
