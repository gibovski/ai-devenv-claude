"""Write an SPDX 2.3 JSON SBOM from a dpkg package list (name<TAB>version<TAB>arch) and docker images.

Usage: python3 sbom.py packages.tsv images.txt out.spdx.json <image-name>
"""

import json
import sys
import uuid
from datetime import UTC, datetime


def main() -> None:
    pkgs_path, images_path, out, name = sys.argv[1:5]
    packages = []
    for line in open(pkgs_path):
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 3:
            continue
        pkg, ver, arch = parts[:3]
        packages.append(
            {
                "SPDXID": f"SPDXRef-deb-{len(packages)}",
                "name": pkg,
                "versionInfo": ver,
                "downloadLocation": "NOASSERTION",
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": f"pkg:deb/ubuntu/{pkg}@{ver}?arch={arch}",
                    }
                ],
            }
        )
    for line in open(images_path):
        ref = line.strip()
        if not ref:
            continue
        packages.append(
            {
                "SPDXID": f"SPDXRef-oci-{len(packages)}",
                "name": ref,
                "downloadLocation": "NOASSERTION",
                "primaryPackagePurpose": "CONTAINER",
            }
        )
    doc = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": name,
        "documentNamespace": f"https://github.com/gibovski/ai-devenv-claude/sbom/{name}-{uuid.uuid4()}",
        "creationInfo": {"created": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "creators": ["Tool: sbom.py"]},
        "packages": packages,
    }
    json.dump(doc, open(out, "w"), indent=1)
    print(f"{out}: {len(packages)} packages")


if __name__ == "__main__":
    main()
