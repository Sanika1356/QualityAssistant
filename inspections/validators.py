"""Shared upload check for inspection images. Looks at the file's bytes, never its name."""
import io
import warnings

from PIL import Image, UnidentifiedImageError

MAX_BYTES = 5 * 1024 * 1024  # 5 MiB
MIN_SIDE = 64
MAX_SIDE = 4096
ALLOWED_FORMATS = {'JPEG', 'PNG'}


def validate_image(file):
    """Return None if the upload is a usable JPEG/PNG, otherwise a readable reason.

    `file` may be a Django UploadedFile, any binary file object, or a path.
    """
    if isinstance(file, (str, bytes)) or hasattr(file, '__fspath__'):
        with open(file, 'rb') as f:
            return validate_image(f)

    if hasattr(file, 'seek'):
        file.seek(0)
    data = file.read(MAX_BYTES + 1)
    if hasattr(file, 'seek'):
        file.seek(0)

    if not data:
        return 'File is empty.'
    if len(data) > MAX_BYTES:
        return 'File is larger than the 5 MiB limit.'

    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in ALLOWED_FORMATS:
                    return f'Unsupported image type ({image.format}). Only JPEG and PNG are accepted.'
                width, height = image.size
                if not (MIN_SIDE <= width <= MAX_SIDE and MIN_SIDE <= height <= MAX_SIDE):
                    return (
                        f'Image is {width}x{height} pixels; each side must be between '
                        f'{MIN_SIDE} and {MAX_SIDE} pixels.'
                    )
                # Decode every pixel so truncated or corrupt data is caught here, not in the model.
                image.load()
    except UnidentifiedImageError:
        return 'File is not a readable JPEG or PNG image.'
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        return 'Image has too many pixels to process safely.'
    except (OSError, SyntaxError, ValueError) as exc:
        return f'Image data is corrupt or incomplete ({exc}).'
    return None
