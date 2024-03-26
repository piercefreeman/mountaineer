"""
Update the version for the regular Mountaineer rust project.

"""
import sys
import re
from packaging.version import parse

def update_version(new_version: str):
    with open('Cargo.toml', 'r') as file:
        filedata = file.read()

    # If the new version is a pre-release version, we need to reformat it
    # to align with Cargo standards
    # pip format uses "0.1.0.dev1" while Cargo uses "0.1.0-dev1"
    parsed_version = parse(new_version)

    cargo_version = f"{parsed_version.major}.{parsed_version.minor}.{parsed_version.micro}"
    if parsed_version.is_prerelease and parsed_version.pre is not None:
        pre_release = '.'.join(str(x) for x in parsed_version.pre)
        cargo_version += f"-{pre_release.replace('.', '')}"
    if parsed_version.is_postrelease and parsed_version.post is not None:
        cargo_version += f"-post{parsed_version.post}"
    if parsed_version.is_devrelease and parsed_version.dev is not None:
        cargo_version += f"-dev{parsed_version.dev}"

    # Update the version in the file
    filedata = re.sub(r'^version = ".*"$', f'version = "{cargo_version}"', filedata, flags=re.MULTILINE)

    with open('Cargo.toml', 'w') as file:
        file.write(filedata)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python update_version.py <new_version>")
        sys.exit(1)
    new_version = sys.argv[1].lstrip("v")
    update_version(new_version)
    print(f"Updated version to: {new_version}")
