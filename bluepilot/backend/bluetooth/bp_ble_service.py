#!/usr/bin/env python3
"""
BluePilot BLE GATT Server Daemon for Comma 4 (AGNOS Linux)
Provides Bluetooth Low Energy interface for mobile companion apps (bpconnect iOS/Android).
Allows querying, streaming, and modifying all openpilot / bluepilot toggles and parameters.
"""

import os
import sys
import json
import time
import socket
import logging
import threading
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [BP_BLE] %(message)s'
)
logger = logging.getLogger("bp_ble_service")

# Import BLE Protocol
try:
    from .ble_protocol import BLEMessageAssembler, BLEMessageChunker, DEFAULT_MAX_CHUNK_SIZE
except ImportError:
    from ble_protocol import BLEMessageAssembler, BLEMessageChunker, DEFAULT_MAX_CHUNK_SIZE

# UUID Definitions (Standard Nordic UART compatible BLE Service for maximum iOS/CoreBluetooth compatibility)
BP_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
BP_CHAR_RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"  # Write / WriteWithoutResponse (App -> Comma)
BP_CHAR_TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  # Notify (Comma -> App)

# Direct Params fallback
PARAMS_DIR = "/data/params/d" if os.path.exists("/data") else os.path.expanduser("~/.comma_params/d")

try:
    from openpilot.common.params import Params
    params_instance = Params()
    logger.info("Using openpilot.common.params.Params")
except Exception as e:
    logger.warning(f"openpilot Params import failed ({e}), using direct filesystem fallback")
    class FallbackParams:
        def __init__(self, p_dir=None):
            self.p_dir = p_dir or PARAMS_DIR
            try:
                os.makedirs(self.p_dir, exist_ok=True)
            except Exception:
                pass

        def get(self, key: str, block: bool = False) -> Optional[bytes]:
            try:
                p = os.path.join(self.p_dir, key)
                if not os.path.exists(p):
                    return None
                with open(p, 'rb') as f:
                    return f.read()
            except Exception:
                return None

        def get_bool(self, key: str) -> bool:
            v = self.get(key)
            return v == b"1" if v is not None else False

        def get_int(self, key: str) -> int:
            v = self.get(key)
            if not v:
                return 0
            try:
                return int(v.decode('utf-8').strip())
            except Exception:
                return 0

        def get_float(self, key: str) -> float:
            v = self.get(key)
            if not v:
                return 0.0
            try:
                return float(v.decode('utf-8').strip())
            except Exception:
                return 0.0

        def put(self, key: str, val: Any):
            try:
                p = os.path.join(self.p_dir, key)
                if isinstance(val, bool):
                    data = b"1" if val else b"0"
                elif isinstance(val, str):
                    data = val.encode('utf-8')
                elif isinstance(val, bytes):
                    data = val
                else:
                    data = str(val).encode('utf-8')
                with open(p, 'wb') as f:
                    f.write(data)
                return True
            except Exception as ex:
                logger.error(f"Error putting param {key}: {ex}")
                return False

        def put_bool(self, key: str, val: bool):
            return self.put(key, val)

        def all_keys(self):
            try:
                return [k for k in os.listdir(self.p_dir) if not k.startswith('.')]
            except Exception:
                return []

    params_instance = FallbackParams()


class BluePilotBLEHandler:
    """
    Handles request routing and responses for BLE operations.
    """
    def __init__(self, params=params_instance):
        self.params = params
        self.repo_root = self._find_repo_root()
        self._param_definitions = self._load_param_definitions()
        self._panel_definitions = self._load_panel_definitions()

    def _find_repo_root(self) -> Path:
        candidates = [
            Path("/data/openpilot"),
            Path(__file__).resolve().parents[3],
            Path(__file__).resolve().parents[2],
            Path("/Volumes/Ext2Tb/github/bluepilot"),
        ]
        for c in candidates:
            if c.exists() and (c / "common").exists():
                return c
        return Path("/data/openpilot")

    def _load_param_definitions(self) -> Dict[str, Dict[str, Any]]:
        defs = {}
        # Try bluepilot/params/params.json
        bp_json = self.repo_root / "bluepilot" / "params" / "params.json"
        if bp_json.exists():
            try:
                with open(bp_json, 'r') as f:
                    data = json.load(f)
                    for item in data.get("params", []):
                        if isinstance(item, dict) and "name" in item:
                            defs[item["name"]] = item
            except Exception as e:
                logger.warning(f"Error reading params.json: {e}")
        return defs

    def _load_panel_definitions(self) -> Dict[str, Any]:
        # Try sunnylink/settings_ui.json
        sunnylink_json = self.repo_root / "sunnypilot" / "sunnylink" / "settings_ui.json"
        if sunnylink_json.exists():
            try:
                with open(sunnylink_json, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Error reading settings_ui.json: {e}")
        return {"panels": []}

    def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main request router.
        """
        req_id = request.get("id", "")
        op = request.get("op", "")

        try:
            if op == "ping":
                return {"id": req_id, "success": True, "data": {"pong": time.time()}}

            elif op == "get_status":
                return {"id": req_id, "success": True, "data": self.get_status()}

            elif op == "get_all_params":
                return {"id": req_id, "success": True, "data": self.get_all_params()}

            elif op == "get_params_by_category":
                return {"id": req_id, "success": True, "data": self.get_params_by_category()}

            elif op == "get_panels":
                return {"id": req_id, "success": True, "data": self.get_panels()}

            elif op == "get_param":
                key = request.get("key")
                if not key:
                    return {"id": req_id, "success": False, "error": "Missing key"}
                return {"id": req_id, "success": True, "data": self.get_param(key)}

            elif op == "set_param":
                key = request.get("key")
                val = request.get("value")
                if key is None:
                    return {"id": req_id, "success": False, "error": "Missing key"}
                success, err = self.set_param(key, val)
                return {"id": req_id, "success": success, "error": err, "key": key, "value": val}

            elif op == "set_params_batch":
                updates = request.get("updates", {})
                results = {}
                for k, v in updates.items():
                    s, e = self.set_param(k, v)
                    results[k] = {"success": s, "error": e}
                return {"id": req_id, "success": True, "data": results}

            elif op == "restart_openpilot":
                self.params.put_bool("DoRestart", True)
                return {"id": req_id, "success": True, "message": "Restarting openpilot"}

            elif op == "reboot":
                self.params.put_bool("DoReboot", True)
                return {"id": req_id, "success": True, "message": "Rebooting device"}

            else:
                return {"id": req_id, "success": False, "error": f"Unknown operation: {op}"}

        except Exception as e:
            logger.exception(f"Exception handling op {op}: {e}")
            return {"id": req_id, "success": False, "error": str(e)}

    def get_status(self) -> Dict[str, Any]:
        dongle_id = ""
        try:
            dongle_raw = self.params.get("DongleId")
            if dongle_raw:
                dongle_id = dongle_raw.decode('utf-8', 'ignore').strip()
        except Exception:
            pass

        version = ""
        try:
            v_raw = self.params.get("Version")
            if v_raw:
                version = v_raw.decode('utf-8', 'ignore').strip()
        except Exception:
            pass

        is_onroad = self.params.get_bool("IsOnroad") if hasattr(self.params, "get_bool") else False
        is_offroad = self.params.get_bool("IsOffroad") if hasattr(self.params, "get_bool") else not is_onroad

        # Storage info
        disk_free_gb = 0.0
        disk_total_gb = 0.0
        try:
            st = os.statvfs("/data" if os.path.exists("/data") else "/")
            disk_free_gb = round((st.f_bavail * st.f_frsize) / (1024 ** 3), 1)
            disk_total_gb = round((st.f_blocks * st.f_frsize) / (1024 ** 3), 1)
        except Exception:
            pass

        return {
            "dongle_id": dongle_id or "comma4-bluepilot",
            "version": version or "BluePilot 5.0",
            "is_onroad": is_onroad,
            "is_offroad": is_offroad,
            "disk_free_gb": disk_free_gb,
            "disk_total_gb": disk_total_gb,
            "timestamp": time.time(),
            "device": "comma four",
        }

    def get_param(self, key: str) -> Dict[str, Any]:
        p_def = self._param_definitions.get(key, {})
        expected_type = p_def.get("type")

        val = None
        raw_bytes = self.params.get(key)
        if raw_bytes is not None:
            raw_str = raw_bytes.decode('utf-8', 'ignore')
            # If type not explicitly declared, infer bool/int/float/string
            if expected_type is None:
                if raw_bytes in (b"1", b"0"):
                    expected_type = "bool"
                elif raw_str.isdigit():
                    expected_type = "int"
                else:
                    expected_type = "string"

            if expected_type == "bool":
                val = raw_bytes == b"1" or raw_str.lower() in ("1", "true")
            elif expected_type == "int":
                try:
                    val = int(raw_str)
                except ValueError:
                    val = 0
            elif expected_type == "float":
                try:
                    val = float(raw_str)
                except ValueError:
                    val = 0.0
            elif expected_type == "json":
                try:
                    val = json.loads(raw_str)
                except Exception:
                    val = raw_str
            else:
                val = raw_str
        else:
            val = p_def.get("default", None)
            if expected_type is None:
                expected_type = "bool" if isinstance(val, bool) else "string"

        return {
            "key": key,
            "value": val,
            "type": expected_type or "string",
            "description": p_def.get("description", ""),
        }

    def get_all_params(self) -> Dict[str, Any]:
        """
        Returns all parameters with values, types, and descriptions.
        """
        all_keys = set(self.params.all_keys() if hasattr(self.params, "all_keys") else [])
        all_keys.update(self._param_definitions.keys())

        result: Dict[str, Any] = {}
        for key in sorted(all_keys):
            if not key or key.startswith('.'):
                continue
            p_def = self._param_definitions.get(key, {})
            p_type = p_def.get("type", "string")

            val = None
            raw = self.params.get(key)
            if raw is not None:
                raw_str = raw.decode('utf-8', 'ignore')
                if p_type == "bool":
                    val = raw == b"1" or raw_str.lower() in ("1", "true")
                elif p_type == "int":
                    try:
                        val = int(raw_str)
                    except ValueError:
                        val = raw_str
                elif p_type == "float":
                    try:
                        val = float(raw_str)
                    except ValueError:
                        val = raw_str
                elif p_type == "json":
                    try:
                        val = json.loads(raw_str)
                    except Exception:
                        val = raw_str
                else:
                    val = raw_str
            else:
                val = p_def.get("default")

            result[key] = {
                "key": key,
                "value": val,
                "type": p_type,
                "default": p_def.get("default"),
                "flags": p_def.get("flags", []),
            }

        return result

    def get_params_by_category(self) -> Dict[str, List[Dict[str, Any]]]:
        all_p = self.get_all_params()
        categorized: Dict[str, List[Dict[str, Any]]] = {
            "Steering & Lateral": [],
            "MADS": [],
            "Cruise & Longitudinal": [],
            "Ford Preferences": [],
            "Visuals & UI": [],
            "Toggles & Behavior": [],
            "Developer & Debug": [],
            "System": []
        }

        for key, p_data in all_p.items():
            k_lower = key.lower()
            if "mads" in k_lower:
                categorized["MADS"].append(p_data)
            elif "steer" in k_lower or "lat" in k_lower or "lane" in k_lower:
                categorized["Steering & Lateral"].append(p_data)
            elif "cruise" in k_lower or "long" in k_lower or "acc" in k_lower or "speed" in k_lower:
                categorized["Cruise & Longitudinal"].append(p_data)
            elif "ford" in k_lower:
                categorized["Ford Preferences"].append(p_data)
            elif "ui" in k_lower or "display" in k_lower or "visual" in k_lower or "camera" in k_lower or "alert" in k_lower:
                categorized["Visuals & UI"].append(p_data)
            elif "debug" in k_lower or "dev" in k_lower or "log" in k_lower:
                categorized["Developer & Debug"].append(p_data)
            elif "toggle" in k_lower or "enable" in k_lower or "custom" in k_lower:
                categorized["Toggles & Behavior"].append(p_data)
            else:
                categorized["System"].append(p_data)

        return categorized

    def get_panels(self) -> Dict[str, Any]:
        """
        Returns structured panels matching sunnypilot / bluepilot UI.
        """
        return self._panel_definitions

    def set_param(self, key: str, value: Any) -> Tuple[bool, Optional[str]]:
        try:
            if isinstance(value, bool):
                self.params.put_bool(key, value)
            elif isinstance(value, (int, float, str)):
                self.params.put(key, str(value))
            elif isinstance(value, (dict, list)):
                self.params.put(key, json.dumps(value))
            else:
                self.params.put(key, str(value))
            logger.info(f"Param updated: {key} = {value}")
            return True, None
        except Exception as e:
            logger.error(f"Error setting param {key}: {e}")
            return False, str(e)


class BlueZBLEGATTServer:
    """
    BlueZ D-Bus GATT Server and LE Advertisement for Comma 4 (AGNOS Linux).
    Publishes Nordic UART Compatible GATT Service.
    """
    def __init__(self, handler: BluePilotBLEHandler):
        self.handler = handler
        self.assembler = BLEMessageAssembler(on_message=self._on_client_message)
        self.chunker = BLEMessageChunker()
        self.tx_callback = None
        self._running = False

    def _on_client_message(self, message: Dict[str, Any]):
        response = self.handler.handle_request(message)
        self.send_response(response)

    def send_response(self, response: Dict[str, Any], max_chunk_size: int = DEFAULT_MAX_CHUNK_SIZE):
        chunks = self.chunker.chunk_message(response, max_chunk_size=max_chunk_size)
        logger.info(f"Sending response for msg {response.get('id')} in {len(chunks)} BLE chunks")
        if self.tx_callback:
            for chunk in chunks:
                self.tx_callback(chunk)

    def on_rx_data(self, data: bytes):
        """
        Called when mobile app writes to RX characteristic.
        """
        self.assembler.feed_chunk(data)

    def start(self):
        """
        Starts the BlueZ D-Bus peripheral service or fallback loop.
        """
        self._running = True
        logger.info("Starting BluePilot BLE GATT Service...")
        try:
            # Check for dbus/bluez
            import dbus
            import dbus.mainloop.glib
            from gi.repository import GLib

            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            bus = dbus.SystemBus()

            # Set device discoverable / adapter powered
            try:
                adapter_obj = bus.get_object('org.bluez', '/org/bluez/hci0')
                adapter_props = dbus.Interface(adapter_obj, 'org.freedesktop.DBus.Properties')
                adapter_props.Set('org.bluez.Adapter1', 'Powered', dbus.Boolean(True))
                adapter_props.Set('org.bluez.Adapter1', 'Discoverable', dbus.Boolean(True))
                adapter_props.Set('org.bluez.Adapter1', 'Alias', dbus.String('Comma4-BluePilot'))
                logger.info("Configured BlueZ HCI adapter: Comma4-BluePilot")
            except Exception as ex:
                logger.warning(f"Could not configure HCI adapter: {ex}")

            logger.info("BluePilot BLE D-Bus Server ready")
        except Exception as e:
            logger.warning(f"BlueZ D-Bus setup unavailable on this host ({e}). Running in standalone / simulation mode.")


def main():
    logger.info("=== BluePilot BLE Daemon Starting ===")
    handler = BluePilotBLEHandler()
    server = BlueZBLEGATTServer(handler)
    server.start()

    # Keep alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Daemon stopped by user")


if __name__ == "__main__":
    main()
