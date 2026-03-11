"""
Патч pipeline_cogvideox_image2video.py для diffusers==0.31.0 + CogVideoX-5b-I2V (in_channels=32)

Фикс 1: latent_channels = in_channels // 2  →  vae.config.latent_channels
  Строка ~733: 32//2=16 ✅ для новой модели, но патч безопасен

Фикс 2: torch.cat temporal mismatch в prepare_latents
  Строка ~390: image_latents[1] != latent_padding[1]

Фикс 3: torch.cat channel mismatch в __call__
  Строка ~782: latent_model_input(13ch) vs latent_image_input(24ch=16+8)
  Причина: latent_image_input конкатенируется неправильно для старого checkpoint
  Фикс: обрезать latent_image_input до num_channels_latents каналов

Запустить: python3 /tmp/patch_cogvideox_all.py
"""
import pathlib
import sys


def main() -> None:
    f = pathlib.Path(
        "/usr/local/lib/python3.11/dist-packages/diffusers/pipelines/cogvideo/pipeline_cogvideox_image2video.py"
    )
    if not f.exists():
        print(f"❌ File not found: {f}")
        sys.exit(1)

    import diffusers
    print(f"diffusers version: {diffusers.__version__}")

    lines = f.read_text().splitlines()
    patched_count = 0

    # ── Фикс 3 (главный): dim=2 channel mismatch в __call__ ──────────────────
    # torch.cat([latent_model_input, latent_image_input], dim=2)
    # latent_image_input имеет 24 каналов (16 image + 8 padding), нужно 13
    # Фикс: обрезать latent_image_input[:, :, :latent_model_input.shape[2]]
    for i, l in enumerate(lines):
        if (
            "torch.cat" in l
            and "latent_model_input" in l
            and "latent_image_input" in l
            and "dim=2" in l
            and "PATCH" not in lines[max(0, i - 1)]
        ):
            print(f"[Fix 3] Line {i+1}: {l.strip()}")
            pad = " " * (len(l) - len(l.lstrip()))
            lines[i:i + 1] = [
                f"{pad}# PATCH Fix3: align channel dim — latent_image_input may have extra channels",
                f"{pad}if latent_image_input.shape[2] != latent_model_input.shape[2]:",
                f"{pad}    latent_image_input = latent_image_input[:, :, :latent_model_input.shape[2]]",
                l,
            ]
            patched_count += 1
            print(f"  ✅ patched")
            break

    # ── Фикс 2: temporal mismatch в prepare_latents ───────────────────────────
    for i, l in enumerate(lines):
        if (
            "torch.cat" in l
            and "image_latents" in l
            and "latent_padding" in l
            and "dim=1" in l
            and "PATCH" not in lines[max(0, i - 1)]
        ):
            print(f"[Fix 2] Line {i+1}: {l.strip()}")
            pad = " " * (len(l) - len(l.lstrip()))
            lines[i:i + 1] = [
                f"{pad}# PATCH Fix2: align temporal dim before cat",
                f"{pad}if image_latents.shape[1] != latent_padding.shape[1]:",
                f"{pad}    _d = latent_padding.shape[1] - image_latents.shape[1]",
                f"{pad}    if _d > 0:",
                f"{pad}        import torch as _t",
                f"{pad}        image_latents = _t.cat([image_latents, _t.zeros(",
                f"{pad}            image_latents.shape[0], _d, *image_latents.shape[2:],",
                f"{pad}            device=image_latents.device, dtype=image_latents.dtype)], dim=1)",
                l,
            ]
            patched_count += 1
            print(f"  ✅ patched")
            break

    # ── Фикс 1: latent_channels ───────────────────────────────────────────────
    for i, l in enumerate(lines):
        if (
            "latent_channels" in l
            and "in_channels" in l
            and "//" in l
            and "PATCH" not in l
        ):
            print(f"[Fix 1] Line {i+1}: {l.strip()}")
            pad = " " * (len(l) - len(l.lstrip()))
            lines[i:i + 1] = [
                f"{pad}# PATCH Fix1: use vae.config.latent_channels instead of in_channels//2",
                f"{pad}latent_channels = self.vae.config.latent_channels",
            ]
            patched_count += 1
            print(f"  ✅ patched")
            break

    if patched_count > 0:
        f.write_text("\n".join(lines) + "\n")
        print(f"\n✅ Applied {patched_count} patch(es) to {f}")
    else:
        print("\nℹ️  Nothing patched — checking relevant lines:")
        for i, l in enumerate(lines):
            if "latent_channels" in l or ("torch.cat" in l and "latent" in l):
                print(f"  {i+1}: {l}")


if __name__ == "__main__":
    main()

