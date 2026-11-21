"""Readers for astronomical image and video formats."""

from .base import FrameSource, SourceInfo, UnsupportedFormatError
from .registry import SUPPORTED_EXTENSIONS, is_supported, open_source

__all__ = [
    "FrameSource",
    "SourceInfo",
    "UnsupportedFormatError",
    "SUPPORTED_EXTENSIONS",
    "is_supported",
    "open_source",
]
