import sys
sys.path.insert(0, 'src')
try:
    from src.services.streaming_cleaner_service import StreamingSubtitleRemoverService
    service = StreamingSubtitleRemoverService(use_gpu=False)
    print("Service instantiated")
    print(f"Has process? {hasattr(service, 'process')}")
    print(f"Has strategy? {hasattr(service, 'strategy')}")
    print(f"Strategy type: {type(service.strategy).__name__}")
    print("Success")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
