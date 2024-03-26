import subprocess
import sys
from zipfile import ZipFile, BadZipFile
from pathlib import Path

def system_unzip_rezip(wheel_path: Path, extract_dir: Path):
    """
    Use system utilities to unzip and re-zip a .whl file.

    """
    # Unzip using system call
    subprocess.run(["unzip", "-o", str(wheel_path), "-d", str(extract_dir)], check=True)

    # Re-zip using system call
    subprocess.run(["zip", "-r", str(wheel_path.with_suffix(".zip")), "."], cwd=extract_dir, check=True)
    (wheel_path.with_suffix(".zip")).rename(wheel_path)

    # Remove the hanging directory
    subprocess.run(["rm", "-rf", str(extract_dir)], check=True)

def try_unzip_wheel(wheel_path: Path):
    """
    Attempt to unzip a wheel file, falling back to system utilities on failure.
    """
    try:
        # If we can read the file in python from the get-go, there's no need
        # to fix it
        print("Found wheel, attempting to fix:", wheel_path)
        with ZipFile(wheel_path, 'r') as zip_ref:
            zip_ref.extractall(wheel_path.parent / wheel_path.stem)
        print("Wheel is already valid.")
        raise BadZipFile
    except BadZipFile:
        print(f"BadZipFile caught for {wheel_path}, using system utilities to recreate.")
        extract_dir = wheel_path.parent / wheel_path.stem
        extract_dir.mkdir(exist_ok=True)
        system_unzip_rezip(wheel_path, extract_dir)

        # Verify fix
        try:
            with ZipFile(wheel_path, 'r') as zip_ref:
                print(f"Successfully fixed and verified {wheel_path}.")
        except BadZipFile:
            raise ValueError(f"Failed to fix the wheel file {wheel_path} after using system utilities.")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python fix_mac_wheels.py <dist>")
        sys.exit(1)
    dist_path = Path(sys.argv[1]).expanduser().resolve()
    print(f"Fixing wheels in {dist_path}")
    for wheel_path in dist_path.glob("*.whl"):
        try_unzip_wheel(wheel_path)
    print("Done with wheel fixes.")
