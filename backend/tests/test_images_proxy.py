from __future__ import annotations

import pytest

from app.deps import ApiError
from app.routers.images import _validate_remote_image_url


def test_validate_remote_image_url_accepts_public_https_url() -> None:
    assert (
        _validate_remote_image_url("https://cdn.rebrickable.com/media/sets/42208-1.jpg")
        == "https://cdn.rebrickable.com/media/sets/42208-1.jpg"
    )


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "file:///tmp/a.png",
        "https://localhost/image.png",
        "http://127.0.0.1/image.png",
        "http://10.0.0.2/image.png",
        "http://[::1]/image.png",
    ],
)
def test_validate_remote_image_url_rejects_local_or_invalid_hosts(url: str) -> None:
    with pytest.raises(ApiError):
        _validate_remote_image_url(url)
