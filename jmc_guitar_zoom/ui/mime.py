"""Drag and drop payload formats shared by the chain, the patch list and the catalog."""

MIME_EFFECT = "application/x-jmc-guitar-zoom-effect"  # payload: catalog effect ID (decimal text)
MIME_SLOT = "application/x-jmc-guitar-zoom-slot"  # payload: slot index of a chain pedal (decimal text)
MIME_PATCH = "application/x-jmc-guitar-zoom-patch"  # payload: location of a patch in the list (decimal text)
