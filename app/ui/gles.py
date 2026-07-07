"""Minimal GLES2 presenter for the UI canvas (via ctypes, no PyOpenGL).

Why this exists: on vc4/KMSDRM the display controller honors per-pixel alpha
on the ARGB scanout plane, and SDL's normal 2D present leaves alpha at zero,
so the whole frame composites as transparent (black screen). Presenting
through GL with a shader that forces alpha to 1.0 avoids that. The canvas is
drawn unscaled, centered in the screen via the viewport.
"""

import ctypes
import logging

log = logging.getLogger("controller.ui.gles")

GL_VERTEX_SHADER = 0x8B31
GL_FRAGMENT_SHADER = 0x8B30
GL_COMPILE_STATUS = 0x8B81
GL_LINK_STATUS = 0x8B82
GL_COLOR_BUFFER_BIT = 0x4000
GL_TEXTURE_2D = 0x0DE1
GL_RGBA = 0x1908
GL_UNSIGNED_BYTE = 0x1401
GL_TEXTURE_MIN_FILTER = 0x2801
GL_TEXTURE_MAG_FILTER = 0x2800
GL_TEXTURE_WRAP_S = 0x2802
GL_TEXTURE_WRAP_T = 0x2803
GL_CLAMP_TO_EDGE = 0x812F
GL_NEAREST = 0x2600
GL_FLOAT = 0x1406
GL_TRIANGLE_STRIP = 0x0005

VERTEX_SHADER = b"""
attribute vec2 pos;
attribute vec2 uv;
varying vec2 v_uv;
void main() {
    gl_Position = vec4(pos, 0.0, 1.0);
    v_uv = uv;
}
"""

# Alpha forced to 1.0: this is the entire point of this module. The swizzle
# ("rgb" or "bgr") matches the canvas surface's in-memory byte order so raw
# pixel buffers can be uploaded without a per-frame CPU conversion.
FRAGMENT_SHADER_TEMPLATE = b"""
precision mediump float;
varying vec2 v_uv;
uniform sampler2D tex;
void main() {
    gl_FragColor = vec4(texture2D(tex, v_uv).%s, 1.0);
}
"""

# Per-rotation UVs for the fullscreen quad, vertex order BL, BR, TL, TR in
# clip space; texture row 0 is the canvas top. Rotation is how far the canvas
# is turned CLOCKWISE on the screen (90/270 for portrait-scan panels whose
# framebuffer is the transpose of the canvas).
_QUAD_UVS = {
    0: ((0, 1), (1, 1), (0, 0), (1, 0)),
    90: ((1, 1), (1, 0), (0, 1), (0, 0)),
    180: ((1, 0), (0, 0), (1, 1), (0, 1)),
    270: ((0, 0), (0, 1), (1, 0), (1, 1)),
}
_QUAD_POS = ((-1, -1), (+1, -1), (-1, +1), (+1, +1))


def _build_quad(rotation: int):
    values = []
    for pos, uv in zip(_QUAD_POS, _QUAD_UVS[rotation]):
        values.extend(pos)
        values.extend(uv)
    return (ctypes.c_float * 16)(*values)


class CanvasPresenter:
    def __init__(self, screen_size: tuple[int, int], canvas_size: tuple[int, int],
                 swizzle: str = "rgb", rotation: int = 0):
        if swizzle not in ("rgb", "bgr"):
            raise ValueError(f"unsupported swizzle {swizzle!r}")
        if rotation not in _QUAD_UVS:
            raise ValueError(f"unsupported rotation {rotation!r}")
        self.rotation = rotation
        self.screen_w, self.screen_h = screen_size
        self.canvas_w, self.canvas_h = canvas_size
        self.gl = gl = ctypes.CDLL("libGLESv2.so.2")
        gl.glClearColor.argtypes = [ctypes.c_float] * 4

        fragment_shader = FRAGMENT_SHADER_TEMPLATE % swizzle.encode()
        program = gl.glCreateProgram()
        for kind, src in ((GL_VERTEX_SHADER, VERTEX_SHADER), (GL_FRAGMENT_SHADER, fragment_shader)):
            gl.glAttachShader(program, self._compile(kind, src))
        gl.glLinkProgram(program)
        status = ctypes.c_int(0)
        gl.glGetProgramiv(program, GL_LINK_STATUS, ctypes.byref(status))
        if not status.value:
            raise RuntimeError("GLES program link failed")
        gl.glUseProgram(program)

        tex = ctypes.c_uint(0)
        gl.glGenTextures(1, ctypes.byref(tex))
        gl.glBindTexture(GL_TEXTURE_2D, tex)
        for param, value in (
            (GL_TEXTURE_MIN_FILTER, GL_NEAREST),
            (GL_TEXTURE_MAG_FILTER, GL_NEAREST),
            (GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE),
            (GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE),
        ):
            gl.glTexParameteri(GL_TEXTURE_2D, param, value)
        gl.glTexImage2D(
            GL_TEXTURE_2D, 0, GL_RGBA, self.canvas_w, self.canvas_h,
            0, GL_RGBA, GL_UNSIGNED_BYTE, None,
        )

        stride = 4 * ctypes.sizeof(ctypes.c_float)
        self._quad = _build_quad(rotation)  # instance ref: keep alive for GL
        quad_addr = ctypes.cast(self._quad, ctypes.c_void_p).value
        for name, offset in ((b"pos", 0), (b"uv", 2)):
            loc = gl.glGetAttribLocation(program, name)
            gl.glEnableVertexAttribArray(loc)
            gl.glVertexAttribPointer(
                loc, 2, GL_FLOAT, 0, stride,
                ctypes.c_void_p(quad_addr + offset * ctypes.sizeof(ctypes.c_float)),
            )

        # On-screen footprint: canvas dims, transposed when rotated 90/270.
        out_w, out_h = ((self.canvas_h, self.canvas_w) if rotation in (90, 270)
                        else (self.canvas_w, self.canvas_h))
        self._viewport = (
            (self.screen_w - out_w) // 2,
            (self.screen_h - out_h) // 2,
            out_w,
            out_h,
        )
        log.info("GLES presenter ready, viewport %s, rotation %d°",
                 self._viewport, rotation)

    def _compile(self, kind: int, src: bytes) -> int:
        gl = self.gl
        shader = gl.glCreateShader(kind)
        buf = ctypes.c_char_p(src)
        gl.glShaderSource(shader, 1, ctypes.byref(buf), None)
        gl.glCompileShader(shader)
        status = ctypes.c_int(0)
        gl.glGetShaderiv(shader, GL_COMPILE_STATUS, ctypes.byref(status))
        if not status.value:
            info = ctypes.create_string_buffer(512)
            gl.glGetShaderInfoLog(shader, 512, None, info)
            raise RuntimeError(f"GLES shader compile failed: {info.value.decode()}")
        return shader

    def present(self, pixels) -> None:
        """Upload the canvas pixels and draw them centered; caller flips.
        `pixels` is either a bytes object or an int address of a raw pixel
        buffer (zero-copy path; byte order must match the swizzle)."""
        gl = self.gl
        gl.glViewport(0, 0, self.screen_w, self.screen_h)
        gl.glClearColor(0.0, 0.0, 0.0, 1.0)
        gl.glClear(GL_COLOR_BUFFER_BIT)
        if isinstance(pixels, int):
            pixels = ctypes.c_void_p(pixels)
        gl.glTexSubImage2D(
            GL_TEXTURE_2D, 0, 0, 0, self.canvas_w, self.canvas_h,
            GL_RGBA, GL_UNSIGNED_BYTE, pixels,
        )
        gl.glViewport(*self._viewport)
        gl.glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
