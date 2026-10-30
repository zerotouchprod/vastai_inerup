from src.serverless.handler import redact_urls


def test_presigned_query_is_redacted():
    line = "Error opening input 'https://b.s3.amazonaws.com/k.mp4?X-Amz-Signature=abc&X-Amz-Credential=x': 403\n"
    out = redact_urls(line)
    assert "abc" not in out and "Credential" not in out
    assert "https://b.s3.amazonaws.com/k.mp4?<redacted>'" in out


def test_plain_text_untouched():
    assert redact_urls("Real-ESRGAN START job=1 chunk=2\n") == "Real-ESRGAN START job=1 chunk=2\n"
