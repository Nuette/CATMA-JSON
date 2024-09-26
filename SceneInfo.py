import json
from bs4 import BeautifulSoup

# Function to extract properties from <fs> elements
def extract_fs_properties(fs_element):
    properties = {}
    for f_element in fs_element.find_all('f'):
        property_name = f_element.get('name')

        # Check if the value is a vRange (which contains multiple characters)
        vRange = f_element.find('vRange')
        if vRange and property_name == 'character_constellation':
            # Extract all characters listed under vRange -> vColl
            characters = [char_element.get_text() for char_element in vRange.find_all('string')]
            properties[property_name] = characters  # Store as a list of characters
        else:
            # Otherwise, just get the string value normally
            property_value = f_element.find('string')
            if property_value:
                properties[property_name] = property_value.get_text()  # Use the value inside <string>
            else:
                properties[property_name] = None  # No value, assign None or a default
    return properties


# Function to extract fs elements and map their xml:id to their type and properties
def extract_fs_mapping_with_properties(soup):
    fs_mapping = {}
    for fs in soup.find_all('fs'):
        xml_id = fs.get('xml:id')
        type_id = fs.get('type')
        properties = extract_fs_properties(fs)  # Extract properties and their values
        if xml_id and type_id:
            fs_mapping[xml_id] = {
                'type': type_id,
                'properties': properties  # Store the properties along with the type
            }
    return fs_mapping


# Function to extract text from a character range in the full text
def extract_text_from_char_range(full_text, char_range):
    try:
        start, end = map(int, char_range.split(','))
        extracted_text = full_text[start:end]
        return extracted_text, start, end  # Also return start and end positions
    except Exception as e:
        print(f"Error extracting text: {e}")
        return None, None, None


# Check if two segments are part of the same scene or non-scene based on properties
def are_segments_similar(segment_a, segment_b, is_scene):
    # Compare relevant properties for scene or non-scene
    if is_scene:
        # For scenes: Compare time, place, and character constellation
        return (segment_a['properties'].get('time') == segment_b['properties'].get('time') and
                segment_a['properties'].get('place') == segment_b['properties'].get('place') and
                segment_a['properties'].get('character_constellation') == segment_b['properties'].get(
                    'character_constellation'))
    else:
        # For non-scenes: Compare summary, scenic passage, and description passage
        return (segment_a['properties'].get('summary') == segment_b['properties'].get('summary') and
                segment_a['properties'].get('scenic_passage') == segment_b['properties'].get('scenic_passage') and
                segment_a['properties'].get('description_passage') == segment_b['properties'].get(
                    'description_passage'))


# Function to parse the TEI XML and group scenes/non-scenes based on properties
def parse_updated_scene_structure(soup, fs_mapping, full_text):
    segments_data = []
    merged_segment = None  # To store the currently merged segment
    previous_scene_segment = None  # To track the last intradiegetic scene for grouping sub-scenes
    previous_subscene_segment = None  # To track the last sub-scene for merging

    # Extract the segments and group based on scene/non-scene tags and diegetic level
    segments = soup.find_all('seg')

    # Process each segment
    for segment in segments:
        ana_tags = segment.get('ana').split()  # Extract the 'ana' tags (CATMA codes)
        char_range = segment.find('ptr').get('target').split('#char=')[-1]

        scene_type = None
        diegetic_level = None
        metadiegetic_level = None
        properties = {}

        for tag_code in ana_tags:
            # Lookup the fs element from the mapping based on the tag
            fs_entry = fs_mapping.get(tag_code.strip("#"), {})
            fs_type = fs_entry.get('type')
            fs_properties = fs_entry.get('properties', {})

            # If it's a diegetic level
            if 'Intradiegetic' in fs_properties:
                diegetic_level = fs_properties.get('Intradiegetic')
            if 'Metadiegetic' in fs_properties:
                metadiegetic_level = fs_properties.get('Metadiegetic')  # Track metadiegetic for sub-scenes

            # Check for scene or non-scene
            if fs_type == 'CATMA_205FC926-99D8-429F-92B1-EA89734F1F84':
                scene_type = 'non-scene'
            elif fs_type == 'CATMA_BF670197-D11B-4CE4-A940-00BF8C83A753':
                scene_type = 'scene'

            # Handle character constellation
            if 'character_constellation' in fs_properties:
                properties['character_constellation'] = fs_properties.get('character_constellation', [])

            properties.update(fs_properties)

        # Extract the text and start/end positions from the full text using the char range
        segment_text, start, end = extract_text_from_char_range(full_text, char_range)

        # Create the current segment with all properties
        current_segment = {
            'text': segment_text,
            'start': start,
            'end': end,
            'scene_type': scene_type,
            'properties': properties  # Keep properties for internal logic
        }

        # Handle sub-scenes: If the segment has a Metadiegetic level, it should be grouped under the previous scene
        if metadiegetic_level:
            # Merge consecutive sub-scenes with the same properties
            if previous_subscene_segment and are_segments_similar(previous_subscene_segment, current_segment,
                                                                  is_scene=True):
                previous_subscene_segment['text'] += ' ' + current_segment['text']
                previous_subscene_segment['end'] = current_segment['end']  # Update end position
            else:
                # Add the current sub-scene to the parent scene
                previous_scene_segment.setdefault('linked_sub_scene', []).append(current_segment)
                previous_subscene_segment = current_segment  # Track this as the current sub-scene
        else:
            # Grouping scenes or non-scenes based on their relevant properties
            if scene_type == 'scene':
                if merged_segment and are_segments_similar(merged_segment, current_segment, is_scene=True):
                    merged_segment['text'] += ' ' + current_segment['text']
                    merged_segment['end'] = current_segment['end']  # Update end position
                else:
                    if merged_segment:
                        segments_data.append(merged_segment)
                    merged_segment = current_segment
            else:  # Non-scene
                if merged_segment and are_segments_similar(merged_segment, current_segment, is_scene=False):
                    merged_segment['text'] += ' ' + current_segment['text']
                    merged_segment['end'] = current_segment['end']  # Update end position
                else:
                    if merged_segment:
                        segments_data.append(merged_segment)
                    merged_segment = current_segment

        # Track the last intradiegetic scene for sub-scene linking
        if scene_type == 'scene' and not metadiegetic_level:
            previous_scene_segment = merged_segment
            previous_subscene_segment = None  # Reset sub-scene tracking when we switch to a new scene

    # Append the last merged segment
    if merged_segment:
        segments_data.append(merged_segment)

    return segments_data


# Function to save the merged segments data to a JSON file
def save_segments_to_json(segments_data, output_file_path):
    # Remove the 'properties' from each segment before saving
    final_segments = []
    for segment in segments_data:
        final_segment = {
            'start': segment['start'],
            'end': segment['end'],
            'scene_type': segment['scene_type'],
            'text': segment['text']
        }
        final_segments.append(final_segment)

    with open(output_file_path, 'w') as json_file:
        json.dump(final_segments, json_file, indent=4)


# Load the XML content
with open('The_adventures_of_the_Italian_nobleman_mystery_annotations.xml', 'r') as file:
    xml_content = file.read()

soup = BeautifulSoup(xml_content, 'lxml-xml')  # Parse using lxml-xml

# Load the full text file (which contains the narrative)
with open('The_adventures_of_the_Italian_nobleman.txt', 'r') as text_file:
    full_text = text_file.read()

# Extract the fs mapping to link the IDs in the body section to their types and properties
fs_mapping = extract_fs_mapping_with_properties(soup)

# Extract the segments, merging consecutive segments with the same diegetic level and scene/non-scene info
merged_segments_by_scene = parse_updated_scene_structure(soup, fs_mapping, full_text)

# Save the segments data to a JSON file
output_file_path = 'scene_info.json'
save_segments_to_json(merged_segments_by_scene, output_file_path)
