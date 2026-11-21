import numpy as np
import pytest
import tifffile
from astropy.io import fits

from frameforge.core.io import UnsupportedFormatError, open_source
from frameforge.core.io.registry import collect_files
from synthetic import planet, write_ser


def test_ser_8bit_roundtrip(tmp_path):
    frames = [planet(seed=i) for i in range(5)]
    path = write_ser(tmp_path / "a.ser", frames)
    with open_source(path) as src:
        assert src.info.format == "SER"
        assert src.info.frame_count == 5
        assert (src.info.width, src.info.height) == (256, 256)
        assert src.info.fps == pytest.approx(50.0)
        f = src.read_frame(2)
        assert f.dtype == np.float32 and f.shape == (256, 256)
        assert np.allclose(f, (frames[2] * 255).round() / 255, atol=1e-6)


@pytest.mark.parametrize("byteorder,flag,depth", [("<", 0, 12), ("<", 1, 16), (">", 0, 16), (">", 1, 14)])
def test_ser_16bit_byteorder_detection(tmp_path, byteorder, flag, depth):
    frames = [planet(seed=i) for i in range(3)]
    path = write_ser(tmp_path / "b.ser", frames, depth=depth, flag=flag, byteorder=byteorder)
    with open_source(path) as src:
        assert src.byteorder == byteorder
        assert np.allclose(src.read_frame(1), frames[1], atol=2.0 / (2**depth - 1))


def test_ser_truncated_file_warns(tmp_path):
    path = write_ser(tmp_path / "c.ser", [planet() for _ in range(4)], timestamps=False)
    data = path.read_bytes()
    path.write_bytes(data[: len(data) - 1000])
    with open_source(path) as src:
        assert src.info.frame_count == 3
        assert src.info.warnings


def test_invalid_ser(tmp_path):
    p = tmp_path / "x.ser"
    p.write_bytes(b"not a ser file" * 20)
    with pytest.raises(UnsupportedFormatError):
        open_source(p)


def test_fits_single_and_cube(tmp_path):
    img = (planet() * 65535).astype(np.uint16)
    single = tmp_path / "s.fits"
    fits.PrimaryHDU(img).writeto(single)  # astropy stores uint16 as int16 + BZERO 32768
    with open_source(single) as src:
        assert src.info.frame_count == 1 and not src.info.is_video
        assert np.allclose(src.read_frame(0), img / 65535.0, atol=1e-4)

    cube = np.stack([img, img // 2, img // 4])
    cube = np.concatenate([cube, cube[:1]])  # 4 frames -> not interpreted as RGB
    path = tmp_path / "c.fits"
    fits.PrimaryHDU(cube).writeto(path)
    with open_source(path) as src:
        assert src.info.frame_count == 4 and src.info.is_video
        assert src.read_frame(1).mean() == pytest.approx(src.read_frame(0).mean() / 2, rel=0.01)


def test_fits_rgb_and_bayer(tmp_path):
    img = (planet() * 65535).astype(np.uint16)
    rgb = tmp_path / "rgb.fits"
    fits.PrimaryHDU(np.stack([img, img, img])).writeto(rgb)
    with open_source(rgb) as src:
        assert src.info.color == "rgb" and src.info.frame_count == 1
    bayer = tmp_path / "bayer.fits"
    hdu = fits.PrimaryHDU(img)
    hdu.header["BAYERPAT"] = "RGGB"
    hdu.writeto(bayer)
    with open_source(bayer) as src:
        assert src.info.color == "bayer_RGGB"
        assert src.read_frame(0).shape == (128, 128)


def test_tiff_variants(tmp_path):
    img = (planet() * 65535).astype(np.uint16)
    p1 = tmp_path / "mono.tif"
    tifffile.imwrite(p1, img)
    with open_source(p1) as src:
        assert src.info.frame_count == 1 and src.info.bit_depth == 16
        assert np.allclose(src.read_frame(0), img / 65535.0, atol=1e-5)
    p2 = tmp_path / "rgb.tif"
    tifffile.imwrite(p2, np.stack([img, img, img], axis=-1), photometric="rgb")
    with open_source(p2) as src:
        assert src.info.color == "rgb"
    p3 = tmp_path / "multi.tif"
    with tifffile.TiffWriter(p3) as tw:
        for k in range(3):
            tw.write(img // (k + 1))
    with open_source(p3) as src:
        assert src.info.frame_count == 3
        assert src.read_frame(2).mean() < src.read_frame(0).mean()
    p4 = tmp_path / "lzw.tif"
    tifffile.imwrite(p4, img, compression="zlib")
    with open_source(p4) as src:
        assert src.read_frame(0).shape == img.shape


def test_png(tmp_path):
    import cv2
    p = tmp_path / "a.png"
    cv2.imwrite(str(p), (planet() * 255).astype(np.uint8))
    with open_source(p) as src:
        assert src.info.format == "PNG"
        assert src.read_frame(0).max() > 0.5


def test_avi(tmp_path):
    import cv2
    p = tmp_path / "v.avi"
    vw = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"MJPG"), 25, (256, 256), isColor=False)
    if not vw.isOpened():
        pytest.skip("OpenCV build without AVI writer")
    for i in range(10):
        vw.write((planet(blur=i * 0.3) * 255).astype(np.uint8))
    vw.release()
    with open_source(p) as src:
        assert src.info.frame_count == 10 and src.info.color == "mono"
        got = list(src.iter_frames([0, 5, 9]))
        assert [i for i, _ in got] == [0, 5, 9]


def test_collect_files(tmp_path):
    (tmp_path / "sub").mkdir()
    write_ser(tmp_path / "a.ser", [planet()])
    write_ser(tmp_path / "sub" / "b.ser", [planet()])
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "._a.ser").write_bytes(b"x")
    assert [p.name for p in collect_files([tmp_path])] == ["a.ser", "b.ser"]
    assert [p.name for p in collect_files([tmp_path], recursive=False)] == ["a.ser"]


def test_fits_float_extension_and_header_values(tmp_path):
    img = planet().astype(np.float32)
    path = tmp_path / "ext.fits"
    hdr = fits.Header()
    hdr["OBJECT"] = "Jupiter's moon"
    hdr["EXPTIME"] = 0.005
    fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(img, header=hdr)]).writeto(path)
    with open_source(path) as src:
        assert src.info.metadata["object"] == "Jupiter's moon"
        assert src.info.metadata["exptime"] == pytest.approx(0.005)
        assert np.allclose(src.read_frame(0), img, atol=1e-6)


def test_fits_compressed_via_astropy(tmp_path):
    img = (planet() * 65535).astype(np.uint16)
    path = tmp_path / "c.fits.fz"
    fits.HDUList([fits.PrimaryHDU(), fits.CompImageHDU(img)]).writeto(path.with_suffix(".fits"))
    with open_source(path.with_suffix(".fits")) as src:
        assert np.allclose(src.read_frame(0), img / 65535.0, atol=1e-4)


def test_fits_not_fits(tmp_path):
    p = tmp_path / "bad.fits"
    p.write_bytes(b"X" * 5000)
    with pytest.raises(UnsupportedFormatError):
        open_source(p)
