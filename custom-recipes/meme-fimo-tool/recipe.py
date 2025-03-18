import dataiku
import os
import shutil
import subprocess
import concurrent.futures
import tempfile
import logging
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
fimo_exec = get_recipe_config().get('fimo_exec_path', "/usr/local/meme/bin/fimo")
fimo_options = get_recipe_config().get('fimo_options', {})

logger.info(f"FIMO options: {fimo_options}")

# Input and Output folder handling
def get_folder(role_name, role_type='input'):
    try:
        folder_name = get_input_names_for_role(role_name)[0] if role_type == 'input' else get_output_names_for_role(role_name)[0]
        folder = dataiku.Folder(folder_name)
        folder_info = folder.get_info()
        logger.info(f"{role_name} folder info: {folder_info}")
        return folder
    except Exception as e:
        logger.error(f"Failed to get {role_name} folder info: {e}")
        raise RuntimeError(f"Unable to access the {role_name} folder.")

fasta_folder = get_folder('input_fasta')
streme_folder = get_folder('input_streme')
fimo_folder = get_folder('fimo_output', role_type='output')

# Get current sample partition ID
partition_id = next((dataiku.dku_flow_variables[key] for key in dataiku.dku_flow_variables if "DKU_DST_" in key), None)
if not partition_id:
    logger.error("Partition ID not found in flow variables")
    raise ValueError("Partition ID not found in flow variables")
logger.info(f"Partition ID (Partition): {partition_id}")

# Create a temporary directory
tmp_dir_name = tempfile.mkdtemp()
logger.info(f"Created temporary directory: {tmp_dir_name}")

# Function to copy files from folders to a temporary directory
def copy_files_to_temp(folder, partition_id=None):
    try:
        for file_name in folder.list_paths_in_partition(partition_id):
            local_file_path = os.path.join(tmp_dir_name, file_name.lstrip('/'))
            os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
            with folder.get_download_stream(file_name) as f_remote, open(local_file_path, 'wb') as f_local:
                shutil.copyfileobj(f_remote, f_local)
                logger.debug(f"Copied {file_name} to {local_file_path}")
                
        logger.info(f"Copied from {folder.short_name} to {tmp_dir_name}")
    except Exception as e:
        logger.error(f"Error while copying files from {folder}: {e}")
        shutil.rmtree(tmp_dir_name)
        raise RuntimeError("Failed to copy files to temporary directory.")

# Copy files from streme and fasta folders
copy_files_to_temp(streme_folder, partition_id)
copy_files_to_temp(fasta_folder)

logger.info("Fasta and Streme files copied to temporary directory")

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
def build_fimo_command(fimo_exec, output_dir, streme_file, fasta_file, options_dict):
    fimo_command = [fimo_exec]
    for key, value in options_dict.items():
        if value.lower() == 'true':
            fimo_command.append(f"--{key}")
        elif value.lower() != 'false':
            fimo_command.extend([f"--{key}", str(value)])
    fimo_command.extend([f'--oc', output_dir, streme_file, fasta_file])
    return fimo_command

# Function to apply FIMO tool
def apply_fimo(streme_file, fasta_file, output_dir, fimo_exec, streme_options):
    fimo_command = build_fimo_command(fimo_exec, output_dir, streme_file, fasta_file, streme_options)
    logger.info(f"Running FIMO for {streme_file} and {fasta_file} with output_dir {output_dir}")

    try:
        fimo_process = subprocess.run(
            fimo_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True  # Raise an error if the command fails
        )
        logger.info(f"FIMO succeeded for {streme_file} and {fasta_file}")
        logger.debug(f"FIMO output: {fimo_process.stdout.decode()}")
    except subprocess.CalledProcessError as e:
        logger.error(f"FIMO failed for {streme_file} and {fasta_file}")
        logger.debug(f"FIMO error output: {e.stderr.decode()}")
        raise RuntimeError(f"FIMO execution failed for {streme_file} and {fasta_file}")

# Function to gather files from subdirectories
def gather_files(tmp_dir_name):
    subfolders = {}
    
    for root, dirs, files in os.walk(tmp_dir_name):
        streme_file = None
        fasta_file = None

        for file_name in files:
            if file_name == 'streme.txt':
                streme_file = os.path.join(root, file_name)
            elif file_name.endswith('.fasta'):
                fasta_file = os.path.join(root, file_name)
        if fasta_file:
            subfolders[root] = (streme_file, fasta_file)
    
    logger.debug(f"Gathered subfolders with streme and fasta files: {subfolders}")
    return subfolders

# Function to process each subfolder and apply FIMO tool between files concurrently
def process_folders_fimo(tmp_dir_name, max_workers, fimo_exec, streme_options):
    subfolders = gather_files(tmp_dir_name)
    logger.debug(f"Processing subfolders: {subfolders}")
    
    tasks = []
    exceptions = []

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        for subfolder1, (streme_file, _) in subfolders.items():
            if streme_file:
                for subfolder2, (_, fasta_file) in subfolders.items():
                    if subfolder1 != subfolder2 and fasta_file:
                        fasta_file_name = os.path.basename(fasta_file)
                        fasta_file_base_name = os.path.splitext(fasta_file_name)[0]
                        output_dir = os.path.join(subfolder1, fasta_file_base_name)

                        tasks.append(executor.submit(apply_fimo, streme_file, fasta_file, output_dir, fimo_exec, streme_options))
                        logger.info(f"Task submitted for streme_file: {streme_file}, fasta_file: {fasta_file} with output_dir {output_dir}")
                    else:
                        logger.debug(f"Skipping pairing for subfolder {subfolder1} and {subfolder2} due to conditions.")
            else:
                logger.debug(f"No valid streme_file in subfolder: {subfolder1}. Skipping task submission.")

        for future in concurrent.futures.as_completed(tasks):
            try:
                future.result()
            except Exception as e:
                logger.error(f"Task failed with exception: {e}")
                exceptions.append(e)

    if exceptions:
        # Aggregate all exceptions into a single exception and raise it
        combined_message = "FIMO processing failed with the following errors:\n" + "\n".join(str(e) for e in exceptions)
        logger.error(combined_message)
        raise RuntimeError(combined_message)
# Usage
process_folders_fimo(tmp_dir_name, max_workers=max_workers, fimo_exec=fimo_exec, streme_options=fimo_options)

# List the directory structure after processing
list_directory_contents(tmp_dir_name)

# Clean up the previous result
try:
    fimo_folder.clear_partition(partition_id)
    logger.info(f"Previous results under {partition_id} removed")
except Exception as e:
    logger.error(f"Failed to clear partition {partition_id}: {e}")
    raise RuntimeError(f"Failed to clear previous results for partition {partition_id}")

# Upload the results to the output folder
def upload_results(tmp_dir_name, output_folder):
    try:
        for root, dirs, file_names in os.walk(tmp_dir_name):
            for file_name in file_names:
                if not file_name.endswith('.fasta'):
                    file_path = os.path.join(root, file_name)
                    relative_subfolder = os.path.relpath(root, tmp_dir_name)
                    output_path = f"/{relative_subfolder}/{file_name}"
                    output_folder.upload_file(output_path, file_path)
                    logger.debug(f"Uploaded {file_path} to FIMO folder under {relative_subfolder}")
        logger.info(f"Uploaded from {tmp_dir_name} to FIMO folder")
    except Exception as e:
        logger.error(f"Failed to upload files: {e}")
        raise RuntimeError("Failed to upload files to FIMO folder")

upload_results(tmp_dir_name, fimo_folder)

# Clean up the temporary directory
try:
    shutil.rmtree(tmp_dir_name)
    logger.info(f"Temporary directory {tmp_dir_name} removed")
except Exception as e:
    logger.error(f"Failed to remove temporary directory {tmp_dir_name}: {e}")
    raise RuntimeError("Failed to remove temporary directory")