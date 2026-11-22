import json
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from PIL import Image, ImageOps

WIDTHS = [480, 800, 1200, 1600]
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
BAD_NAME = re.compile(r"^(img|image|dsc|pic|photo)[-_ ]?\d*$", re.I)
STATIC_PREFIX = "img/optimized"


class Command(BaseCommand):
    help = "Resize photos in image_sources/ into WebP files and write manifest.json."

    def add_arguments(self, parser):
        parser.add_argument("--source", default=str(settings.IMAGE_SOURCE_DIR))
        parser.add_argument("--output", default=str(settings.OPTIMIZED_IMAGE_DIR))
        parser.add_argument("--quality", type=int, default=80)

    def handle(self, *args, **options):
        source, output = Path(options["source"]), Path(options["output"])
        if not source.is_dir():
            raise CommandError(f"Source folder not found: {source}")

        names = {}
        for path in sorted(source.iterdir()):
            if path.suffix.lower() not in EXTENSIONS:
                continue
            name = re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")
            if not name or BAD_NAME.match(name):
                raise CommandError(
                    f"Rename '{path.name}' to something descriptive, "
                    "such as 'kauswagan-river-sensor.jpg'."
                )
            if name in names:
                raise CommandError(f"Two files produce the same name '{name}'.")
            names[name] = path
        if not names:
            raise CommandError(f"No .jpg, .png or .webp files found in {source}")

        output.mkdir(parents=True, exist_ok=True)
        for old in list(output.glob("*.webp")) + list(output.glob("manifest.json")):
            old.unlink()

        manifest, size_in, size_out = {}, 0, 0
        for name, path in names.items():
            size_in += path.stat().st_size
            with Image.open(path) as opened:
                image = ImageOps.exif_transpose(opened)
                mode = "RGBA" if "A" in image.getbands() else "RGB"
                image = image.convert(mode)
                width, height = image.size
                variants = []
                for target in [w for w in WIDTHS if w <= width] or [width]:
                    new_height = round(height * target / width)
                    resized = image if target == width else image.resize(
                        (target, new_height), Image.Resampling.LANCZOS
                    )
                    filename = f"{name}-{target}.webp"
                    resized.save(output / filename, "WEBP", quality=options["quality"], method=6)
                    size_out += (output / filename).stat().st_size
                    variants.append(
                        {"width": target, "height": new_height, "file": f"{STATIC_PREFIX}/{filename}"}
                    )
            manifest[name] = {"variants": variants}
            self.stdout.write(f"{name}: {', '.join(str(v['width']) for v in variants)} px")

        (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(
            f"Done. {len(manifest)} image(s), {size_in // 1024} KB in, {size_out // 1024} KB out."
        ))