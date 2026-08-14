"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from cereal import car, custom
from opendbc.car import structs, apply_hysteresis
from openpilot.common.constants import CV
from openpilot.common.realtime import DT_CTRL

with open("/tmp/icbm.log", "a") as f:
  f.write("ICBM: controller.py imported!\n")
from openpilot.sunnypilot.selfdrive.car.intelligent_cruise_button_management.helpers import get_minimum_set_speed
from openpilot.sunnypilot.selfdrive.car.cruise_ext import CRUISE_BUTTON_TIMER, update_manual_button_timers

from openpilot.common.bluepilot import is_bluepilot
LongitudinalPlanSource = custom.LongitudinalPlanSP.LongitudinalPlanSource
State = custom.IntelligentCruiseButtonManagement.IntelligentCruiseButtonManagementState
SendButtonState = custom.IntelligentCruiseButtonManagement.SendButtonState

ALLOWED_SPEED_THRESHOLD = 1.8  # m/s, ~4 MPH
HYST_GAP = 0.0  # currently disabled; TODO-SP: might need to be brand-specific
INACTIVE_TIMER = 0.4


SEND_BUTTONS = {
  State.increasing: SendButtonState.increase,
  State.decreasing: SendButtonState.decrease,
}


class IntelligentCruiseButtonManagement:
  def __init__(self, CP: structs.CarParams, CP_SP: structs.CarParamsSP):
    self.CP = CP
    self.CP_SP = CP_SP

    self.v_target = 0
    self.v_cruise_cluster = 0
    self.v_cruise_min = 0
    self.cruise_button = SendButtonState.none
    self.state = State.inactive
    self.pre_active_timer = 0

    self.is_ready = False
    self.is_ready_prev = False
    self.v_target_ms_last = 0.0
    self.is_metric = False

    self.cruise_button_timers = CRUISE_BUTTON_TIMER
    
    self.initial_cruise_speed_kph = 0
    self.last_user_set_speed_kph = 0
    self.cruise_enabled_prev = False
    self.frame = 0
    self.longitudinal_plan_source = LongitudinalPlanSource.cruise
    self.holding_frames = 0
    # End BluePilot

  @property
  def v_cruise_equal(self) -> bool:
    return self.v_target == self.v_cruise_cluster

  def update_calculations(self, CS: car.CarState, LP_SP: custom.LongitudinalPlanSP) -> None:
    speed_conv = CV.MS_TO_KPH if self.is_metric else CV.MS_TO_MPH
    ms_conv = CV.KPH_TO_MS if self.is_metric else CV.MPH_TO_MS
    self.longitudinal_plan_source = LP_SP.longitudinalPlanSource

    # BluePilot: Capture initial cruise speed when cruise is first enabled
    # Use current speed (vEgo) as the initial setpoint if planner target is invalid/unreasonable
    cruise_enabled = CS.cruiseState.available and CS.cruiseState.enabled
    if cruise_enabled and not self.cruise_enabled_prev:
      # Cruise just enabled - capture last user set speed or current speed as initial setpoint
      if self.last_user_set_speed_kph > 0:
        self.initial_cruise_speed_kph = self.last_user_set_speed_kph
      else:
        current_speed_kph = CS.vEgo * CV.MS_TO_KPH
        self.initial_cruise_speed_kph = round(current_speed_kph)
      with open("/tmp/icbm.log", "a") as f:
        f.write(f"ICBM: Cruise enabled! last_user_set_speed_kph={self.last_user_set_speed_kph}, initial_cruise_speed_kph={self.initial_cruise_speed_kph}\n")
    self.cruise_enabled_prev = cruise_enabled
    # End BluePilot

    self.v_target_ms_last = apply_hysteresis(LP_SP.vTarget, self.v_target_ms_last, HYST_GAP * ms_conv)

    self.v_target = round(self.v_target_ms_last * speed_conv)
    self.v_cruise_min = get_minimum_set_speed(self.is_metric)
    self.v_cruise_cluster = round(CS.cruiseState.speedCluster * speed_conv)
    
    # BluePilot: If planner target is invalid/unreasonable and we have an initial cruise speed,
    # use the initial speed as the target. Also do this if the planner target is limited
    # only by the lower cruise set speed but we have a higher user-set speed.
    MAX_REASONABLE_TARGET = 145 if self.is_metric else 90
    is_invalid = self.v_target >= MAX_REASONABLE_TARGET or self.v_target == 0
    is_limited_by_cruise = (LP_SP.longitudinalPlanSource == LongitudinalPlanSource.cruise and 
                            self.initial_cruise_speed_kph > 0 and 
                            self.v_target < self.initial_cruise_speed_kph)
    if is_invalid or is_limited_by_cruise:
      # Planner target is invalid/limited - use initial cruise speed or cluster speed
      if self.initial_cruise_speed_kph > 0:
        self.v_target = self.initial_cruise_speed_kph
      elif self.v_cruise_cluster > 0:
        self.v_target = self.v_cruise_cluster
      
      # Print debug info on transition/limit
      if CS.cruiseState.enabled and self.frame % 50 == 0:
        with open("/tmp/icbm.log", "a") as f:
          f.write(f"ICBM: Active override! v_target={self.v_target}, initial_cruise_speed={self.initial_cruise_speed_kph}, is_limited={is_limited_by_cruise}, state={self.state}\n")

    # BluePilot: Track the user's manual set speed
    if self.state == State.holding:
      self.holding_frames += 1
    else:
      self.holding_frames = 0

    user_adjusting = any(self.cruise_button_timers[k] > 0 for k in self.cruise_button_timers)
    if CS.cruiseState.enabled and self.v_cruise_cluster > 0:
      # Only capture the cluster speed as the user's set speed if:
      # 1. The planner is targeting the cruise speed (no curve/limit active) and the speed is NOT lower than our stored set speed (unless user is adjusting)
      # 2. Or, the user is actively adjusting the buttons (must have been holding stable to filter out spoofed CAN messages).
      is_cruise_source = (LP_SP.longitudinalPlanSource == LongitudinalPlanSource.cruise)
      is_not_lower = (self.v_cruise_cluster >= self.last_user_set_speed_kph)
      real_user_adjusting = user_adjusting and (self.holding_frames > 10)
      if (self.state == State.holding and is_cruise_source and is_not_lower) or real_user_adjusting:
        self.last_user_set_speed_kph = self.v_cruise_cluster
        # Log when set speed is updated
        with open("/tmp/icbm.log", "a") as f:
          f.write(f"ICBM: Updated last_user_set_speed_kph to {self.last_user_set_speed_kph} (is_holding={self.state == State.holding}, real_adjusting={real_user_adjusting})\n")
    # End BluePilot

  def update_state_machine(self) -> custom.IntelligentCruiseButtonManagement.SendButtonState:
    self.pre_active_timer = max(0, self.pre_active_timer - 1)

    # HOLDING, ACCELERATING, DECELERATING, PRE_ACTIVE
    if self.state != State.inactive:
      if not self.is_ready:
        self.state = State.inactive

      else:
        # PRE_ACTIVE
        if self.state == State.preActive:
          if self.pre_active_timer <= 0:
            if self.v_cruise_equal:
              self.state = State.holding

            elif self.v_target > self.v_cruise_cluster:
              # BluePilot: Prevent ICBM from increasing speed when cruise is first enabled
              # If cluster speed is 0 or very low, don't increase - wait for user to set initial speed
              # Also cap target to reasonable maximum (145 kph / 90 mph)
              # Don't increase if target exceeds initial cruise speed by more than 5 mph/kph
              MAX_REASONABLE_TARGET = 145 if self.is_metric else 90
              MAX_INITIAL_INCREASE = 5  # Allow small increases from initial speed
              
              if self.v_cruise_cluster == 0 or self.v_target >= MAX_REASONABLE_TARGET:
                # Don't increase - stay in preActive or go to holding
                self.state = State.holding
              elif self.initial_cruise_speed_kph > 0 and self.v_target > (self.initial_cruise_speed_kph + MAX_INITIAL_INCREASE):
                # Don't increase beyond initial cruise speed + small margin
                # This prevents ICBM from ramping up when cruise is first enabled
                self.state = State.holding
              else:
                self.state = State.increasing

            elif (self.v_target < self.v_cruise_cluster and 
                  self.v_cruise_cluster > self.v_cruise_min and 
                  self.longitudinal_plan_source != LongitudinalPlanSource.cruise):
              self.state = State.decreasing

        # HOLDING
        elif self.state == State.holding:
          if not self.v_cruise_equal:
            self.state = State.preActive

        # ACCELERATING
        elif self.state == State.increasing:
          if self.v_target <= self.v_cruise_cluster:
            self.state = State.holding

        # DECELERATING
        elif self.state == State.decreasing:
          if self.v_target >= self.v_cruise_cluster or self.v_cruise_cluster <= self.v_cruise_min:
            self.state = State.holding

    # INACTIVE
    elif self.state == State.inactive:
      if self.is_ready and not self.is_ready_prev:
        self.pre_active_timer = int(INACTIVE_TIMER / DT_CTRL)
        self.state = State.preActive

    send_button = SEND_BUTTONS.get(self.state, SendButtonState.none)

    return send_button

  def update_readiness(self, CS: car.CarState, CC: car.CarControl) -> None:
    update_manual_button_timers(CS, self.cruise_button_timers)

    ready = CC.enabled and not CC.cruiseControl.override and not CC.cruiseControl.cancel and not CC.cruiseControl.resume
    button_pressed = any(self.cruise_button_timers[k] > 0 for k in self.cruise_button_timers)

    # BluePilot: Clear button timers when cruise is disabled to prevent stale presses
    # This ensures that when cruise is re-enabled, ICBM doesn't see stale button presses
    if not ready:
      for k in self.cruise_button_timers:
        self.cruise_button_timers[k] = 0
      # BluePilot: Reset initial cruise speed when cruise is disabled
      # This ensures we capture a fresh initial speed when cruise is re-enabled
      self.initial_cruise_speed_kph = 0

    self.is_ready = ready and not button_pressed

  def run(self, CS: car.CarState, CC: car.CarControl, LP_SP: custom.LongitudinalPlanSP, is_metric: bool) -> None:
    self.frame += 1
    if self.CP_SP.pcmCruiseSpeed and not is_bluepilot():
      return

    self.is_metric = is_metric

    self.update_calculations(CS, LP_SP)
    self.update_readiness(CS, CC)

    self.cruise_button = self.update_state_machine()

    self.is_ready_prev = self.is_ready
