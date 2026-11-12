"""Compile locale/ar/LC_MESSAGES/django.po -> django.mo without GNU gettext (handy on Windows).
Usage:  pip install polib   then   python tools/compile_po.py"""
import pathlib
import polib

base = pathlib.Path(__file__).resolve().parent.parent / "locale" / "ar" / "LC_MESSAGES"
polib.pofile(str(base / "django.po")).save_as_mofile(str(base / "django.mo"))
print("django.mo rebuilt")
