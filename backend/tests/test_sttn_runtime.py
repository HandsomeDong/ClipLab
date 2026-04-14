from pathlib import Path

import pytest

from cliplab_backend.inpaint import STTNInpaintError, STTNInpaintRuntime


def test_sttn_runtime_requires_torch_and_weights():
    with pytest.raises(STTNInpaintError):
        STTNInpaintRuntime(Path("/tmp/missing-sttn-model.pth"))
