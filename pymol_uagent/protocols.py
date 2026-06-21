from typing import Optional
from uagents import Model


class PingRequest(Model):
    pass


class PingResponse(Model):
    success: bool
    version: str = ""
    message: str = ""


class LoadStructureRequest(Model):
    source: str
    object_name: Optional[str] = ""


class LoadStructureResponse(Model):
    success: bool
    message: str


class ColorSelectionRequest(Model):
    color: str
    selection: str = "all"


class ColorSelectionResponse(Model):
    success: bool
    message: str


class RenderImageRequest(Model):
    output_path: str
    width: int = 800
    height: int = 600
    ray_trace: bool = False


class RenderImageResponse(Model):
    success: bool
    message: str
    image_path: str = ""
