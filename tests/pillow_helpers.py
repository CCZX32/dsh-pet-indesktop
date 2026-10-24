"""Pixel assertions across the declared Pillow>=10.3 support range."""


def pixels(image):
    """Use the new API when available, without monkeypatching Pillow globally."""
    flattened = getattr(image, "get_flattened_data", None)
    return list(flattened() if flattened is not None else image.getdata())
