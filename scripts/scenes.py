#!/usr/bin/env python3
"""
X-32 scene management.

Usage:
    python scenes.py --list
    python scenes.py --current
    python scenes.py --load 5
    python scenes.py --load "Sunday Service"
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from common import load_config, get_mixer


async def list_scenes(mixer):
    """
    List all available scenes.

    Args:
        mixer: Connected mixer instance

    Returns:
        List of scene dictionaries
    """
    state = mixer.state()
    scenes = []

    # X32 has 100 scene slots (0-99)
    for scene_num in range(100):
        try:
            # Try to get scene name
            scene_name = state.get(f"/-snap/{scene_num:03d}/name", "")
            if scene_name:
                scenes.append({
                    "number": scene_num,
                    "name": scene_name
                })
        except:
            pass

    return scenes


async def get_current_scene(mixer):
    """
    Get current scene.

    Args:
        mixer: Connected mixer instance

    Returns:
        Current scene dictionary
    """
    state = mixer.state()

    try:
        scene_num = state.get("/-snap/index", 0)
        scene_name = state.get(f"/-snap/{scene_num:03d}/name", "")

        return {
            "number": scene_num,
            "name": scene_name
        }
    except Exception as e:
        return {"error": str(e)}


async def load_scene(mixer, scene_identifier):
    """
    Load a scene by number or name.

    Args:
        mixer: Connected mixer instance
        scene_identifier: Scene number or partial name match

    Returns:
        Success status
    """
    # Try as number first
    try:
        scene_num = int(scene_identifier)
        await mixer.load_scene(scene_num)
        print(f"Loaded scene {scene_num}", file=sys.stderr)
        return True
    except ValueError:
        pass

    # Try as name match
    scenes = await list_scenes(mixer)
    matching_scenes = [
        s for s in scenes
        if scene_identifier.lower() in s["name"].lower()
    ]

    if not matching_scenes:
        print(f"Error: No scene found matching '{scene_identifier}'", file=sys.stderr)
        return False

    if len(matching_scenes) > 1:
        print(f"Error: Multiple scenes match '{scene_identifier}':", file=sys.stderr)
        for s in matching_scenes:
            print(f"  {s['number']}: {s['name']}", file=sys.stderr)
        return False

    # Load the matching scene
    scene = matching_scenes[0]
    await mixer.load_scene(scene["number"])
    print(f"Loaded scene {scene['number']}: {scene['name']}", file=sys.stderr)
    return True


async def main():
    parser = argparse.ArgumentParser(description="X-32 scene management")
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all available scenes"
    )
    parser.add_argument(
        "--current",
        action="store_true",
        help="Show current scene"
    )
    parser.add_argument(
        "--load",
        help="Load scene by number or name"
    )
    parser.add_argument(
        "--format", "-f",
        choices=["json", "table"],
        default="table",
        help="Output format for --list (default: table)"
    )

    args = parser.parse_args()

    # Validate arguments
    if not any([args.list, args.current, args.load]):
        parser.error("Must specify --list, --current, or --load")

    # Connect to mixer
    print(f"Connecting to mixer...", file=sys.stderr)
    mixer = await get_mixer()

    try:
        # List scenes
        if args.list:
            scenes = await list_scenes(mixer)

            if args.format == "json":
                print(json.dumps(scenes, indent=2))
            else:
                print(f"{'#':<5} {'Name':<30}")
                print("-" * 35)
                for scene in scenes:
                    print(f"{scene['number']:<5} {scene['name']:<30}")

        # Current scene
        elif args.current:
            scene = await get_current_scene(mixer)
            print(json.dumps(scene, indent=2))

        # Load scene
        elif args.load:
            success = await load_scene(mixer, args.load)
            if success:
                print("Success")
            else:
                sys.exit(1)

    finally:
        await mixer.stop()


if __name__ == "__main__":
    asyncio.run(main())
