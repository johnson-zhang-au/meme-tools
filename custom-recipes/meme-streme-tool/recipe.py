import dataiku
import os
import shutil
import subprocess
import concurrent.futures
from pathlib import Path
import tempfile
import logging
# Import the helpers for custom recipes
from dataiku.customrecipe import get_input_names_for_role, get_output_names_for_role, get_recipe_config

# Set up logging
logging_level = get_recipe_config().get('logging_level', "INFO")

# Map string levels to logging constants
level_mapping = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL
}

level = level_mapping.get(logging_level, logging.INFO)  # Default to INFO if not found

logging.basicConfig(level=level, format='%(asctime)s - %(levelname)s - %(message)s')

# Set up the logger with the script name
script_name = os.path.basename(__file__).split('.')[0]
logger = logging.getLogger(script_name)
logger.setLevel(level) 


# Suppress DEBUG messages from urllib3
logging.getLogger('urllib3').setLevel(logging.INFO)

# Suppress DEBUG messages from specific urllib3 submodules
logging.getLogger('urllib3.connectionpool').setLevel(logging.INFO)

# Process roles and parameters
max_workers = int(get_recipe_config().get('max_workers', 1))
streme_exec = get_recipe_config().get('streme_exec_path', "/usr/local/meme/bin/streme")
streme_options = get_recipe_config().get('streme_options')

logger.info(f"STREME options: {streme_options}")

# Input and Output folder
input_fasta = get_input_names_for_role('input_fasta')[0]
fasta_folder = dataiku.Folder(input_fasta)
try:
    fasta_info = fasta_folder.get_info()
    logger.info(f"Input folder info: {fasta_info}")
except Exception as e:
    logger.error(f"Failed to get input folder info: {e}")
    raise RuntimeError("Unable to access the input folder.")

streme_output = get_output_names_for_role('streme_output')[0]
streme_folder = dataiku.Folder(streme_output)

# Get current sample partition ID
partition_id = next((dataiku.dku_flow_variables[key] for key in dataiku.dku_flow_variables if "DKU_DST_" in key), None)
if not partition_id:
    logger.error("Partition ID not found in flow variables")
    raise ValueError("Partition ID not found in flow variables")
logger.info(f"Partition ID (Partition): {partition_id}")

# Create temporary directory
try:
    tmp_dir_name = tempfile.mkdtemp()
    logger.info(f"Created temporary directory: {tmp_dir_name}")
except Exception as e:
    logger.error(f"Failed to create temporary directory: {e}")
    raise OSError("Could not create temporary directory.")

# Copy files from the remote folder to the local temp directory
for file_name in fasta_folder.list_paths_in_partition(partition_id):
    local_file_path = os.path.join(tmp_dir_name, file_name.lstrip('/'))
    os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
    
    try:
        with fasta_folder.get_download_stream(file_name) as f_remote, open(local_file_path, 'wb') as f_local:
            shutil.copyfileobj(f_remote, f_local)
            logger.debug(f"Copied file {file_name} to {local_file_path}")
        logger.info(f"Copied files from {input_fasta} to {tmp_dir_name}")
    except Exception as e:
        logger.error(f"Error copying file {file_name}: {e}")
        raise IOError(f"Failed to copy file {file_name}")

# List the contents of the temp directory
def list_directory_contents(directory):
    try:
        result = subprocess.run(['ls', '-lR', directory], capture_output=True, text=True, check=True)
        logger.debug(f"Directory contents:\n{result.stdout}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to list directory contents: {e}")
        raise RuntimeError("Failed to list contents of the temporary directory.")

list_directory_contents(tmp_dir_name)        
        

# Command builder function
def build_streme_command(streme_exec, output_dir, file_path, options_dict):
    streme_command = [streme_exec]
    for key, value in options_dict.items():
        if value.lower() == 'true':
            streme_command.append(f"--{key}")
        elif value.lower() != 'false':
            streme_command.extend([f"--{key}", str(value)])
    streme_command.extend([f"--oc", str(output_dir), f"--p", str(file_path)])
    return streme_command

# Function to apply the STREME tool
def apply_streme(file_path, streme_exec, streme_options):
    # output_dir = os.path.dirname(file_path)
    
    file_name = os.path.basename(file_path)
    parent_folder = os.path.basename(os.path.dirname(file_path))


    file_name_no_ext = os.path.splitext(file_name)[0]

    if file_name_no_ext != parent_folder:
        # Create a subfolder inside the parent folder
        output_dir = os.path.join(os.path.dirname(file_path), file_name_no_ext)
        os.makedirs(output_dir, exist_ok=True)
    else:
        # If the file name matches the parent folder name, keep output_dir as the parent folder
        output_dir = os.path.dirname(file_path)
    
    streme_command = build_streme_command(streme_exec, output_dir, file_path, streme_options)

    logger.info(f"Processing {file_path} with STREME command: {streme_command}")
    try:
        streme_process = subprocess.run(streme_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        logger.info(f"STREME succeeded for {file_path}")
        logger.debug(f"STREME output:\n{streme_process.stdout.decode()}")
    except subprocess.CalledProcessError as e:
        logger.error(f"STREME failed for {file_path}: {e.stderr.decode()}")
        raise RuntimeError(f"STREME execution failed for {file_path}")

# Process files in parallel using ProcessPoolExecutor
def process_directory_streme(tmp_dir_name, max_workers, streme_exec, streme_options):
    files = [os.path.join(root, file_name) for root, _, file_names in os.walk(tmp_dir_name) for file_name in file_names if file_name.endswith('.fasta')]
    logger.info(f"Processing {len(files)} files with STREME")
    
    tasks = []

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        tasks = {}
        for file in files:
            logger.info(f"Submitting STREME task for file: {file}")
            tasks[executor.submit(apply_streme, file, streme_exec, streme_options)] = file
            
        for future in concurrent.futures.as_completed(tasks):
            try:
                future.result()
            except Exception as e:
                logger.error(f"Task failed for {futures[future]}: {e}")
                raise RuntimeError(f"Task failed for {futures[future]}: {e}")

# Process the files in the directory
process_directory_streme(tmp_dir_name, max_workers, streme_exec, streme_options)

# List the directory structure after processing
list_directory_contents(tmp_dir_name)

# Clear previous results in output folder
try:
    streme_folder.clear_partition(partition_id)
    logger.info(f"Cleared previous results for partition {partition_id}")
except Exception as e:
    logger.error(f"Failed to clear partition {partition_id}: {e}")
    raise RuntimeError(f"Unable to clear partition {partition_id}")

# Upload processed files back to the Dataiku folder
for root, _, file_names in os.walk(tmp_dir_name):
    for file_name in file_names:
        if not file_name.endswith('.fasta'):
            file_path = os.path.join(root, file_name)
            #relative_subfolder = os.path.basename(root)
            relative_subfolder = os.path.relpath(root, tmp_dir_name)
            try:
                streme_folder.upload_file(f"/{relative_subfolder}/{file_name}", file_path)
                logger.debug(f"Uploaded file: {file_path} to folder: {relative_subfolder}")
            except Exception as e:
                logger.error(f"Failed to upload file {file_path}: {e}")
                raise IOError(f"Error uploading file {file_path} to folder")
logger.debug(f"Uploaded file from {tmp_dir_name} to folder: {streme_output}")
                
# Clean up the temp directory
try:
    shutil.rmtree(tmp_dir_name)
    logger.info(f"Removed temporary directory: {tmp_dir_name}")
except Exception as e:
    logger.error(f"Failed to remove temporary directory: {e}")
    raise OSError("Failed to remove temporary directory.")