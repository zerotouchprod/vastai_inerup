import sys
sys.path.insert(0, 'src')
from src.infrastructure.processors.subtitle.propainter_wrapper import SubtitleRemoverProPainterWrapper

if __name__ == '__main__':
    print('Testing ProPainter availability...')
    available = SubtitleRemoverProPainterWrapper.is_available()
    print(f'Available: {available}')
    if available:
        print('ProPainter integration should work.')
    else:
        print('ProPainter integration failed.')
        sys.exit(1)
