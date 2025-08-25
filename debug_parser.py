#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Debug script for 1fichier parser filename extraction
"""

import sys
import os
import re
import lxml.html
from pathlib import Path

# Add the backend directory to Python path
backend_path = Path(__file__).parent / 'backend'
sys.path.insert(0, str(backend_path))

from core.parser import FichierParser

def test_filename_extraction():
    """Test filename extraction with sample HTML patterns"""
    parser = FichierParser()
    
    # Test HTML patterns that might be found on 1fichier
    test_cases = [
        # Case 1: Premium table structure with bold filename and italic size
        '''
        <table class="premium">
            <tr>
                <td class="normal">
                    <img src="qr.pl?..." />
                </td>
                <td class="normal">
                    <span style="font-weight:bold">example_file.zip</span><br>
                    <span style="font-size:0.9em;font-style:italic">15.2 GB</span>
                </td>
            </tr>
        </table>
        ''',
        
        # Case 2: Simple table structure
        '''
        <table>
            <tr>
                <td><img src="some_image.png"/></td>
                <td>
                    <span style="font-weight:bold">my_document.pdf</span><br>
                    <span style="font-style:italic">2.5 MB</span>
                </td>
            </tr>
        </table>
        ''',
        
        # Case 3: H1 title with filename
        '''
        <html>
            <head><title>example_movie.mkv - 1fichier.com</title></head>
            <body>
                <h1>example_movie.mkv</h1>
                <div class="content">
                    <p>File size: 15 GB</p>
                </div>
            </body>
        </html>
        ''',
        
        # Case 4: Modern 1fichier structure
        '''
        <div class="ct_warn">
            <h2>important_file.rar</h2>
            <p>Size: 8.5 GB</p>
        </div>
        ''',
    ]
    
    print("=" * 80)
    print("Testing 1fichier Filename Extraction")
    print("=" * 80)
    
    for i, html_content in enumerate(test_cases, 1):
        print(f"\n[TEST CASE {i}]")
        print("-" * 40)
        
        try:
            file_info = parser.extract_file_info(html_content)
            print(f"[OK] Extracted filename: '{file_info['name']}'")
            print(f"[OK] Extracted size: '{file_info['size']}'")
            
            if not file_info['name']:
                print("[WARNING] FILENAME EXTRACTION FAILED!")
                print("Debugging...")
                
                # Try to manually extract what's in the HTML
                doc = lxml.html.fromstring(html_content)
                
                # Check all spans with style attributes
                spans_with_style = doc.xpath('//span[@style]')
                print(f"Found {len(spans_with_style)} spans with style:")
                for span in spans_with_style:
                    style = span.get('style', '')
                    text = (span.text or '').strip()
                    print(f"  Style: '{style}' -> Text: '{text}'")
                
                # Check all text content
                all_text = doc.xpath('//text()')
                potential_filenames = []
                for text in all_text:
                    text = text.strip()
                    if text and '.' in text and len(text) < 200 and len(text) > 3:
                        # Check if it looks like a filename
                        if re.search(r'\w+\.\w{2,5}$', text):
                            potential_filenames.append(text)
                
                print(f"Potential filenames found: {potential_filenames}")
                
        except Exception as e:
            print(f"[ERROR] Error: {e}")
    
    print("\n" + "=" * 80)
    print("Testing parser's filename selectors individually")
    print("=" * 80)
    
    # Test with a simple case
    simple_html = '''
    <table class="premium">
        <tr>
            <td class="normal">
                <span style="font-weight:bold">test_file.zip</span><br>
                <span style="font-size:0.9em;font-style:italic">15.2 GB</span>
            </td>
        </tr>
    </table>
    '''
    
    doc = lxml.html.fromstring(simple_html)
    
    # Test each filename selector
    name_selectors = [
        # Premium table selectors
        '//table[contains(@class, "premium")]//span[contains(@style, "font-weight") and contains(@style, "bold")]/text()',
        '//table[contains(@class, "premium")]//span[@style="font-weight:bold"]/text()',
        '//table[contains(@class, "premium")]//td[contains(@class, "normal")]//span[contains(@style, "bold")]/text()',
        
        # General bold span selectors
        '//table//span[contains(@style, "font-weight:bold") and string-length(text()) > 5]/text()',
        '//table//span[contains(@style, "font-weight") and contains(@style, "bold") and string-length(text()) > 5]/text()',
        
        # Simple selectors
        '//span[contains(@style, "bold")]/text()',
        '//span[@style="font-weight:bold"]/text()',
    ]
    
    print(f"\nTesting with HTML: {simple_html}")
    print("\nTesting filename selectors:")
    for i, selector in enumerate(name_selectors):
        try:
            results = doc.xpath(selector)
            print(f"Selector {i+1}: {selector}")
            print(f"  Results: {results}")
            if results:
                print(f"  [OK] Found: {results[0]}")
            else:
                print(f"  [FAIL] No match")
        except Exception as e:
            print(f"  [ERROR] Error: {e}")
        print()

if __name__ == "__main__":
    test_filename_extraction()