"""
Monkey-patch for CogVideoXImageToVideoPipeline.prepare_latents

Фикс: "Sizes of tensors must match except in dimension 1. Expected size 16 but got size 8"

Причина: в prepare_latents image_latents кодируется VAE из изображения,
а latent_padding создаётся через torch.zeros — если spatial размеры не совпадают,
torch.cat падает. Патч выравнивает latent_padding под image_latents через interpolate.

Применять ДО импорта CogVideoXImageToVideoPipeline:
    import src.patches.cogvideox_patch  # noqa: F401
"""
import logging
import pathlib

logger = logging.getLogger(__name__)


def apply() -> None:
    try:
        import diffusers

        pipeline_file = pathlib.Path(diffusers.__file__).parent / \
            "pipelines/cogvideo/pipeline_cogvideox_image2video.py"

        if not pipeline_file.exists():
            logger.warning(f"cogvideox_patch: file not found: {pipeline_file}")
            return

        src = pipeline_file.read_text()
        lines = src.splitlines()

        target_indices = [
            i for i, line in enumerate(lines)
            if "torch.cat" in line and "image_latents" in line and "latent_padding" in line
        ]

        if not target_indices:
            logger.info("cogvideox_patch: torch.cat pattern not found — skipping")
            return

        patched = False
        for idx in target_indices:
            if idx > 0 and "PATCH" in lines[idx - 1]:
                logger.info("cogvideox_patch: already patched — skipping")
                continue

            original_line = lines[idx]
            indent = len(original_line) - len(original_line.lstrip())
            pad = " " * indent

            replacement = [
                f"{pad}# PATCH cogvideox_patch.py: align spatial dims before cat",
                f"{pad}if image_latents.shape[2:] != latent_padding.shape[2:]:",
                f"{pad}    import torch.nn.functional as _F",
                f"{pad}    _b, _t = latent_padding.shape[:2]",
                f"{pad}    latent_padding = _F.interpolate(",
                f"{pad}        latent_padding.reshape(_b * _t, *latent_padding.shape[2:]).unsqueeze(0),",
                f"{pad}        size=image_latents.shape[2:],",
                f"{pad}        mode='nearest',",
                f"{pad}    ).squeeze(0).reshape(_b, _t, *image_latents.shape[2:])",
                original_line,
            ]
            lines[idx:idx + 1] = replacement
            patched = True

        if patched:
            pipeline_file.write_text("\n".join(lines) + "\n")
            logger.info(f"✅ cogvideox_patch applied to {pipeline_file}")

            # Перезагружаем модуль чтобы патч вступил в силу
            import importlib
            import diffusers.pipelines.cogvideo.pipeline_cogvideox_image2video as _mod
            importlib.reload(_mod)
            import diffusers.pipelines.cogvideo as _pkg
            importlib.reload(_pkg)
            logger.info("✅ cogvideox module reloaded")

    except Exception as e:
        logger.warning(f"cogvideox_patch failed (non-fatal): {e}")

