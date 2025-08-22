#!/usr/bin/env python3
"""
Test script to verify TTS and subtitle generation functionality.
This script tests the core functionality without requiring SQS access.
"""

import os
import tempfile
import logging
from main import TTSProcessor

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_tts_generation():
    """Test TTS audio generation."""
    try:
        processor = TTSProcessor()
        
        # Test text
        test_text = "Hello, this is a test of the TTS system. It should generate audio and subtitles."
        
        # Create temporary output directory
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = os.path.join(temp_dir, "test_audio.wav")
            
            # Test TTS generation
            logger.info("Testing TTS generation...")
            result_path = processor.generate_tts_audio(test_text, audio_path)
            
            if os.path.exists(result_path):
                file_size = os.path.getsize(result_path)
                logger.info(f"✓ TTS generation successful! File size: {file_size} bytes")
                return True
            else:
                logger.error("✗ TTS generation failed - file not created")
                return False
                
    except Exception as e:
        logger.error(f"✗ TTS generation test failed: {e}")
        return False

def test_subtitle_generation():
    """Test subtitle generation."""
    try:
        processor = TTSProcessor()
        
        # Test text
        test_text = "This is a test sentence for subtitle generation."
        
        # Create temporary files
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = os.path.join(temp_dir, "test_audio.wav")
            subtitle_path = os.path.join(temp_dir, "test_subtitles.srt")
            
            # First generate a test audio file
            processor.generate_tts_audio(test_text, audio_path)
            
            # Test subtitle generation
            logger.info("Testing subtitle generation...")
            result_path = processor.generate_subtitles(test_text, audio_path, subtitle_path)
            
            if os.path.exists(result_path):
                file_size = os.path.getsize(result_path)
                logger.info(f"✓ Subtitle generation successful! File size: {file_size} bytes")
                
                # Read and display subtitle content
                with open(result_path, 'r') as f:
                    content = f.read()
                    logger.info(f"Subtitle content preview:\n{content[:200]}...")
                
                return True
            else:
                logger.error("✗ Subtitle generation failed - file not created")
                return False
                
    except Exception as e:
        logger.error(f"✗ Subtitle generation test failed: {e}")
        return False

def main():
    """Run all tests."""
    logger.info("Starting TTS and subtitle generation tests...")
    
    # Test TTS generation
    tts_success = test_tts_generation()
    
    # Test subtitle generation
    subtitle_success = test_subtitle_generation()
    
    # Summary
    logger.info("\n" + "="*50)
    logger.info("TEST RESULTS SUMMARY")
    logger.info("="*50)
    logger.info(f"TTS Generation: {'✓ PASSED' if tts_success else '✗ FAILED'}")
    logger.info(f"Subtitle Generation: {'✓ PASSED' if subtitle_success else '✗ FAILED'}")
    
    if tts_success and subtitle_success:
        logger.info("\n🎉 All tests passed! Your setup is working correctly.")
        return 0
    else:
        logger.error("\n❌ Some tests failed. Please check the error messages above.")
        return 1

if __name__ == "__main__":
    exit(main())
