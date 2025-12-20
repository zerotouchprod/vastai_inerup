import sys
sys.path.insert(0, 'src')
try:
    from src.services.streaming_cleaner_service import StreamingSubtitleRemoverService
    print("Import succeeded")
except Exception as e:
    print(f"Import failed: {e}")
    import traceback
    traceback.print_exc()
