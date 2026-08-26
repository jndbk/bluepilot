"""BluePilot On-Road Cabin / Back-Seat Camera Monitor (Picture-in-Picture).

Provides a live, on-road video feed of the vehicle cabin/back-seat using the
existing driver camera stream without entering off-road calibration mode or
interrupting cruise, steering control, or driver monitoring.
"""

from enum import IntEnum
import pyray as rl
from msgq.visionipc import VisionStreamType
from openpilot.common.params import Params
from openpilot.selfdrive.ui.onroad.cameraview import CameraView
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.multilang import tr
from openpilot.selfdrive.ui.bp.lib.ui_debug_logger import bp_ui_log


class CabinPipSize(IntEnum):
  SMALL = 0
  MEDIUM = 1
  LARGE = 2


# (Width, Height) for each size mode
PIP_DIMENSIONS = {
  CabinPipSize.SMALL: (340.0, 212.0),
  CabinPipSize.MEDIUM: (460.0, 288.0),
  CabinPipSize.LARGE: (600.0, 375.0),
}

CORNER_ROUNDNESS = 0.08
BORDER_COLOR = rl.Color(80, 160, 240, 200)
BORDER_COLOR_PRESSED = rl.Color(120, 200, 255, 255)
BG_COLOR = rl.Color(15, 18, 24, 220)
BADGE_BG_COLOR = rl.Color(0, 0, 0, 160)
DOT_COLOR = rl.Color(50, 215, 75, 255)


class CabinCameraPip(CameraView):
  """Picture-in-Picture live cabin/rear-seat monitor for onroad display."""

  def __init__(self):
    super().__init__("camerad", VisionStreamType.VISION_STREAM_DRIVER)
    self._params = Params()
    self._enabled = self._params.get_bool("BPShowCabinCamera")
    try:
      self._size_mode = CabinPipSize(int(self._params.get("BPCabinCameraPipSize", return_default=True) or 1))
    except (ValueError, TypeError):
      self._size_mode = CabinPipSize.MEDIUM

    self._param_counter = 0
    self._current_rect = rl.Rectangle(0, 0, 0, 0)
    self._is_active = False

  def update_params(self) -> None:
    """Refresh params periodically."""
    self._param_counter += 1
    if self._param_counter >= 60:
      self._param_counter = 0
      self._enabled = self._params.get_bool("BPShowCabinCamera")
      try:
        self._size_mode = CabinPipSize(int(self._params.get("BPCabinCameraPipSize", return_default=True) or 1))
      except (ValueError, TypeError):
        self._size_mode = CabinPipSize.MEDIUM

  def is_active(self) -> bool:
    return self._enabled and ui_state.is_onroad()

  def cycle_size(self) -> None:
    """Cycle between Small -> Medium -> Large."""
    next_mode = CabinPipSize((self._size_mode.value + 1) % len(CabinPipSize))
    self._size_mode = next_mode
    self._params.put("BPCabinCameraPipSize", int(next_mode.value))

  def toggle_enabled(self) -> None:
    """Toggle cabin monitor on/off."""
    self._enabled = not self._enabled
    self._params.put_bool("BPShowCabinCamera", self._enabled)

  def _handle_mouse_release(self, touch_pos: rl.Vector2) -> None:
    """Tapping the PiP tile cycles its size."""
    super()._handle_mouse_release(touch_pos)
    if rl.check_collision_point_rec(touch_pos, self._current_rect):
      self.cycle_size()

  def render_pip(self, parent_rect: rl.Rectangle, bottom_offset: float = 0.0) -> None:
    """Render the Picture-in-Picture tile inside the provided parent rect."""
    self.update_params()
    if not self.is_active():
      return

    pip_w, pip_h = PIP_DIMENSIONS.get(self._size_mode, PIP_DIMENSIONS[CabinPipSize.MEDIUM])
    margin_x = 25.0
    margin_y = 25.0 + bottom_offset

    # Place in lower-right corner of onroad screen
    x = parent_rect.x + parent_rect.width - pip_w - margin_x
    y = parent_rect.y + parent_rect.height - pip_h - margin_y
    self._current_rect = rl.Rectangle(x, y, pip_w, pip_h)
    self.set_rect(self._current_rect)

    # Draw card background & drop glow
    rl.draw_rectangle_rounded(
      rl.Rectangle(x - 2, y - 2, pip_w + 4, pip_h + 4),
      CORNER_ROUNDNESS,
      8,
      rl.Color(0, 0, 0, 100),
    )
    rl.draw_rectangle_rounded(self._current_rect, CORNER_ROUNDNESS, 8, BG_COLOR)

    # Video viewport with 3px inner margin
    inner_margin = 3.0
    inner_rect = rl.Rectangle(
      x + inner_margin,
      y + inner_margin,
      pip_w - 2 * inner_margin,
      pip_h - 2 * inner_margin,
    )

    # Render video stream within scissor region
    rl.begin_scissor_mode(
      int(inner_rect.x),
      int(inner_rect.y),
      int(inner_rect.width),
      int(inner_rect.height),
    )

    # Render frame using CameraView pipeline
    CameraView._render(self, inner_rect)

    if not self.frame:
      # Placeholder text when camera stream is starting
      label_text = tr("Cabin Camera")
      font_size = 28
      font = gui_app.font(FontWeight.BOLD)
      text_w = rl.measure_text_ex(font, label_text, font_size, 0).x
      text_x = inner_rect.x + (inner_rect.width - text_w) / 2
      text_y = inner_rect.y + (inner_rect.height - font_size) / 2
      rl.draw_text_ex(font, label_text, rl.Vector2(text_x, text_y), font_size, 0, rl.Color(180, 190, 205, 200))

    rl.end_scissor_mode()

    # Draw stylish rounded border
    border_color = BORDER_COLOR_PRESSED if self.is_pressed else BORDER_COLOR
    rl.draw_rectangle_rounded_lines_ex(self._current_rect, CORNER_ROUNDNESS, 8, 2.5, border_color)

    # Draw "CABIN" badge in top-left of PiP tile
    badge_x = x + 10
    badge_y = y + 10
    badge_w = 78.0
    badge_h = 24.0
    rl.draw_rectangle_rounded(rl.Rectangle(badge_x, badge_y, badge_w, badge_h), 0.4, 4, BADGE_BG_COLOR)

    # Live green indicator dot
    dot_radius = 4.0
    dot_center_x = badge_x + 10
    dot_center_y = badge_y + badge_h / 2
    rl.draw_circle(int(dot_center_x), int(dot_center_y), dot_radius, DOT_COLOR)

    # Badge text
    badge_font = gui_app.font(FontWeight.BOLD)
    badge_text = "CABIN"
    rl.draw_text_ex(badge_font, badge_text, rl.Vector2(badge_x + 20, badge_y + 4), 16, 0, rl.WHITE)
