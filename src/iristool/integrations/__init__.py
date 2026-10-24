"""Optional dataset sources. Install iristool[kaggle] or iristool[huggingface]."""

from .kaggle import import_dataset as import_kaggle
from .huggingface import import_dataset as import_huggingface

__all__ = ["import_kaggle", "import_huggingface"]
