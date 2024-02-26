import re
import sys

def update_version(new_version):
    with open('Cargo.toml', 'r') as file:
        filedata = file.read()

    # Update the version in the file
    filedata = re.sub(r'^version = ".*"$', f'version = "{new_version}"', filedata, flags=re.MULTILINE)

    with open('Cargo.toml', 'w') as file:
        file.write(filedata)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python update_version.py <new_version>")
        sys.exit(1)
    new_version = sys.argv[1].lstrip("v")
    update_version(new_version)
    print(f"Updated version to: {new_version}")
