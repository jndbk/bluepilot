from unittest.mock import MagicMock, patch
import pyray as rl
from openpilot.common.params import Params
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.selfdrive.ui.layouts.settings.recording import RecordingLayout


def _setup_mock_gui_app():
  dummy_font = rl.Font()
  gui_app._fonts = {
    FontWeight.NORMAL: dummy_font,
    FontWeight.MEDIUM: dummy_font,
    FontWeight.BOLD: dummy_font,
  }
  gui_app._textures = {}


def test_recording_layout_init_and_override():
  _setup_mock_gui_app()
  params = Params()
  params.put_bool("OverrideCabinRecording", False, block=True)
  params.put_bool("RecordFront", False, block=True)
  params.put_bool("RecordAudio", False, block=True)

  layout = RecordingLayout()
  assert not layout._override_toggle.action_item.get_state()
  assert not layout._record_front_toggle.action_item.get_state()
  assert not layout._record_audio_toggle.action_item.get_state()

  # Toggle override ON
  layout._override_callback(True)
  assert params.get_bool("OverrideCabinRecording")
  assert params.get_bool("RecordFront")
  assert params.get_bool("RecordAudio")
  assert layout._record_front_toggle.action_item.get_state()
  assert layout._record_audio_toggle.action_item.get_state()

  # Toggle override OFF
  layout._override_callback(False)
  assert not params.get_bool("OverrideCabinRecording")
  assert not params.get_bool("RecordFront")
  assert not params.get_bool("RecordAudio")
  assert not layout._record_front_toggle.action_item.get_state()
  assert not layout._record_audio_toggle.action_item.get_state()


def test_recording_layout_sub_toggles():
  _setup_mock_gui_app()
  params = Params()
  params.put_bool("OverrideCabinRecording", True, block=True)
  params.put_bool("RecordFront", True, block=True)
  params.put_bool("RecordAudio", True, block=True)

  layout = RecordingLayout()

  # Turn off front camera while keeping audio
  layout._param_callback("RecordFront", False)
  assert not params.get_bool("RecordFront")
  assert params.get_bool("RecordAudio")
  assert params.get_bool("OverrideCabinRecording")

  # Turn off audio as well -> should turn off override
  layout._param_callback("RecordAudio", False)
  assert not params.get_bool("RecordFront")
  assert not params.get_bool("RecordAudio")
  assert not params.get_bool("OverrideCabinRecording")
