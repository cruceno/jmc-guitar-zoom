import jmc_guitar_zoom


def test_package_exposes_version():
    assert jmc_guitar_zoom.__version__ == "0.2.0"


def test_upstream_modules_are_importable():
    import decode_preset  # noqa: F401  upstream ZPTC definitions are reused, not copied
    import zoomzt2  # noqa: F401  upstream protocol and ZD2/ZT2 definitions
