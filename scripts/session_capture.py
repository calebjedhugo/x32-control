#!/usr/bin/env python3
"""
Comprehensive session capture for X-32 mixer.

Captures everything needed for a mixing session:
- All channel settings (EQ, dynamics, preamp, routing)
- All bus settings (EQ, dynamics)
- All FX settings and routing
- Meter data for gain staging analysis
- Signal path tracing

Usage:
    python session_capture.py
    python session_capture.py --duration 10
    python session_capture.py --output captures/sunday-worship.json
"""

import argparse
import asyncio
import json
import math
import socket
import struct
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

sys.path.insert(0, str(Path(__file__).parent))

from common import (
    load_config, get_mixer, format_db, get_state_value, reliable_query,
    warmup_connection, ratio_index_to_value, hpf_value_to_hz,
    INACTIVE_THRESHOLD_RAW,
    parse_meter_blob, parse_bus_meter_blob, extract_blob,
)

# On/off queries: with per-address response matching, the 46% misattribution
# rate is eliminated. Retries now only cover UDP packet loss.
ON_OFF_RETRIES = 3
ON_OFF_DELAY = 0.05


async def reliable_on_off_query(mixer, address: str, label: str = "",
                                failures: list = None) -> Optional[int]:
    """Query an on/off parameter with extra retries and warning on failure."""
    val = await reliable_query(mixer, address, retries=ON_OFF_RETRIES, delay=ON_OFF_DELAY,
                               failures=failures)
    if val is None:
        print(f"  WARNING: {label or address} returned None after {ON_OFF_RETRIES} retries — defaulting to OFF (may be wrong)", file=sys.stderr)
        return 0
    return val

# FX type names (index -> name)
# NOTE: Some names may be inaccurate. The X32 FX numbering varies by firmware
# and slot type (insert vs send). Names for types 45-50 are gaps in the official
# list. Verify against mixer display when possible. Types 47 and 50 were
# identified from live sessions but names need confirmation.
FX_TYPE_NAMES = {
    0: "Hall Reverb",
    1: "Ambience",
    2: "Rich Plate",
    3: "Room",
    4: "Chamber",
    5: "Plate",
    6: "Vintage Room",
    7: "Vintage Plate",
    8: "Gated Reverb",
    9: "Reverse Reverb",
    10: "Stereo Delay",
    11: "Precision Limiter",
    12: "3-Tap Delay",
    13: "4-Tap Delay",
    14: "Chorus",
    15: "Flanger",
    16: "Phaser",
    17: "Ultimo Compressor",
    18: "Rotary Speaker",
    19: "Tremolo/Panner",
    20: "Sub Octaver",
    21: "Delay+Chamber",
    22: "Stereo Exciter",
    23: "Flanger+Chamber",
    24: "Delay+Chorus",
    25: "Delay+Flanger",
    26: "Dual Guitar Amp",
    27: "Graphic EQ",
    28: "True EQ",
    29: "Stereo EQ",
    30: "Wave Designer",
    31: "Precision Limiter",
    32: "Combinator",
    33: "Fair Compressor",
    34: "Leisure Compressor",
    35: "Ultra Enhancer",
    36: "Exciter",
    37: "Stereo Imager",
    38: "Edison EX1",
    39: "Sound Maxer",
    40: "Dual Guitar Amp",
    41: "Tube Stage",
    42: "Stereo Pitch",
    43: "Dual Pitch",
    44: "De-Esser",
    47: "Ultimo Compressor",
    50: "Dual Exciter",
}


async def capture_channel_settings(mixer, ch_num: int, failures: list = None) -> Dict:
    """Capture full settings for a single channel."""
    ch_addr = f"/ch/{ch_num:02d}"
    state = mixer.state()

    # Basic info from state
    fader = get_state_value(state, ch_addr, "mix_fader", 0.0)
    fader_db = get_state_value(state, ch_addr, "mix_fader_db", None)

    # Check stereo link status (pairs are 1-2, 3-4, etc.)
    if ch_num % 2 == 1:  # Odd channel - check link with next
        link_addr = f'/config/chlink/{ch_num}-{ch_num+1}'
    else:  # Even channel - check link with previous
        link_addr = f'/config/chlink/{ch_num-1}-{ch_num}'
    stereo_linked = await reliable_on_off_query(mixer, link_addr, label=f"ch{ch_num} stereo link", failures=failures) == 1

    settings = {
        "name": await reliable_query(mixer, f'{ch_addr}/config/name', default="", failures=failures) or "",
        "fader": round(fader, 3),
        "fader_db": f"{fader_db} dB" if fader_db is not None else format_db(fader),
        "mute": get_state_value(state, ch_addr, "mix_on", True) == False,
        "pan": round(val if (val := await reliable_query(mixer, f'{ch_addr}/mix/pan', failures=failures)) is not None else 0.5, 3),
        "stereo_linked": stereo_linked,
    }

    # Preamp (phantom intentionally NOT queried — headamp queries may have side effects)
    hpf_val = await reliable_query(mixer, f'{ch_addr}/preamp/hpf', default=0.0, retries=ON_OFF_RETRIES, delay=ON_OFF_DELAY, failures=failures)
    settings["preamp"] = {
        "gain": round(await reliable_query(mixer, f'{ch_addr}/preamp/trim', default=0.5, failures=failures), 3),
        "hpf_on": await reliable_on_off_query(mixer, f'{ch_addr}/preamp/hpon', f'ch{ch_num:02d} HPF on', failures=failures) == 1,
        "hpf_hz": hpf_value_to_hz(hpf_val) if hpf_val is not None else 20,
    }

    # EQ (omit band details when EQ is off)
    eq_on = await reliable_on_off_query(mixer, f'{ch_addr}/eq/on', f'ch{ch_num:02d} EQ on', failures=failures) == 1
    if eq_on:
        eq_bands = []
        for band in range(1, 5):
            eq_bands.append({
                "band": band,
                "freq": round(await reliable_query(mixer, f'{ch_addr}/eq/{band}/f', default=0.5, failures=failures), 3),
                "gain": round(await reliable_query(mixer, f'{ch_addr}/eq/{band}/g', default=0.5, failures=failures), 3),
                "q": round(await reliable_query(mixer, f'{ch_addr}/eq/{band}/q', default=0.5, failures=failures), 3),
            })
        settings["eq"] = {"on": True, "bands": eq_bands}
    else:
        settings["eq"] = {"on": False}

    # Gate (omit details when off)
    gate_on = await reliable_on_off_query(mixer, f'{ch_addr}/gate/on', f'ch{ch_num:02d} gate on', failures=failures) == 1
    if gate_on:
        settings["gate"] = {
            "on": True,
            "threshold": round(await reliable_query(mixer, f'{ch_addr}/gate/thr', default=0.5, failures=failures), 3),
            "range": round(await reliable_query(mixer, f'{ch_addr}/gate/range', default=0.5, failures=failures), 3),
            "attack": round(await reliable_query(mixer, f'{ch_addr}/gate/attack', default=0.5, failures=failures), 3),
            "release": round(await reliable_query(mixer, f'{ch_addr}/gate/release', default=0.5, failures=failures), 3),
        }
    else:
        settings["gate"] = {"on": False}

    # Compressor (omit details when off)
    comp_on = await reliable_on_off_query(mixer, f'{ch_addr}/dyn/on', f'ch{ch_num:02d} comp on', failures=failures) == 1
    if comp_on:
        comp_ratio_idx = await reliable_query(mixer, f'{ch_addr}/dyn/ratio', default=5, failures=failures)
        settings["compressor"] = {
            "on": True,
            "threshold": round(await reliable_query(mixer, f'{ch_addr}/dyn/thr', default=0.5, failures=failures), 3),
            "ratio": f"{ratio_index_to_value(int(comp_ratio_idx))}:1" if comp_ratio_idx is not None else "3:1",
            "attack": round(await reliable_query(mixer, f'{ch_addr}/dyn/attack', default=0.5, failures=failures), 3),
            "release": round(await reliable_query(mixer, f'{ch_addr}/dyn/release', default=0.5, failures=failures), 3),
            "mix": round(await reliable_query(mixer, f'{ch_addr}/dyn/mix', default=1.0, failures=failures), 3),
            "mgain": round(await reliable_query(mixer, f'{ch_addr}/dyn/mgain', default=0.0, failures=failures), 3),
        }
    else:
        settings["compressor"] = {"on": False}

    # Insert
    insert_on = await reliable_on_off_query(mixer, f'{ch_addr}/insert/on', f'ch{ch_num:02d} insert on', failures=failures) == 1
    insert_sel = await reliable_query(mixer, f'{ch_addr}/insert/sel', default=0, failures=failures)
    # Insert sel maps: 0-1=FX1, 2-3=FX2, 4-5=FX3, 6-7=FX4 (L/R pairs)
    settings["insert"] = {
        "on": insert_on,
        "fx_slot": (int(insert_sel) // 2) + 1 if insert_on and insert_sel is not None else None,
    }

    # Bus sends (routing)
    sends = {}
    for bus_num in range(1, 17):
        level = await reliable_query(mixer, f'{ch_addr}/mix/{bus_num:02d}/level', default=0.0, failures=failures)
        on = await reliable_on_off_query(mixer, f'{ch_addr}/mix/{bus_num:02d}/on', label=f"ch{ch_num} bus{bus_num:02d} send on", failures=failures) == 1
        if on or (level and level > 0.01):
            sends[f"bus{bus_num:02d}"] = {
                "level": round(level, 3) if level else 0.0,
                "level_db": format_db(level) if level else "-inf dB",
                "on": on,
            }
    settings["sends"] = sends

    # Main send
    main_level = get_state_value(state, ch_addr, "mix_fader", 0.0)
    main_on = get_state_value(state, ch_addr, "mix_on", True)
    settings["main_send"] = {
        "level": round(main_level, 3),
        "level_db": format_db(main_level),
        "on": main_on,
    }

    # Routing: does this channel feed main LR?
    st = await reliable_on_off_query(mixer, f'{ch_addr}/mix/st', label=f"ch{ch_num} main LR routing", failures=failures)
    settings["routing"] = {
        "main_lr": int(st) == 1 if st is not None else True,
    }

    # DCA membership (bitmask: bit0=DCA1, bit1=DCA2, etc.)
    dca_bits = await reliable_query(mixer, f'{ch_addr}/grp/dca', default=0, failures=failures)
    if dca_bits is not None and int(dca_bits) > 0:
        settings["dca_groups"] = [i + 1 for i in range(8) if int(dca_bits) & (1 << i)]
    else:
        settings["dca_groups"] = []

    return settings


async def capture_bus_settings(mixer, bus_num: int, failures: list = None) -> Dict:
    """Capture full settings for a single bus."""
    bus_addr = f"/bus/{bus_num:02d}"
    state = mixer.state()

    fader = get_state_value(state, bus_addr, "mix_fader", 0.0)
    fader_db = get_state_value(state, bus_addr, "mix_fader_db", None)

    settings = {
        "name": await reliable_query(mixer, f'{bus_addr}/config/name', default="", failures=failures) or "",
        "fader": round(fader, 3),
        "fader_db": f"{fader_db} dB" if fader_db is not None else format_db(fader),
        "mute": get_state_value(state, bus_addr, "mix_on", True) == False,
    }

    # Bus EQ (6 bands, omit details when off)
    eq_on = await reliable_on_off_query(mixer, f'{bus_addr}/eq/on', f'bus{bus_num:02d} EQ on', failures=failures) == 1
    if eq_on:
        eq_bands = []
        for band in range(1, 7):
            eq_bands.append({
                "band": band,
                "freq": round(await reliable_query(mixer, f'{bus_addr}/eq/{band}/f', default=0.5, failures=failures), 3),
                "gain": round(await reliable_query(mixer, f'{bus_addr}/eq/{band}/g', default=0.5, failures=failures), 3),
                "q": round(await reliable_query(mixer, f'{bus_addr}/eq/{band}/q', default=0.5, failures=failures), 3),
            })
        settings["eq"] = {"on": True, "bands": eq_bands}
    else:
        settings["eq"] = {"on": False}

    # Bus compressor (omit details when off)
    comp_on = await reliable_on_off_query(mixer, f'{bus_addr}/dyn/on', f'bus{bus_num:02d} comp on', failures=failures) == 1
    if comp_on:
        comp_ratio_idx = await reliable_query(mixer, f'{bus_addr}/dyn/ratio', default=5, failures=failures)
        settings["compressor"] = {
            "on": True,
            "threshold": round(await reliable_query(mixer, f'{bus_addr}/dyn/thr', default=0.5, failures=failures), 3),
            "ratio": f"{ratio_index_to_value(int(comp_ratio_idx))}:1" if comp_ratio_idx is not None else "3:1",
            "attack": round(await reliable_query(mixer, f'{bus_addr}/dyn/attack', default=0.5, failures=failures), 3),
            "release": round(await reliable_query(mixer, f'{bus_addr}/dyn/release', default=0.5, failures=failures), 3),
            "mix": round(await reliable_query(mixer, f'{bus_addr}/dyn/mix', default=1.0, failures=failures), 3),
            "mgain": round(await reliable_query(mixer, f'{bus_addr}/dyn/mgain', default=0.0, failures=failures), 3),
        }
    else:
        settings["compressor"] = {"on": False}

    # Bus insert - sel maps: 0-1=FX1, 2-3=FX2, 4-5=FX3, 6-7=FX4 (L/R pairs)
    insert_on = await reliable_on_off_query(mixer, f'{bus_addr}/insert/on', f'bus{bus_num:02d} insert on', failures=failures) == 1
    insert_sel = await reliable_query(mixer, f'{bus_addr}/insert/sel', default=0, failures=failures)
    settings["insert"] = {
        "on": insert_on,
        "fx_slot": (int(insert_sel) // 2) + 1 if insert_on and insert_sel is not None else None,
    }

    # Routing: does this bus feed main LR?
    st = await reliable_on_off_query(mixer, f'{bus_addr}/mix/st', label=f"bus{bus_num:02d} main LR routing", failures=failures)
    settings["routing"] = {
        "main_lr": int(st) == 1 if st is not None else False,
    }

    # Matrix sends from this bus (6 matrices)
    matrix_sends = {}
    for mtx_num in range(1, 7):
        level = await reliable_query(mixer, f'{bus_addr}/mix/{mtx_num:02d}/level', default=0.0, failures=failures)
        on = await reliable_on_off_query(mixer, f'{bus_addr}/mix/{mtx_num:02d}/on', label=f"bus{bus_num:02d} mtx{mtx_num:02d} send on", failures=failures)
        on_val = int(on) == 1
        if on_val or (level is not None and float(level) > 0.01):
            matrix_sends[f"mtx{mtx_num:02d}"] = {
                "level": round(float(level), 3) if level else 0.0,
                "level_db": format_db(float(level)) if level else "-inf dB",
                "on": on_val,
            }
    settings["matrix_sends"] = matrix_sends

    # DCA membership
    dca_bits = await reliable_query(mixer, f'{bus_addr}/grp/dca', default=0, failures=failures)
    if dca_bits is not None and int(dca_bits) > 0:
        settings["dca_groups"] = [i + 1 for i in range(8) if int(dca_bits) & (1 << i)]
    else:
        settings["dca_groups"] = []

    return settings


async def capture_fx_settings(mixer, fx_num: int, failures: list = None) -> Dict:
    """Capture settings for an FX slot."""
    fx_type_idx = await reliable_query(mixer, f'/fx/{fx_num}/type', default=0, failures=failures)
    fx_type_idx = int(fx_type_idx) if fx_type_idx and not (isinstance(fx_type_idx, float) and math.isnan(fx_type_idx)) else 0

    settings = {
        "type_id": fx_type_idx,
        "type_name": FX_TYPE_NAMES.get(fx_type_idx, f"Unknown ({fx_type_idx})"),
        "parameters": {},
    }

    # Get parameters (first 12 are usually the important ones)
    for param_num in range(1, 13):
        value = await reliable_query(mixer, f'/fx/{fx_num}/par/{param_num:02d}', default=None, failures=failures)
        if value is not None:
            settings["parameters"][param_num] = round(value, 3)

    return settings


async def capture_main_settings(mixer, failures: list = None) -> Dict:
    """Capture main LR bus settings."""
    state = mixer.state()
    main_addr = "/main/st"

    fader = get_state_value(state, main_addr, "mix_fader", 0.0)

    settings = {
        "fader": round(fader, 3),
        "fader_db": format_db(fader),
        "mute": get_state_value(state, main_addr, "mix_on", True) == False,
    }

    # Main EQ (6 bands)
    eq_on = await reliable_on_off_query(mixer, '/main/st/eq/on', 'main EQ on', failures=failures) == 1
    eq_bands = []
    for band in range(1, 7):
        eq_bands.append({
            "band": band,
            "freq": round(await reliable_query(mixer, f'/main/st/eq/{band}/f', default=0.5, failures=failures), 3),
            "gain": round(await reliable_query(mixer, f'/main/st/eq/{band}/g', default=0.5, failures=failures), 3),
            "q": round(await reliable_query(mixer, f'/main/st/eq/{band}/q', default=0.5, failures=failures), 3),
        })
    settings["eq"] = {"on": eq_on, "bands": eq_bands}

    # Main compressor
    main_comp_ratio_idx = await reliable_query(mixer, '/main/st/dyn/ratio', default=5, failures=failures)
    settings["compressor"] = {
        "on": await reliable_on_off_query(mixer, '/main/st/dyn/on', 'main comp on', failures=failures) == 1,
        "threshold": round(await reliable_query(mixer, '/main/st/dyn/thr', default=0.5, failures=failures), 3),
        "ratio": f"{ratio_index_to_value(int(main_comp_ratio_idx))}:1" if main_comp_ratio_idx is not None else "3:1",
        "attack": round(await reliable_query(mixer, '/main/st/dyn/attack', default=0.5, failures=failures), 3),
        "release": round(await reliable_query(mixer, '/main/st/dyn/release', default=0.5, failures=failures), 3),
        "mix": round(await reliable_query(mixer, '/main/st/dyn/mix', default=1.0, failures=failures), 3),
        "mgain": round(await reliable_query(mixer, '/main/st/dyn/mgain', default=0.0, failures=failures), 3),
    }

    # Matrix sends from main (6 matrices)
    matrix_sends = {}
    for mtx_num in range(1, 7):
        level = await reliable_query(mixer, f'/main/st/mix/{mtx_num:02d}/level', default=0.0, failures=failures)
        on = await reliable_on_off_query(mixer, f'/main/st/mix/{mtx_num:02d}/on', label=f"main mtx{mtx_num:02d} send on", failures=failures)
        on_val = int(on) == 1
        if on_val or (level is not None and float(level) > 0.01):
            matrix_sends[f"mtx{mtx_num:02d}"] = {
                "level": round(float(level), 3) if level else 0.0,
                "level_db": format_db(float(level)) if level else "-inf dB",
                "on": on_val,
            }
    settings["matrix_sends"] = matrix_sends

    return settings


async def capture_matrix_settings(mixer, mtx_num: int, failures: list = None) -> Dict:
    """Capture full settings for a matrix output."""
    mtx_addr = f"/mtx/{mtx_num:02d}"
    state = mixer.state()

    # Matrix fader from state (direct query is unreliable)
    fader = state.get(f'/mtx/{mtx_num}/mix_fader', 0.0)

    settings = {
        "name": await reliable_query(mixer, f'{mtx_addr}/config/name', default="", failures=failures) or "",
        "fader": round(float(fader), 3) if fader else 0.0,
        "fader_db": format_db(float(fader)) if fader else "-inf dB",
        "mute": state.get(f'/mtx/{mtx_num}/mix_on', True) == False,
    }

    # Matrix EQ (6 bands, omit details when off)
    eq_on = await reliable_on_off_query(mixer, f'{mtx_addr}/eq/on', label=f"mtx{mtx_num} EQ on", failures=failures) == 1
    if eq_on:
        eq_bands = []
        for band in range(1, 7):
            eq_bands.append({
                "band": band,
                "freq": round(await reliable_query(mixer, f'{mtx_addr}/eq/{band}/f', default=0.5, failures=failures), 3),
                "gain": round(await reliable_query(mixer, f'{mtx_addr}/eq/{band}/g', default=0.5, failures=failures), 3),
                "q": round(await reliable_query(mixer, f'{mtx_addr}/eq/{band}/q', default=0.5, failures=failures), 3),
            })
        settings["eq"] = {"on": True, "bands": eq_bands}
    else:
        settings["eq"] = {"on": False}

    # Matrix compressor (omit details when off)
    mtx_comp_on = await reliable_on_off_query(mixer, f'{mtx_addr}/dyn/on', label=f"mtx{mtx_num} comp on", failures=failures) == 1
    if mtx_comp_on:
        mtx_comp_ratio_idx = await reliable_query(mixer, f'{mtx_addr}/dyn/ratio', default=5, failures=failures)
        settings["compressor"] = {
            "on": True,
            "threshold": round(await reliable_query(mixer, f'{mtx_addr}/dyn/thr', default=0.5, failures=failures), 3),
            "ratio": f"{ratio_index_to_value(int(mtx_comp_ratio_idx))}:1" if mtx_comp_ratio_idx is not None else "3:1",
            "attack": round(await reliable_query(mixer, f'{mtx_addr}/dyn/attack', default=0.5, failures=failures), 3),
            "release": round(await reliable_query(mixer, f'{mtx_addr}/dyn/release', default=0.5, failures=failures), 3),
            "mix": round(await reliable_query(mixer, f'{mtx_addr}/dyn/mix', default=1.0, failures=failures), 3),
            "mgain": round(await reliable_query(mixer, f'{mtx_addr}/dyn/mgain', default=0.0, failures=failures), 3),
        }
    else:
        settings["compressor"] = {"on": False}

    # Matrix insert
    insert_on = await reliable_on_off_query(mixer, f'{mtx_addr}/insert/on', label=f"mtx{mtx_num} insert on", failures=failures) == 1
    insert_sel = await reliable_query(mixer, f'{mtx_addr}/insert/sel', default=0, failures=failures)
    settings["insert"] = {
        "on": insert_on,
        "fx_slot": (int(insert_sel) // 2) + 1 if insert_on and insert_sel is not None else None,
    }

    return settings


async def capture_fxrtn_settings(mixer, fxrtn_num: int, failures: list = None) -> Dict:
    """Capture settings for an FX return."""
    fxrtn_addr = f"/fxrtn/{fxrtn_num:02d}"
    state = mixer.state()

    fader = state.get(f'/fxrtn/{fxrtn_num}/mix_fader', 0.0)
    on = state.get(f'/fxrtn/{fxrtn_num}/mix_on', True)

    settings = {
        "name": await reliable_query(mixer, f'{fxrtn_addr}/config/name', default="", failures=failures) or "",
        "fader": round(float(fader), 3) if fader else 0.0,
        "fader_db": format_db(float(fader)) if fader else "-inf dB",
        "mute": on == False if on is not None else False,
    }

    # EQ (4 bands, omit details when off)
    eq_on = await reliable_on_off_query(mixer, f'{fxrtn_addr}/eq/on', label=f"fxrtn{fxrtn_num} EQ on", failures=failures) == 1
    if eq_on:
        eq_bands = []
        for band in range(1, 5):
            eq_bands.append({
                "band": band,
                "freq": round(await reliable_query(mixer, f'{fxrtn_addr}/eq/{band}/f', default=0.5, failures=failures), 3),
                "gain": round(await reliable_query(mixer, f'{fxrtn_addr}/eq/{band}/g', default=0.5, failures=failures), 3),
                "q": round(await reliable_query(mixer, f'{fxrtn_addr}/eq/{band}/q', default=0.5, failures=failures), 3),
            })
        settings["eq"] = {"on": True, "bands": eq_bands}
    else:
        settings["eq"] = {"on": False}

    # Routing: main LR send
    st = await reliable_on_off_query(mixer, f'{fxrtn_addr}/mix/st', label=f"fxrtn{fxrtn_num} main LR routing", failures=failures)
    settings["routing"] = {
        "main_lr": int(st) == 1 if st is not None else True,
    }

    # Bus sends
    sends = {}
    for bus_num in range(1, 17):
        level = await reliable_query(mixer, f'{fxrtn_addr}/mix/{bus_num:02d}/level', default=0.0, failures=failures)
        bus_on = await reliable_on_off_query(mixer, f'{fxrtn_addr}/mix/{bus_num:02d}/on', label=f"fxrtn{fxrtn_num} bus{bus_num:02d} send on", failures=failures) == 1
        if bus_on or (level and level > 0.01):
            sends[f"bus{bus_num:02d}"] = {
                "level": round(level, 3) if level else 0.0,
                "level_db": format_db(level) if level else "-inf dB",
                "on": bus_on,
            }
    settings["sends"] = sends

    return settings


async def capture_dca_settings(mixer, failures: list = None) -> Dict:
    """Capture DCA group settings (faders, names, membership)."""
    state = mixer.state()
    dcas = {}

    for dca_num in range(1, 9):
        name = await reliable_query(mixer, f'/dca/{dca_num}/config/name', default="", failures=failures)
        fader = state.get(f'/dca/{dca_num}/mix_fader', 0.0)
        on = state.get(f'/dca/{dca_num}/mix_on', True)

        dcas[f"dca{dca_num}"] = {
            "name": name or "",
            "fader": round(float(fader), 3) if fader else 0.0,
            "fader_db": format_db(float(fader)) if fader else "-inf dB",
            "mute": on == False if on is not None else False,
        }

    return dcas


async def capture_meters(mixer_ip: str, mixer_port: int, duration: float) -> tuple:
    """Capture meter data for gain staging analysis.

    Uses /meters request-polling (not /batchsubscribe which is unreliable).
    Returns (channel_peaks, bus_peaks).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.1)
    sock.bind(('', 0))

    channel_peaks = {f'ch{i:02d}': 0.0 for i in range(1, 33)}
    bus_peaks = {f'bus{i:02d}': 0.0 for i in range(1, 17)}

    def send_xremote():
        msg = b'/xremote\x00\x00\x00\x00,\x00\x00\x00'
        sock.sendto(msg, (mixer_ip, mixer_port))

    def request_channel_meters():
        # /meters ,siii '/meters/0' 0 0 3
        msg = b'/meters\x00,siii\x00\x00\x00'
        msg += b'/meters/0\x00\x00\x00'
        msg += struct.pack('>iii', 0, 0, 3)
        sock.sendto(msg, (mixer_ip, mixer_port))

    def request_bus_meters():
        # /meters ,siii '/meters/2' 0 0 3
        msg = b'/meters\x00,siii\x00\x00\x00'
        msg += b'/meters/2\x00\x00\x00'
        msg += struct.pack('>iii', 0, 0, 3)
        sock.sendto(msg, (mixer_ip, mixer_port))

    start_time = time.time()
    last_request = 0

    print(f"Capturing meters for {duration}s...", file=sys.stderr)

    try:
        while time.time() - start_time < duration:
            current = time.time()

            if current - last_request > 0.05:
                send_xremote()
                request_channel_meters()
                request_bus_meters()
                last_request = current

            try:
                data, _ = sock.recvfrom(8192)
                if data.startswith(b'/meters/0'):
                    blob_data = extract_blob(data)
                    if blob_data:
                        peaks = parse_meter_blob(blob_data)
                        for ch, val in peaks.items():
                            if val > channel_peaks[ch]:
                                channel_peaks[ch] = val
                elif data.startswith(b'/meters/2'):
                    blob_data = extract_blob(data)
                    if blob_data:
                        peaks = parse_bus_meter_blob(blob_data)
                        for key, val in peaks.items():
                            if key in bus_peaks and val > bus_peaks[key]:
                                bus_peaks[key] = val
            except socket.timeout:
                pass

            await asyncio.sleep(0.001)
    finally:
        sock.close()

    return channel_peaks, bus_peaks


def analyze_gain_staging(channel_peaks: Dict, channel_names: Dict) -> Dict:
    """Analyze gain staging and identify issues."""
    # Filter to active channels only
    active = {ch: peak for ch, peak in channel_peaks.items() if peak > INACTIVE_THRESHOLD_RAW}

    if not active:
        return {"active_channels": [], "issues": [], "average_peak": 0}

    # Calculate average peak of active channels
    avg_peak = sum(active.values()) / len(active)

    issues = []
    for ch, peak in active.items():
        ch_num = int(ch.replace('ch', ''))
        name = channel_names.get(ch, ch)

        ratio = peak / avg_peak if avg_peak > 0 else 1

        if ratio > 2.0:  # More than 2x average
            db_diff = 20 * math.log10(ratio)
            issues.append({
                "channel": ch_num,
                "name": name,
                "peak_raw": peak,
                "issue": "hot",
                "detail": f"Running {db_diff:.0f}dB above average - consider reducing preamp gain",
            })
        elif ratio < 0.3:  # Less than 30% of average
            db_diff = -20 * math.log10(ratio)
            issues.append({
                "channel": ch_num,
                "name": name,
                "peak_raw": peak,
                "issue": "quiet",
                "detail": f"Running {db_diff:.0f}dB below average - may need more preamp gain",
            })

    return {
        "active_channels": sorted([int(ch.replace('ch', '')) for ch in active.keys()]),
        "issues": issues,
        "average_peak": round(avg_peak, 6),
        "channel_peaks": {ch: round(peak, 6) for ch, peak in channel_peaks.items() if peak > 0},
    }



def validate_capture(result: Dict) -> List[str]:
    """Post-capture validation: flag suspicious patterns that suggest query failures.

    Returns list of warning strings.
    """
    warnings = []

    for ch_key, ch_data in result.get("channels", {}).items():
        eq = ch_data.get("eq", {})
        if not eq.get("on"):
            continue
        bands = eq.get("bands", [])
        default_freq_count = 0
        for band in bands:
            freq = band.get("freq", 0.5)
            gain = band.get("gain", 0.5)
            # EQ freq at exactly 0.5 (632Hz) when gain is NOT 0.5 = likely query failure
            # (tuned gain + default freq makes no engineering sense)
            if freq == 0.5 and gain != 0.5:
                name = ch_data.get("name", ch_key)
                warnings.append(
                    f"{ch_key} ({name}) EQ band {band.get('band')}: "
                    f"freq at default 0.5 (632Hz) but gain is {gain:.3f} — possible query failure"
                )
            if freq == 0.5:
                default_freq_count += 1
        # Multiple bands at default freq on same channel is very suspicious
        if default_freq_count >= 3:
            name = ch_data.get("name", ch_key)
            warnings.append(
                f"{ch_key} ({name}): {default_freq_count}/4 EQ bands at default freq (0.5) — likely query failures"
            )

    # Same checks for buses and matrices
    for section_name, section_key in [("buses", "bus"), ("matrices", "mtx")]:
        for item_key, item_data in result.get(section_name, {}).items():
            eq = item_data.get("eq", {})
            if not eq.get("on"):
                continue
            for band in eq.get("bands", []):
                freq = band.get("freq", 0.5)
                gain = band.get("gain", 0.5)
                if freq == 0.5 and gain != 0.5:
                    name = item_data.get("name", item_key)
                    warnings.append(
                        f"{item_key} ({name}) EQ band {band.get('band')}: "
                        f"freq at default 0.5 but gain is {gain:.3f} — possible query failure"
                    )

    return warnings


async def main():
    parser = argparse.ArgumentParser(
        description="Comprehensive session capture for X-32 mixer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Captures everything needed for a mixing session:
- All channel settings (EQ, dynamics, preamp, routing)
- All bus settings (EQ, dynamics, inserts)
- All FX settings and routing
- Meter data for gain staging analysis
- Signal path analysis

Example:
    python session_capture.py --duration 10 --output captures/sunday.json
        """
    )
    parser.add_argument(
        "--duration", "-d",
        type=float,
        default=5,
        help="Meter capture duration in seconds (default: 5)"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path (default: captures/session_TIMESTAMP.json)"
    )
    parser.add_argument(
        "--settings-only",
        action="store_true",
        help="Skip meter collection (use with --meter-data for external meter peaks)"
    )
    parser.add_argument(
        "--meter-data",
        help="Load external meter peaks JSON (from meter_collector.py)"
    )

    args = parser.parse_args()

    if args.meter_data and not args.settings_only:
        print("Warning: --meter-data has no effect without --settings-only", file=sys.stderr)

    config = load_config()

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_path = Path(__file__).parent.parent / "captures" / f"session_{timestamp}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print("Connecting to mixer...", file=sys.stderr)

    try:
        mixer = await get_mixer(config)
    except Exception as e:
        print(f"Error: Cannot connect to mixer at {config['mixer_ip']}", file=sys.stderr)
        print(json.dumps({"success": False, "error": "connection_failed"}))
        sys.exit(1)

    try:
        await warmup_connection(mixer)

        # Background keepalive: send /xremote every 2s to keep the UDP
        # connection "hot". This dramatically improves query reliability
        # (the mixer drops fewer responses on an active connection).
        async def keepalive_loop():
            try:
                while True:
                    await mixer.send('/xremote')
                    await asyncio.sleep(2)
            except asyncio.CancelledError:
                pass

        keepalive_task = asyncio.create_task(keepalive_loop())

        # Shared failures list — tracks all addresses where queries failed
        query_failures = []

        result = {
            "metadata": {
                "capture_time": datetime.now().isoformat(),
                "mixer_ip": config["mixer_ip"],
                "meter_duration": args.duration,
            },
            "channels": {},
            "buses": {},
            "matrices": {},
            "dcas": {},
            "fx": {},
            "fxrtns": {},
            "main": {},
            "analysis": {},
        }

        # Capture all channels
        print("Capturing channel settings...", file=sys.stderr)
        for ch_num in range(1, 33):
            result["channels"][f"ch{ch_num:02d}"] = await capture_channel_settings(mixer, ch_num, failures=query_failures)
            if ch_num % 8 == 0:
                print(f"  Channels 1-{ch_num} done", file=sys.stderr)

        # Fix stereo linked pairs: even (right) channel returns stale/default
        # values for processing settings. Copy from odd (left/master) channel.
        for ch_num in range(1, 32, 2):
            odd_key = f"ch{ch_num:02d}"
            even_key = f"ch{ch_num+1:02d}"
            odd_ch = result["channels"][odd_key]
            even_ch = result["channels"][even_key]
            if odd_ch.get("stereo_linked") and even_ch.get("stereo_linked"):
                for key in ("preamp", "eq", "gate", "compressor", "insert", "sends"):
                    even_ch[key] = odd_ch[key]

        # Known false readback: ch31 (bass) insert/on always returns 0.
        # The Ultimo Compressor (FX1) is confirmed active as a tonal insert.
        if "ch31" in result["channels"]:
            result["channels"]["ch31"]["insert"] = {"on": True, "fx_slot": 1}

        # Capture all buses
        print("Capturing bus settings...", file=sys.stderr)
        for bus_num in range(1, 17):
            result["buses"][f"bus{bus_num:02d}"] = await capture_bus_settings(mixer, bus_num, failures=query_failures)
        print("  Buses 1-16 done", file=sys.stderr)

        # Capture all FX slots
        print("Capturing FX settings...", file=sys.stderr)
        for fx_num in range(1, 9):
            result["fx"][f"fx{fx_num}"] = await capture_fx_settings(mixer, fx_num, failures=query_failures)
        print("  FX 1-8 done", file=sys.stderr)

        # Capture FX returns
        print("Capturing FX return settings...", file=sys.stderr)
        for fxrtn_num in range(1, 9):
            result["fxrtns"][f"fxrtn{fxrtn_num:02d}"] = await capture_fxrtn_settings(mixer, fxrtn_num, failures=query_failures)
        print("  FX returns 1-8 done", file=sys.stderr)

        # Capture main bus
        print("Capturing main bus settings...", file=sys.stderr)
        result["main"] = await capture_main_settings(mixer, failures=query_failures)

        # Capture all matrices
        print("Capturing matrix settings...", file=sys.stderr)
        for mtx_num in range(1, 7):
            result["matrices"][f"mtx{mtx_num:02d}"] = await capture_matrix_settings(mixer, mtx_num, failures=query_failures)
        print("  Matrices 1-6 done", file=sys.stderr)

        # Capture DCA groups
        print("Capturing DCA settings...", file=sys.stderr)
        result["dcas"] = await capture_dca_settings(mixer, failures=query_failures)
        print("  DCAs 1-8 done", file=sys.stderr)

        # Capture meters (channels + buses)
        if args.settings_only and args.meter_data:
            # Load external meter data from meter_collector.py
            print(f"Loading external meter data from {args.meter_data}...", file=sys.stderr)
            with open(args.meter_data) as f:
                meter_data = json.load(f)

            # Use rolling window peaks for gain staging analysis
            channel_peaks = meter_data.get("channel_peaks_window", meter_data.get("channel_peaks", {}))
            bus_peaks = meter_data.get("bus_peaks_window", meter_data.get("bus_peaks", {}))

            # Store full running peaks as headroom reference
            result["metadata"]["headroom_peaks"] = {
                "channel_peaks": meter_data.get("channel_peaks", {}),
                "bus_peaks": meter_data.get("bus_peaks", {}),
            }
            result["metadata"]["meter_duration"] = meter_data.get("duration_seconds", 0)
            result["metadata"]["meter_source"] = "meter_collector"
            result["metadata"]["meter_window_seconds"] = meter_data.get("window_seconds", 60)

            print(f"  Meter data: {meter_data.get('duration_seconds', 0):.0f}s collection, "
                  f"{meter_data.get('window_seconds', 60)}s rolling window", file=sys.stderr)
        elif args.settings_only:
            # Settings only, no meter data at all
            print("Settings-only mode, skipping meter capture", file=sys.stderr)
            channel_peaks = {f'ch{i:02d}': 0.0 for i in range(1, 33)}
            bus_peaks = {f'bus{i:02d}': 0.0 for i in range(1, 17)}
            result["metadata"]["meter_duration"] = 0
            result["metadata"]["meter_source"] = "none"
        else:
            channel_peaks, bus_peaks = await capture_meters(
                config["mixer_ip"], config["mixer_port"], args.duration
            )

        # Build channel name lookup
        channel_names = {
            ch_key: ch_data.get("name", ch_key)
            for ch_key, ch_data in result["channels"].items()
        }

        # Analyze gain staging
        print("Analyzing gain staging...", file=sys.stderr)
        result["analysis"]["gain_staging"] = analyze_gain_staging(channel_peaks, channel_names)

        # Store bus meter peaks (for livestream agent)
        result["analysis"]["bus_peaks"] = {
            bus: round(peak, 6) for bus, peak in bus_peaks.items() if peak > 0
        }

        # Add FX routing summary
        fx_routing = {}
        for fx_key, fx_data in result["fx"].items():
            fx_num = int(fx_key.replace('fx', ''))
            # Find what uses this FX as insert
            used_by = []
            for ch_key, ch_data in result["channels"].items():
                if ch_data.get("insert", {}).get("fx_slot") == fx_num:
                    used_by.append({"type": "channel", "id": ch_key, "name": ch_data.get("name")})
            for bus_key, bus_data in result["buses"].items():
                if bus_data.get("insert", {}).get("fx_slot") == fx_num:
                    used_by.append({"type": "bus", "id": bus_key, "name": bus_data.get("name")})
            for mtx_key, mtx_data in result["matrices"].items():
                if mtx_data.get("insert", {}).get("fx_slot") == fx_num:
                    used_by.append({"type": "matrix", "id": mtx_key, "name": mtx_data.get("name")})

            if used_by or fx_data.get("type_id", 0) != 0:
                fx_routing[fx_key] = {
                    "type": fx_data.get("type_name"),
                    "inserted_on": used_by if used_by else None,
                }
        result["analysis"]["fx_routing"] = fx_routing

        # Query failure tracking — ALWAYS write the key, even when count is 0.
        # An absent key is ambiguous (zero failures? old format? tracking broken?);
        # an explicit count==0 lets consumers reliably gate trust on a capture
        # (e.g. "only auto-apply from captures with query_failures.count == 0").
        result["metadata"]["query_failures"] = {
            "count": len(query_failures),
            "addresses": query_failures,
        }
        if query_failures:
            print(f"\nQuery failures: {len(query_failures)} addresses failed all retries", file=sys.stderr)
            for addr in query_failures[:10]:
                print(f"  {addr}", file=sys.stderr)
            if len(query_failures) > 10:
                print(f"  ... and {len(query_failures) - 10} more", file=sys.stderr)

        # Post-capture validation
        validation_warnings = validate_capture(result)
        if validation_warnings:
            result["metadata"]["validation_warnings"] = validation_warnings
            print(f"\nValidation warnings: {len(validation_warnings)}", file=sys.stderr)
            for w in validation_warnings:
                print(f"  {w}", file=sys.stderr)

        # Write output
        with open(output_path, 'w') as f:
            json.dump(result, f, indent=2)

        # Summary
        active_count = len(result["analysis"]["gain_staging"]["active_channels"])
        issue_count = len(result["analysis"]["gain_staging"]["issues"])

        print(f"\nSession capture complete!", file=sys.stderr)
        print(f"  Active channels: {active_count}", file=sys.stderr)
        print(f"  Gain issues: {issue_count}", file=sys.stderr)
        print(f"  Output: {output_path}", file=sys.stderr)

        # Output JSON summary
        summary = {
            "success": True,
            "path": str(output_path),
            "active_channels": result["analysis"]["gain_staging"]["active_channels"],
            "gain_issues": result["analysis"]["gain_staging"]["issues"],
        }
        print(json.dumps(summary, indent=2))

    finally:
        keepalive_task.cancel()
        try:
            await keepalive_task
        except asyncio.CancelledError:
            pass
        await mixer.stop()


if __name__ == "__main__":
    asyncio.run(main())
