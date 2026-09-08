"""Stage the existing packaged UI assets for Vercel static delivery."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "deterministic_scheduling_core" / "native_planning_ui"
OUTPUT = ROOT / "public"
ASSETS = ("index.html", "app.js", "styles.css")


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    for name in ASSETS:
        shutil.copyfile(SOURCE / name, OUTPUT / name)
    print(f"Staged {len(ASSETS)} native-planning UI assets in {OUTPUT}")


if __name__ == "__main__":
    main()
