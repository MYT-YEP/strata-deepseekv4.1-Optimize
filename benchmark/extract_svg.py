"""Extract an unedited SVG from a recorded Pelican answer and check its safety."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

SVG_NS = "http://www.w3.org/2000/svg"
FORBIDDEN_TAGS = {"script", "foreignObject", "image", "iframe", "object", "embed", "audio", "video"}


def local_name(name):
    return name.rsplit("}", 1)[-1]


def extract(answer):
    match = re.search(r"<svg\b[\s\S]*?</svg\s*>", answer, flags=re.IGNORECASE)
    if not match:
        raise ValueError("The answer does not contain a complete SVG element.")
    value = match.group(0)
    if len(value.encode("utf-8")) > 1024 * 1024:
        raise ValueError("SVG exceeds the 1 MiB inspection limit.")
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", value, flags=re.IGNORECASE):
        raise ValueError("SVG contains a DTD or entity declaration.")
    if re.search(r"@import|javascript\s*:|expression\s*\(", value, flags=re.IGNORECASE):
        raise ValueError("SVG contains an unsupported active or external reference.")
    for match in re.finditer(r"url\s*\(\s*['\"]?([^\s)'\"]+)", value, flags=re.IGNORECASE):
        if not match.group(1).startswith("#"):
            raise ValueError("SVG contains a non-local CSS URL.")
    root = ET.fromstring(value)
    if root.tag != "{" + SVG_NS + "}svg":
        raise ValueError("Root is not an SVG in the expected namespace.")
    for node in root.iter():
        if local_name(node.tag).lower() in {x.lower() for x in FORBIDDEN_TAGS}:
            raise ValueError("Forbidden SVG element: " + local_name(node.tag))
        for key, item in node.attrib.items():
            key = local_name(key).lower()
            if key.startswith("on"):
                raise ValueError("SVG contains an event-handler attribute.")
            if key == "href" and not item.startswith("#"):
                raise ValueError("SVG contains an external reference.")
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("result_json", type=Path)
    parser.add_argument("svg_output", type=Path)
    args = parser.parse_args()
    result = json.loads(args.result_json.read_text(encoding="utf-8-sig"))
    svg = extract(result["answer"])
    data = svg.encode("utf-8")
    with args.svg_output.open("xb") as handle:
        handle.write(data)
    print(json.dumps({"svg": str(args.svg_output), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                      "xml_valid": True, "external_and_active_content": "not detected", "edited": False}))


if __name__ == "__main__": main()
