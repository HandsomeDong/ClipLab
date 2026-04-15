import numpy as np

from cliplab_backend.schemas import WatermarkRegion
from cliplab_backend.services.watermark import (
    build_watermark_output_path,
    clamp_region,
    create_mask,
    get_inpaint_areas_by_mask,
)


def test_clamp_region_maps_normalized_coordinates():
    region = WatermarkRegion(x=0.25, y=0.5, width=0.2, height=0.1)
    assert clamp_region(region, 1000, 500) == (250, 250, 450, 300)


def test_create_mask_expands_selected_area():
    mask = create_mask((120, 200), [(50, 80, 40, 60)], expand_pixels=10)
    assert mask[20, 20] == 0
    assert mask[40, 50] == 255
    assert mask[30, 40] == 255
    assert mask[70, 90] == 255


def test_get_inpaint_areas_stays_compact_for_corner_watermark():
    mask = np.zeros((180, 320), dtype=np.uint8)
    mask[130:150, 250:290] = 255
    areas = get_inpaint_areas_by_mask(320, 180, 50, mask, multiple=2)
    assert len(areas) == 1
    ymin, ymax, xmin, xmax = areas[0]
    assert ymin <= 130 < ymax
    assert xmin <= 250 < xmax
    assert xmax - xmin < 140


def test_build_watermark_output_path_defaults_to_input_directory(tmp_path):
    input_path = tmp_path / "demo.mp4"
    input_path.write_bytes(b"video")

    output_path = build_watermark_output_path(str(input_path), "")

    assert output_path.parent == tmp_path
    assert output_path.name == "demo_no_watermark.mp4"
