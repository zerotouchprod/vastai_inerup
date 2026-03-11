"""
Патч pipeline_cogvideox_image2video.py для diffusers==0.31.0

Проблема: строка 733
    latent_channels = self.transformer.config.in_channels // 2
    → 16 // 2 = 8  (неверно для старого checkpoint где in_channels=16)

Правильно: latent_channels берётся из VAE config
    self.vae.config.latent_channels = 16

Запустить: python3 /app/docker/patches/patch_cogvideox_031.py
"""
import pathlib
import sys


def show_context(lines: list[str], idx: int, radius: int = 5) -> None:
    start = max(0, idx - radius)
    end = min(len(lines), idx + radius + 1)
    for i in range(start, end):
        marker = ">>>" if i == idx else "   "
        print(f"{marker} {i+1:4}: {lines[i]}")


def main() -> None:
    f = pathlib.Path(
        "/usr/local/lib/python3.11/dist-packages/diffusers/pipelines/cogvideo/pipeline_cogvideox_image2video.py"
    )
    if not f.exists():
        print(f"❌ File not found: {f}")
        sys.exit(1)

    import diffusers
    print(f"diffusers: {diffusers.__version__}")

    lines = f.read_text().splitlines()

    # Найти строку с latent_channels = self.transformer.config.in_channels // 2
    target_indices = [
        i for i, l in enumerate(lines)
        if "latent_channels" in l and "in_channels" in l and "//" in l
    ]

    if not target_indices:
        print("❌ Target line not found. All 'latent_channels' lines:")
        for i, l in enumerate(lines):
            if "latent_channels" in l:
                print(f"  {i+1}: {repr(l)}")
        sys.exit(0)

    print(f"Found {len(target_indices)} target line(s):")
    patched = False

    for idx in target_indices:
        line = lines[idx]
        print(f"  {idx+1}: {line}")

        if "PATCH" in line:
            print(f"  ↳ already patched, skipping")
            continue

        indent = len(line) - len(line.lstrip())
        pad = " " * indent

        lines[idx:idx + 1] = [
            f"{pad}# PATCH patch_cogvideox_031.py: vae.config.latent_channels instead of in_channels//2",
            f"{pad}# Old checkpoint: transformer.in_channels=16, vae.latent_channels=16 → //2 gives 8 (wrong)",
            f"{pad}latent_channels = self.vae.config.latent_channels",
        ]
        patched = True
        print(f"  ↳ patched!")

    if patched:
        f.write_text("\n".join(lines) + "\n")
        print(f"✅ Written to {f}")
    else:
        print("ℹ️  Nothing to patch")


if __name__ == "__main__":
    main()

