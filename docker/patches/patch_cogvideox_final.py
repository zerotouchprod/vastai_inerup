"""
Финальный патч pipeline_cogvideox_image2video.py для diffusers==0.31.0

КОРНЕВАЯ ПРИЧИНА (подтверждена тестами):
  Строка 771: torch.cat([latent_model_input, latent_image_input], dim=2)

  latents shape из prepare_latents: [B, T, C, H, W] = [B, 13, 16, 60, 90]
  dim=2 в этом формате = C (channel) = 16
  cat по dim=2 должен давать [B, 13, 32, 60, 90] — это ПРАВИЛЬНО для in_channels=32

  НО scheduler.scale_model_input делает permute [B,T,C,H,W] → [B,C,T,H,W]
  Тогда dim=2 = T (temporal) = 13, а latent_image_input.dim2 = 24 → ошибка

ФИКС:
  Перед cat проверяем реальный формат и используем правильный dim.
  Если latent_model_input.shape[1] != latent_image_input.shape[1] → dim=1 (temporal формат)
  Иначе dim=2 (channel формат)
"""
import pathlib
import sys


def main() -> None:
    f = pathlib.Path(
        "/usr/local/lib/python3.11/dist-packages/diffusers/pipelines/cogvideo/pipeline_cogvideox_image2video.py"
    )
    if not f.exists():
        print(f"❌ Not found: {f}")
        sys.exit(1)

    import diffusers
    print(f"diffusers: {diffusers.__version__}")

    lines = f.read_text().splitlines()

    # Найти строку 771: torch.cat([latent_model_input, latent_image_input], dim=2)
    target_idx = next(
        (i for i, l in enumerate(lines)
         if "torch.cat" in l
         and "latent_model_input" in l
         and "latent_image_input" in l
         and "dim=2" in l
         and "PATCH" not in lines[max(0, i-1)]),
        None
    )

    if target_idx is None:
        print("❌ Target line not found. All torch.cat lines:")
        for i, l in enumerate(lines):
            if "torch.cat" in l:
                print(f"  {i+1}: {l.strip()}")
        sys.exit(1)

    print(f"Found target at line {target_idx+1}: {lines[target_idx].strip()}")

    pad = " " * (len(lines[target_idx]) - len(lines[target_idx].lstrip()))
    original = lines[target_idx]

    # Также найти строку с latent_image_input = torch.cat([image_latents] * 2)
    # и добавить permute чтобы привести к формату latent_model_input
    img_input_idx = next(
        (i for i, l in enumerate(lines)
         if "latent_image_input" in l and "image_latents" in l and "cat" in l
         and "PATCH" not in lines[max(0, i-1)]),
        None
    )

    if img_input_idx is not None:
        print(f"Found latent_image_input at line {img_input_idx+1}: {lines[img_input_idx].strip()}")
        img_pad = " " * (len(lines[img_input_idx]) - len(lines[img_input_idx].lstrip()))
        orig_img_line = lines[img_input_idx]
        lines[img_input_idx:img_input_idx + 1] = [
            orig_img_line,
            f"{img_pad}# PATCH Final: permute image_latents [B,T,C,H,W] → [B,C,T,H,W] to match latent_model_input",
            f"{img_pad}if latent_image_input.shape[1] != latent_model_input.shape[1]:",
            f"{img_pad}    latent_image_input = latent_image_input.permute(0, 2, 1, 3, 4)",
            f"{img_pad}    # align temporal dim after permute",
            f"{img_pad}    if latent_image_input.shape[2] != latent_model_input.shape[2]:",
            f"{img_pad}        _t_diff = latent_model_input.shape[2] - latent_image_input.shape[2]",
            f"{img_pad}        if _t_diff > 0:",
            f"{img_pad}            import torch as _torch",
            f"{img_pad}            _pad = _torch.zeros(*latent_image_input.shape[:2], _t_diff, *latent_image_input.shape[3:],",
            f"{img_pad}                               device=latent_image_input.device, dtype=latent_image_input.dtype)",
            f"{img_pad}            latent_image_input = _torch.cat([latent_image_input, _pad], dim=2)",
            f"{img_pad}        else:",
            f"{img_pad}            latent_image_input = latent_image_input[:, :, :latent_model_input.shape[2]]",
        ]
        print(f"  ✅ patched latent_image_input")

    f.write_text("\n".join(lines) + "\n")
    print(f"✅ Final patch applied to {f}")


if __name__ == "__main__":
    main()

