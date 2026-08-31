from openpilot.common.params import Params
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.list_view import toggle_item
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.selfdrive.ui.ui_state import ui_state

if gui_app.sunnypilot_ui():
  from openpilot.system.ui.sunnypilot.widgets.list_view import toggle_item_sp as toggle_item


DESCRIPTIONS = {
  "OverrideCabinRecording": tr_noop(
    "By default, cabin audio and driver camera video are never recorded to disk to protect your privacy. "
    "Driver attention monitoring remains fully active in real time for safety. "
    "Enable this override to allow recording driver camera video and cabin microphone audio to disk."
  ),
  "RecordFront": tr_noop(
    "Record driver-facing camera video (dcamera.hevc) to disk while driving."
  ),
  "RecordAudio": tr_noop(
    "Record and store cabin microphone audio while driving. The audio will be included in the saved logs."
  ),
}


class RecordingLayout(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()

    override_state = self._params.get_bool("OverrideCabinRecording")
    record_front_state = self._params.get_bool("RecordFront")
    record_audio_state = self._params.get_bool("RecordAudio")

    self._override_toggle = toggle_item(
      lambda: tr("Record Cabin Audio & Video"),
      DESCRIPTIONS["OverrideCabinRecording"],
      override_state,
      callback=self._override_callback,
      icon="monitoring.png",
    )

    self._record_front_toggle = toggle_item(
      lambda: tr("Record Driver Camera Video"),
      DESCRIPTIONS["RecordFront"],
      record_front_state,
      callback=lambda state: self._param_callback("RecordFront", state),
      icon="driver_face.png",
    )

    self._record_audio_toggle = toggle_item(
      lambda: tr("Record Cabin Microphone Audio"),
      DESCRIPTIONS["RecordAudio"],
      record_audio_state,
      callback=lambda state: self._param_callback("RecordAudio", state),
      icon="microphone.png",
    )

    # Sub-toggles only active when override is enabled
    self._record_front_toggle.action_item.set_enabled(override_state and (lambda: not ui_state.engaged)())
    self._record_audio_toggle.action_item.set_enabled(override_state and (lambda: not ui_state.engaged)())

    self._items = [
      self._override_toggle,
      self._record_front_toggle,
      self._record_audio_toggle,
    ]

    self._scroller = Scroller(self._items, line_separator=True, spacing=0)
    ui_state.add_engaged_transition_callback(self._update_toggles)

  def _override_callback(self, state: bool):
    self._params.put_bool("OverrideCabinRecording", state, block=True)
    if state:
      # If turning on override, enable both recordings by default
      self._params.put_bool("RecordFront", True, block=True)
      self._params.put_bool("RecordAudio", True, block=True)
      self._record_front_toggle.action_item.set_state(True)
      self._record_audio_toggle.action_item.set_state(True)
    else:
      # If turning off override, enforce disabling both recordings
      self._params.put_bool("RecordFront", False, block=True)
      self._params.put_bool("RecordAudio", False, block=True)
      self._record_front_toggle.action_item.set_state(False)
      self._record_audio_toggle.action_item.set_state(False)

    self._record_front_toggle.action_item.set_enabled(state and not ui_state.engaged)
    self._record_audio_toggle.action_item.set_enabled(state and not ui_state.engaged)

  def _param_callback(self, param: str, state: bool):
    self._params.put_bool(param, state, block=True)
    # If both sub-toggles are turned off, turn off override as well
    front = self._params.get_bool("RecordFront")
    audio = self._params.get_bool("RecordAudio")
    if not front and not audio:
      self._params.put_bool("OverrideCabinRecording", False, block=True)
      self._override_toggle.action_item.set_state(False)
      self._record_front_toggle.action_item.set_enabled(False)
      self._record_audio_toggle.action_item.set_enabled(False)

  def _update_toggles(self):
    ui_state.update_params()
    override_state = self._params.get_bool("OverrideCabinRecording")
    self._override_toggle.action_item.set_state(override_state)
    self._override_toggle.action_item.set_enabled(not ui_state.engaged)

    self._record_front_toggle.action_item.set_state(self._params.get_bool("RecordFront"))
    self._record_front_toggle.action_item.set_enabled(override_state and not ui_state.engaged)

    self._record_audio_toggle.action_item.set_state(self._params.get_bool("RecordAudio"))
    self._record_audio_toggle.action_item.set_enabled(override_state and not ui_state.engaged)

  def show_event(self):
    super().show_event()
    self._scroller.show_event()
    self._update_toggles()

  def _render(self, rect):
    self._scroller.render(rect)
