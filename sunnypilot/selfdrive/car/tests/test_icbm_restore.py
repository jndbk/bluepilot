import pytest
from cereal import car, custom
from opendbc.car import structs
from openpilot.common.constants import CV
from openpilot.sunnypilot.selfdrive.car.intelligent_cruise_button_management.controller import IntelligentCruiseButtonManagement

ButtonType = car.CarState.ButtonEvent.Type
ButtonEvent = car.CarState.ButtonEvent
State = custom.IntelligentCruiseButtonManagement.IntelligentCruiseButtonManagementState
SendButtonState = custom.IntelligentCruiseButtonManagement.SendButtonState
LongitudinalPlanSource = custom.LongitudinalPlanSP.LongitudinalPlanSource

def test_icbm_restore_user_set_speed():
  # Setup mock CP and CP_SP
  CP = structs.CarParams()
  CP_SP = structs.CarParamsSP()
  CP_SP.pcmCruiseSpeed = False

  # Instantiate ICBM
  icbm = IntelligentCruiseButtonManagement(CP, CP_SP)
  icbm.is_metric = True

  # 1. Cruise is set to Speed A (60 KPH)
  CS = car.CarState(
    cruiseState={
      "available": True,
      "enabled": True,
      "speed": 60 / CV.MS_TO_KPH,
      "speedCluster": 60 / CV.MS_TO_KPH,
    },
    vEgo=60 / CV.MS_TO_KPH
  )
  CC = car.CarControl(enabled=True)
  LP_SP = custom.LongitudinalPlanSP(
    vTarget=60 / CV.MS_TO_KPH,
    longitudinalPlanSource=LongitudinalPlanSource.cruise
  )

  # Run ICBM loop to settle into holding state (takes 40 frames for preActive timer to clear)
  for _ in range(50):
    icbm.run(CS, CC, LP_SP, is_metric=True)

  assert icbm.state == State.holding
  assert icbm.last_user_set_speed_kph == 60

  # 2. ICBM reduces speed to Speed B (40 KPH) due to curve
  LP_SP.longitudinalPlanSource = LongitudinalPlanSource.sccVision
  LP_SP.vTarget = 40 / CV.MS_TO_KPH

  # Settle into decreasing state (takes 2 steps: holding -> preActive -> decreasing)
  icbm.run(CS, CC, LP_SP, is_metric=True)  # transitions holding -> preActive
  icbm.run(CS, CC, LP_SP, is_metric=True)  # transitions preActive -> decreasing
  assert icbm.state == State.decreasing

  # Simulate the cluster speed decreasing to 40 KPH
  CS.cruiseState.speedCluster = 40 / CV.MS_TO_KPH
  CS.cruiseState.speed = 40 / CV.MS_TO_KPH
  CS.vEgo = 40 / CV.MS_TO_KPH

  # Run while decreasing
  icbm.run(CS, CC, LP_SP, is_metric=True)
  # Verify that last_user_set_speed_kph remains 60
  assert icbm.last_user_set_speed_kph == 60

  # 3. User taps brakes (disengages)
  CS.cruiseState.enabled = False
  CC.enabled = False
  icbm.run(CS, CC, LP_SP, is_metric=True)
  assert icbm.state == State.inactive
  # Verify that last_user_set_speed_kph still remains 60
  assert icbm.last_user_set_speed_kph == 60

  # 4. User re-engages (resumes) at speed B (40 KPH) and the curve is gone
  CS.cruiseState.enabled = True
  CS.cruiseState.speedCluster = 40 / CV.MS_TO_KPH
  CS.cruiseState.speed = 40 / CV.MS_TO_KPH
  CC.enabled = True
  LP_SP.longitudinalPlanSource = LongitudinalPlanSource.cruise
  LP_SP.vTarget = 40 / CV.MS_TO_KPH  # Limited by the cluster speed in the planner

  # Settle into increasing state (requires decrementing the pre-activation timer of 40 frames)
  for _ in range(45):
    icbm.run(CS, CC, LP_SP, is_metric=True)

  # Verify that initial_cruise_speed_kph was restored to 60 (Speed A)
  assert icbm.initial_cruise_speed_kph == 60
  # Verify that v_target was overridden to 60
  assert icbm.v_target == 60
  # Verify that ICBM wants to increase the speed
  assert icbm.state == State.increasing
  assert icbm.cruise_button == SendButtonState.increase
