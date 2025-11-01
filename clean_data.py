#!/usr/bin/env python3
"""
Clean git merge conflict markers and duplicates from data files.
"""
import json
import re
import sys
from pathlib import Path


def clean_conflict_markers(content):
    """Remove git conflict markers from text content, handling nested conflicts.
    Keeps the "theirs" version (after the last ======= before >>>>>>>) when resolving conflicts.
    Uses multiple passes and a stack-based approach to handle nested conflicts.
    """
    prev_content = content
    max_iterations = 30
    iteration = 0
    
    while iteration < max_iterations:
        lines = prev_content.split('\n')
        cleaned_lines = []
        i = 0
        
        while i < len(lines):
            line = lines[i]
            
            # Look for conflict start marker
            if re.match(r'^<<<<<<<', line):
                # Found a conflict start, use stack to handle nested conflicts
                conflict_level = 1
                separator_positions = []  # List of (level, position) tuples for ======= markers
                i += 1
                start_pos = i
                
                # Navigate through the conflict block, handling nesting
                while i < len(lines) and conflict_level > 0:
                    current_line = lines[i]
                    
                    if re.match(r'^<<<<<<<', current_line):
                        # Nested conflict starts - increase level
                        conflict_level += 1
                    elif re.match(r'^=======', current_line):
                        # Record separator position with its current conflict level
                        separator_positions.append((conflict_level, i))
                    elif re.match(r'^>>>>>>>', current_line):
                        # Conflict end marker
                        conflict_level -= 1
                        if conflict_level == 0:
                            # This closes our original conflict block
                            # Find the last separator at level 1 (top-level conflict)
                            # If no level 1 separator exists, find the last one at any level
                            last_separator = None
                            
                            # First, try to find separator at level 1
                            for level, pos in reversed(separator_positions):
                                if level == 1:
                                    last_separator = pos
                                    break
                            
                            # If no level 1 separator, use the last separator found
                            if last_separator is None and separator_positions:
                                last_separator = separator_positions[-1][1]
                            
                            # Keep content after the last separator (theirs version)
                            if last_separator is not None:
                                # Include lines from after separator to before end marker
                                for j in range(last_separator + 1, i):
                                    cleaned_lines.append(lines[j])
                            # Skip the conflict markers (start, separators, and end)
                            i += 1
                            break
                    
                    i += 1
                
                # If we exited the loop but conflict_level > 0, it's malformed - skip rest
                if conflict_level > 0:
                    # Malformed conflict block, skip everything until we find more markers
                    while i < len(lines):
                        if re.match(r'^>>>>>>>', lines[i]):
                            i += 1
                            break
                        i += 1
                continue
            elif re.match(r'^=======', line):
                # Standalone separator (orphaned, not part of a conflict block), skip it
                i += 1
                continue
            elif re.match(r'^>>>>>>>', line):
                # Standalone end marker (orphaned), skip it
                i += 1
                continue
            else:
                # Normal line, keep it
                cleaned_lines.append(line)
                i += 1
        
        current_content = '\n'.join(cleaned_lines)
        
        # Check if we made any changes
        if current_content == prev_content:
            break
        
        prev_content = current_content
        iteration += 1
    
    # Final cleanup: remove any remaining conflict markers as a fallback
    # This handles edge cases where markers might have been malformed
    prev_content = re.sub(r'^<<<<<<<.*$', '', prev_content, flags=re.MULTILINE)
    prev_content = re.sub(r'^=======.*$', '', prev_content, flags=re.MULTILINE)
    prev_content = re.sub(r'^>>>>>>>.*$', '', prev_content, flags=re.MULTILINE)
    
    # Clean up extra blank lines
    prev_content = re.sub(r'\n{3,}', '\n\n', prev_content)
    prev_content = prev_content.strip()
    if prev_content and not prev_content.endswith('\n'):
        prev_content += '\n'
    
    return prev_content


def clean_json_file(file_path):
    """Clean and fix JSON file with conflict markers."""
    print(f"Cleaning {file_path}...")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return False
    
    # First, remove conflict markers
    cleaned_content = clean_conflict_markers(content)
    
    # Try to parse JSON
    try:
        data = json.loads(cleaned_content)
    except json.JSONDecodeError as e:
        print(f"JSON parsing error in {file_path}: {e}")
        print("Attempting to fix JSON structure...")
        
        # Try to fix common JSON issues
        # Remove trailing commas
        cleaned_content = re.sub(r',\s*}', '}', cleaned_content)
        cleaned_content = re.sub(r',\s*]', ']', cleaned_content)
        
        # Try parsing again
        try:
            data = json.loads(cleaned_content)
        except json.JSONDecodeError as e2:
            print(f"Failed to fix JSON: {e2}")
            return False
    
    # Remove duplicates (if it's a dict, keep only unique keys with latest values)
    if isinstance(data, dict):
        cleaned_data = {}
        for key, value in data.items():
            # If key already exists, merge values intelligently
            if key in cleaned_data:
                if isinstance(value, dict) and isinstance(cleaned_data[key], dict):
                    # Merge dicts, taking maximum values
                    merged = {}
                    for k in set(list(value.keys()) + list(cleaned_data[key].keys())):
                        if k in value and k in cleaned_data[key]:
                            merged[k] = max(value[k], cleaned_data[key][k], default=value[k])
                        elif k in value:
                            merged[k] = value[k]
                        else:
                            merged[k] = cleaned_data[key][k]
                    cleaned_data[key] = merged
                else:
                    # Keep the later value
                    cleaned_data[key] = value
            else:
                cleaned_data[key] = value
        data = cleaned_data
    
    # Write cleaned data back
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Successfully cleaned {file_path}")
        return True
    except Exception as e:
        print(f"Error writing {file_path}: {e}")
        return False


def clean_text_file(file_path):
    """Clean text file with conflict markers and duplicates."""
    print(f"Cleaning {file_path}...")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return False
    
    # Remove conflict markers
    cleaned_content = clean_conflict_markers(content)
    
    # Remove duplicate lines (preserving order)
    lines = cleaned_content.split('\n')
    seen = set()
    unique_lines = []
    
    for line in lines:
        # Normalize line (strip whitespace for comparison, but keep original)
        line_stripped = line.strip()
        if line_stripped and line_stripped not in seen:
            seen.add(line_stripped)
            unique_lines.append(line)
        elif not line_stripped:
            # Keep empty lines
            unique_lines.append(line)
    
    cleaned_content = '\n'.join(unique_lines)
    
    # Write cleaned content back
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(cleaned_content)
        print(f"Successfully cleaned {file_path}")
        return True
    except Exception as e:
        print(f"Error writing {file_path}: {e}")
        return False


def main():
    """Main function to clean data files."""
    files_to_clean = [
        '.state/check_counts.json',
        'output/all_valid_proxies.txt'
    ]
    
    all_success = True
    for file_path in files_to_clean:
        path = Path(file_path)
        if not path.exists():
            print(f"Warning: {file_path} does not exist, skipping...")
            continue
        
        if file_path.endswith('.json'):
            success = clean_json_file(path)
        else:
            success = clean_text_file(path)
        
        if not success:
            all_success = False
    
    if all_success:
        print("All files cleaned successfully!")
        return 0
    else:
        print("Some files had errors during cleaning.")
        return 1


if __name__ == '__main__':
    sys.exit(main())

