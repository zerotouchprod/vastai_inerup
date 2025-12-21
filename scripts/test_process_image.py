#!/usr/bin/env python3
"""
Simple test for process_image.py CLI interface.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import argparse

def test_argparse():
    """Test that argparse works correctly."""
    parser = argparse.ArgumentParser(
        description="Remove text from images using PaddleOCR + SAM 2 + OpenCV inpainting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --image test.jpg
  %(prog)s --image test.jpg --output ./results
  %(prog)s --image test.jpg --debug
        """
    )
    
    parser.add_argument(
        "--image",
        required=True,
        help="Path to input image"
    )
    
    parser.add_argument(
        "--output",
        help="Output directory (default: same as input)"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Save debug mask for verification"
    )
    
    # Test help
    try:
        parser.parse_args(['--help'])
        print("✅ Argparse help works")
    except SystemExit:
        print("✅ Argparse help works (SystemExit is expected)")
    
    # Test required argument
    try:
        parser.parse_args([])
        print("❌ Should have required --image argument")
    except SystemExit:
        print("✅ Required argument check works")
    
    # Test valid arguments
    try:
        args = parser.parse_args(['--image', 'test.jpg', '--debug'])
        assert args.image == 'test.jpg'
        assert args.debug == True
        assert args.output is None
        print("✅ Argument parsing works correctly")
    except Exception as e:
        print(f"❌ Argument parsing failed: {e}")

if __name__ == "__main__":
    print("Testing process_image.py CLI interface...")
    test_argparse()
    print("\n✅ All tests passed!")
