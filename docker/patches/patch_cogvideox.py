"""
Патч pipeline_cogvideox_image2video.py — фикс size mismatch в prepare_latents.
"""
import pathlib
import sys


def main() -> None:
    try:
        import diffusers
        pipeline_file = pathlib.Path(diffusers.__file__).parent / \
            "pipelines/cogvideo/pipeline_cogvideox_image2video.py"

        if not pipeline_file.exists():
            print(f"⚠️  File not found: {pipeline_file}")
            sys.exit(0)

        src = pipeline_file.read_text()
        lines = src.splitlines()

        # Найти строку с torch.cat для image_latents
        target_indices = [
            i for i, line in enumerate(lines)
            if "torch.cat" in line and "image_latents" in line and "latent_padding" in line
        ]

        if not target_indices:
            print("ℹ️  torch.cat pattern not found — patch not needed or different version")
            print("Searching for 'latent_padding' occurrences:")
            for i, line in enumerate(lines):
                if "latent_padding" in line:
                    print(f"  line {i+1}: {repr(line)}")
            sys.exit(0)

        print(f"Found {len(target_indices)} torch.cat target(s)")

        patched = False
        for idx in target_indices:
            original_line = lines[idx]
            indent = len(original_line) - len(original_line.lstrip())
            pad = " " * indent

            # Печатаем контекст для диагностики
            print(f"  line {idx+1}: {repr(original_line)}")

            # Проверяем — не запатчено ли уже
            if "PATCH" in lines[max(0, idx - 1)]:
                print(f"  ↳ already patched, skipping")
                continue

            replacement = [
                f"{pad}# PATCH patch_cogvideox.py: align spatial dims before cat",
                f"{pad}if image_latents.shape[2:] != latent_padding.shape[2:]:",
                f"{pad}    import torch.nn.functional as _F",
                f"{pad}    _b, _t = latent_padding.shape[:2]",
                f"{pad}    latent_padding = _F.interpolate(",
                f"{pad}        latent_padding.reshape(_b * _t, *latent_padding.shape[2:]).unsqueeze(0),",
                f"{pad}        size=image_latents.shape[2:],",
                f"{pad}        mode='nearest',",
                f"{pad}    ).squeeze(0).reshape(_b, _t, *image_latents.shape[2:])",
                original_line,  # оригинальная строка torch.cat остаётся
            ]

            lines[idx:idx + 1] = replacement
            patched = True
            print(f"  ↳ patched!")

        if patched:
            pipeline_file.write_text("\n".join(lines) + "\n")
            print(f"✅ Patch written to {pipeline_file}")
        else:
            print("ℹ️  Nothing to patch")

    except Exception as e:
        print(f"⚠️  Patch failed (non-fatal): {e}")
        import traceback
        traceback.print_exc()
        sys.exit(0)


if __name__ == "__main__":
    main()

