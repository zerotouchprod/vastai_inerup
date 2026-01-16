#!/usr/bin/env python3
"""
Emergency debug patch for raft.py to show FULL error message
"""
import sys
from pathlib import Path

raft_py = Path("/opt/ProPainter/RAFT/raft.py")

if not raft_py.exists():
    print(f"❌ {raft_py} not found!")
    sys.exit(1)

content = raft_py.read_text()

# Find line ~109-111 with corr_fn = CorrBlock
old_code = """        if self.args.alternate_corr:
            corr_fn = AlternateCorrBlock(fmap1, fmap2, radius=self.args.corr_radius)
        else:
            corr_fn = CorrBlock(fmap1, fmap2, radius=self.args.corr_radius)"""

new_code = """        # DEBUG WRAPPER - Show full error
        try:
            if self.args.alternate_corr:
                corr_fn = AlternateCorrBlock(fmap1, fmap2, radius=self.args.corr_radius)
            else:
                corr_fn = CorrBlock(fmap1, fmap2, radius=self.args.corr_radius)
        except Exception as e:
            import traceback
            print(f"\\n\\n❌ FATAL: CorrBlock creation failed!", file=sys.stderr)
            print(f"Error type: {type(e).__name__}", file=sys.stderr)
            print(f"Error message: {str(e)}", file=sys.stderr)
            print(f"fmap1 shape: {fmap1.shape if hasattr(fmap1, 'shape') else 'N/A'}", file=sys.stderr)
            print(f"fmap2 shape: {fmap2.shape if hasattr(fmap2, 'shape') else 'N/A'}", file=sys.stderr)
            print(f"radius: {self.args.corr_radius}", file=sys.stderr)
            print(f"\\nFull traceback:", file=sys.stderr)
            traceback.print_exc()
            raise"""

if old_code in content:
    content = content.replace(old_code, new_code)
    raft_py.write_text(content)
    print("✅ Added debug wrapper to raft.py")
    print("   Next run will show FULL error message!")
else:
    print("⚠️  Could not find exact code pattern to patch")
    print("   Trying alternate approach...")
    
    # Try to find just the CorrBlock line
    if "corr_fn = CorrBlock(fmap1, fmap2, radius=self.args.corr_radius)" in content:
        # Wrap just this line
        content = content.replace(
            "            corr_fn = CorrBlock(fmap1, fmap2, radius=self.args.corr_radius)",
            """            try:
                corr_fn = CorrBlock(fmap1, fmap2, radius=self.args.corr_radius)
            except Exception as e:
                import traceback
                print(f"\\n\\n❌ FATAL: CorrBlock failed! {type(e).__name__}: {str(e)}", file=sys.stderr)
                traceback.print_exc()
                raise"""
        )
        raft_py.write_text(content)
        print("✅ Added minimal debug wrapper")
    else:
        print("❌ Could not find CorrBlock line to patch!")
        sys.exit(1)

