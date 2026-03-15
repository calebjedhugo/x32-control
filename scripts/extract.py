#!/usr/bin/env python3
"""
Extract targeted data from a session capture for specific agent scopes.

Each scope returns only what that agent needs — compact enough to read in one shot.

Usage:
    python extract.py --scope metering-vocals captures/session_XXX.json
    python extract.py --scope metering-drums captures/session_XXX.json
    python extract.py --scope metering-instruments captures/session_XXX.json
    python extract.py --scope eq captures/session_XXX.json
    python extract.py --scope eq --channels 1,2,3,5 captures/session_XXX.json
    python extract.py --scope editor captures/session_XXX.json
    python extract.py --scope livestream captures/session_XXX.json
"""

import argparse
import json
import sys
from pathlib import Path


def get_active_channels(capture):
    """Get list of active channel numbers from capture analysis."""
    return capture.get("analysis", {}).get("gain_staging", {}).get("active_channels", [])


def get_meter_peaks(capture):
    """Build channel meter peak lookup from gain staging analysis."""
    gain_staging = capture.get("analysis", {}).get("gain_staging", {})
    issues = gain_staging.get("issues", [])
    avg = gain_staging.get("average_peak", 0)
    channel_peaks = gain_staging.get("channel_peaks", {})
    return {
        "average_peak": avg,
        "issues": {i["channel"]: i for i in issues},
        "channel_peaks": channel_peaks,
    }


def get_relevant_dcas(capture, channel_nums):
    """Get DCA settings for DCAs that affect the given channels."""
    dcas = {}
    for ch_num in channel_nums:
        ch_key = f"ch{ch_num:02d}"
        ch_data = capture.get("channels", {}).get(ch_key, {})
        for dca_num in ch_data.get("dca_groups", []):
            dca_key = f"dca{dca_num}"
            if dca_key not in dcas and dca_key in capture.get("dcas", {}):
                dcas[dca_key] = capture["dcas"][dca_key]
    return dcas


def extract_metering(capture, scope_channels):
    """Extract preamp + dynamics for specified channels.

    For metering agents: gain staging, gate, compressor settings.
    """
    active = get_active_channels(capture)
    meter_info = get_meter_peaks(capture)

    result = {
        "average_meter_peak": meter_info["average_peak"],
        "dcas": get_relevant_dcas(capture, scope_channels),
        "channels": {},
    }

    for ch_num in scope_channels:
        ch_key = f"ch{ch_num:02d}"
        ch_data = capture.get("channels", {}).get(ch_key, {})
        if not ch_data:
            continue

        ch_extract = {
            "name": ch_data.get("name", ""),
            "active": ch_num in active,
            "fader": ch_data.get("fader"),
            "fader_db": ch_data.get("fader_db"),
            "mute": ch_data.get("mute"),
            "preamp": ch_data.get("preamp", {}),
            "gate": ch_data.get("gate", {}),
            "compressor": ch_data.get("compressor", {}),
            "dca_groups": ch_data.get("dca_groups", []),
        }

        # Add reverb sends (bus 15 AudVerb, bus 16 CamVerb) for metering agents
        all_sends = ch_data.get("sends", {})
        reverb_sends = {}
        for bus_key in ("bus15", "bus16"):
            if bus_key in all_sends:
                reverb_sends[bus_key] = all_sends[bus_key]
        if reverb_sends:
            ch_extract["sends"] = reverb_sends

        # Add channel insert info (needed for FX insert evaluation)
        insert_data = ch_data.get("insert", {})
        if insert_data and insert_data.get("on"):
            ch_extract["insert"] = insert_data

        # Add meter peak for this channel (needed for compressor threshold evaluation)
        ch_peak_key = f"ch{ch_num:02d}"
        if ch_peak_key in meter_info["channel_peaks"]:
            ch_extract["meter_peak"] = meter_info["channel_peaks"][ch_peak_key]

        # Add gain staging issue if flagged
        issue = meter_info["issues"].get(ch_num)
        if issue:
            ch_extract["meter_issue"] = issue.get("issue")
            ch_extract["meter_detail"] = issue.get("detail")

        result["channels"][ch_key] = ch_extract

    # Include FX data for slots that are inserted on channels in this scope
    fx_routing = capture.get("analysis", {}).get("fx_routing", {})
    for fx_key, fx_data in capture.get("fx", {}).items():
        routing = fx_routing.get(fx_key, {})
        inserted_on = routing.get("inserted_on") or []
        for target in inserted_on:
            if target.get("type") == "channel":
                ch_id = target.get("id", "")
                ch_num_str = ch_id.replace("ch", "")
                try:
                    if int(ch_num_str) in scope_channels:
                        if "fx" not in result:
                            result["fx"] = {}
                        params = fx_data.get("parameters", {})
                        clean_params = {k: v for k, v in params.items()
                                        if v is not None and (not isinstance(v, float) or v == v)}
                        result["fx"][fx_key] = {
                            "type_name": fx_data.get("type_name", ""),
                            "parameters": clean_params,
                            "inserted_on": target,
                        }
                except ValueError:
                    pass

    return result


def extract_eq(capture, scope_channels=None):
    """Extract EQ + HPF + FX tone for active channels, buses, main, matrices.

    For the EQ agent: everything timbral across the full signal path.
    If scope_channels is provided, only those channels are included (buses/main/matrices/FX still included).
    """
    active = get_active_channels(capture)
    if scope_channels is not None:
        # Only include active channels that are also in the requested scope
        active = [ch for ch in active if ch in scope_channels]

    result = {
        "channels": {},
        "buses": {},
        "main": {},
        "matrices": {},
        "fx": {},
    }

    # Active channels: EQ + HPF + insert info
    for ch_num in active:
        ch_key = f"ch{ch_num:02d}"
        ch_data = capture.get("channels", {}).get(ch_key, {})
        if not ch_data:
            continue
        ch_extract = {
            "name": ch_data.get("name", ""),
            "eq": ch_data.get("eq", {}),
            "preamp": {
                "hpf_on": ch_data.get("preamp", {}).get("hpf_on"),
                "hpf_hz": ch_data.get("preamp", {}).get("hpf_hz"),
            },
            "insert": ch_data.get("insert", {}),
        }
        # Include RTA data if available (spliced in by splice_rta.py)
        rta = ch_data.get("rta_analysis")
        if rta:
            ch_extract["rta_analysis"] = rta
        result["channels"][ch_key] = ch_extract

    # All buses: just EQ + name
    for bus_key, bus_data in capture.get("buses", {}).items():
        result["buses"][bus_key] = {
            "name": bus_data.get("name", ""),
            "eq": bus_data.get("eq", {}),
        }

    # Main bus EQ
    main_data = capture.get("main", {})
    result["main"] = {"eq": main_data.get("eq", {})}

    # Matrix EQ
    for mtx_key, mtx_data in capture.get("matrices", {}).items():
        result["matrices"][mtx_key] = {
            "name": mtx_data.get("name", ""),
            "eq": mtx_data.get("eq", {}),
        }

    # FX settings with routing info
    fx_routing = capture.get("analysis", {}).get("fx_routing", {})
    for fx_key, fx_data in capture.get("fx", {}).items():
        # Only include FX slots that are actually in use
        routing = fx_routing.get(fx_key, {})
        if routing or fx_data.get("type_id", 0) != 0:
            params = fx_data.get("parameters", {})
            # Strip NaN values
            clean_params = {k: v for k, v in params.items()
                           if v is not None and (not isinstance(v, float) or v == v)}
            result["fx"][fx_key] = {
                "type_name": fx_data.get("type_name", ""),
                "parameters": clean_params,
                "inserted_on": routing.get("inserted_on"),
            }

    return result


def extract_editor(capture):
    """Extract overview for the editor: active channels, routing, bus/main summary.

    For the editor agent: enough to deconflict, check routing, and apply changes.
    """
    active = get_active_channels(capture)

    result = {
        "active_channels": active,
        "gain_issues": capture.get("analysis", {}).get("gain_staging", {}).get("issues", []),
        "channels": {},
        "buses": {},
        "main": {},
        "matrices": {},
        "dcas": capture.get("dcas", {}),
        "fx_routing": capture.get("analysis", {}).get("fx_routing", {}),
    }

    # Active channels: faders, routing, sends, pan, insert
    for ch_num in active:
        ch_key = f"ch{ch_num:02d}"
        ch_data = capture.get("channels", {}).get(ch_key, {})
        if not ch_data:
            continue
        result["channels"][ch_key] = {
            "name": ch_data.get("name", ""),
            "fader": ch_data.get("fader"),
            "fader_db": ch_data.get("fader_db"),
            "mute": ch_data.get("mute"),
            "pan": ch_data.get("pan"),
            "routing": ch_data.get("routing", {}),
            "dca_groups": ch_data.get("dca_groups", []),
            "sends": ch_data.get("sends", {}),
            "insert": ch_data.get("insert", {}),
        }

    # Buses: fader, routing, matrix sends, insert
    for bus_key, bus_data in capture.get("buses", {}).items():
        result["buses"][bus_key] = {
            "name": bus_data.get("name", ""),
            "fader": bus_data.get("fader"),
            "fader_db": bus_data.get("fader_db"),
            "mute": bus_data.get("mute"),
            "routing": bus_data.get("routing", {}),
            "insert": bus_data.get("insert", {}),
            "matrix_sends": bus_data.get("matrix_sends", {}),
        }

    # Main: fader + matrix sends
    main_data = capture.get("main", {})
    result["main"] = {
        "fader": main_data.get("fader"),
        "fader_db": main_data.get("fader_db"),
        "mute": main_data.get("mute"),
        "matrix_sends": main_data.get("matrix_sends", {}),
    }

    # Matrices: fader + compressor (for livestream level checks)
    for mtx_key, mtx_data in capture.get("matrices", {}).items():
        result["matrices"][mtx_key] = {
            "name": mtx_data.get("name", ""),
            "fader": mtx_data.get("fader"),
            "fader_db": mtx_data.get("fader_db"),
            "mute": mtx_data.get("mute"),
            "compressor": {"on": mtx_data.get("compressor", {}).get("on", False)},
        }

    return result


def extract_livestream(capture):
    """Extract livestream signal path: bus->matrix sends, matrix settings, FX returns.

    For livestream optimization: what feeds the Cam L/R matrices and at what levels.
    """
    bus_peaks = capture.get("analysis", {}).get("bus_peaks", {})

    result = {
        "buses": {},
        "main": {},
        "matrices": {},
        "fxrtns": {},
    }

    # Buses that have matrix sends
    for bus_key, bus_data in capture.get("buses", {}).items():
        mtx_sends = bus_data.get("matrix_sends", {})
        if mtx_sends:
            bus_extract = {
                "name": bus_data.get("name", ""),
                "fader": bus_data.get("fader"),
                "fader_db": bus_data.get("fader_db"),
                "mute": bus_data.get("mute"),
                "compressor": bus_data.get("compressor", {}),
                "matrix_sends": mtx_sends,
            }
            # Include bus meter peak if available (from /meters/2 capture)
            if bus_key in bus_peaks:
                bus_extract["meter_peak"] = bus_peaks[bus_key]
            result["buses"][bus_key] = bus_extract

    # Main -> matrix sends
    main_data = capture.get("main", {})
    result["main"] = {
        "fader": main_data.get("fader"),
        "fader_db": main_data.get("fader_db"),
        "matrix_sends": main_data.get("matrix_sends", {}),
    }

    # Full matrix settings (EQ, comp, fader)
    result["matrices"] = capture.get("matrices", {})

    # FX returns with active sends
    for fxrtn_key, fxrtn_data in capture.get("fxrtns", {}).items():
        sends = fxrtn_data.get("sends", {})
        if sends:
            result["fxrtns"][fxrtn_key] = {
                "name": fxrtn_data.get("name", ""),
                "fader": fxrtn_data.get("fader"),
                "fader_db": fxrtn_data.get("fader_db"),
                "sends": sends,
            }

    return result


def extract_dynamics(capture):
    """Extract compressor/dynamics settings for buses, main, and matrices.

    For the bus dynamics agent: evaluate and tune group/master compression.
    """
    result = {
        "buses": {},
        "main": {},
        "matrices": {},
    }

    for bus_key, bus_data in capture.get("buses", {}).items():
        result["buses"][bus_key] = {
            "name": bus_data.get("name", ""),
            "fader": bus_data.get("fader"),
            "fader_db": bus_data.get("fader_db"),
            "compressor": bus_data.get("compressor", {}),
        }

    main_data = capture.get("main", {})
    result["main"] = {
        "fader": main_data.get("fader"),
        "fader_db": main_data.get("fader_db"),
        "compressor": main_data.get("compressor", {}),
    }

    for mtx_key, mtx_data in capture.get("matrices", {}).items():
        result["matrices"][mtx_key] = {
            "name": mtx_data.get("name", ""),
            "fader": mtx_data.get("fader"),
            "fader_db": mtx_data.get("fader_db"),
            "compressor": mtx_data.get("compressor", {}),
        }

    return result


SCOPE_HANDLERS = {
    'metering': None,  # Requires --channels; handled in main()
    'eq': extract_eq,
    'editor': extract_editor,
    'dynamics': extract_dynamics,
    'livestream': extract_livestream,
}


def main():
    parser = argparse.ArgumentParser(
        description="Extract targeted data from a session capture for agent scopes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Scopes:
  metering              Preamp + dynamics for specified channels (requires --channels)
  eq                    EQ + HPF + FX tone for active channels + buses + main + matrices (--channels filters channels)
  editor                Overview: active channels, routing, bus/main faders, DCA, FX routing
  dynamics              Bus/main/matrix compressor settings
  livestream            Bus->matrix sends, matrix settings, FX returns

Examples:
    python extract.py --scope metering --channels 1,2,3,5,7 captures/session_XXX.json
    python extract.py --scope eq captures/session_XXX.json
    python extract.py --scope eq --channels 1,2,3,5,7 captures/session_XXX.json
        """
    )
    parser.add_argument(
        "--scope", "-s",
        required=True,
        choices=list(SCOPE_HANDLERS.keys()),
        help="What data to extract"
    )
    parser.add_argument(
        "--channels", "-c",
        help="Comma-separated channel list (e.g., 1,2,3,5,7). "
             "Required for --scope metering. Optional for --scope eq to filter channels."
    )
    parser.add_argument(
        "capture_file",
        nargs="?",
        help="Path to session capture JSON (default: latest in captures/)"
    )

    args = parser.parse_args()

    # Validate --channels for metering scope
    if args.scope == 'metering' and not args.channels:
        print("Error: --scope metering requires --channels (e.g., --channels 1,2,3,5,7)", file=sys.stderr)
        sys.exit(1)

    # Find capture file
    if args.capture_file:
        capture_path = Path(args.capture_file)
    else:
        captures_dir = Path(__file__).parent.parent / "captures"
        session_files = list(captures_dir.glob("session_*.json"))
        if not session_files:
            print("Error: No session captures found", file=sys.stderr)
            sys.exit(1)
        capture_path = max(session_files, key=lambda f: f.stat().st_mtime)
        print(f"Using latest capture: {capture_path.name}", file=sys.stderr)

    if not capture_path.exists():
        print(f"Error: File not found: {capture_path}", file=sys.stderr)
        sys.exit(1)

    # Load and extract
    with open(capture_path) as f:
        capture = json.load(f)

    # Parse --channels if provided
    channel_list = None
    if args.channels:
        channel_list = [int(c.strip()) for c in args.channels.split(',')]

    # Dispatch to scope handler
    if args.scope == 'metering':
        if not channel_list:
            print("Error: --scope metering requires --channels", file=sys.stderr)
            sys.exit(1)
        result = extract_metering(capture, channel_list)
    elif args.scope == 'eq':
        result = extract_eq(capture, scope_channels=channel_list)
    else:
        handler = SCOPE_HANDLERS[args.scope]
        result = handler(capture)

    # Output compact JSON
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
