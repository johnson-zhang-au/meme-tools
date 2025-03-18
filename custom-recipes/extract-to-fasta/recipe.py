# Import the helpers for custom recipes
from dataiku.customrecipe import get_input_names_for_role, get_output_names_for_role, get_recipe_config
import dataiku
import pandas as pd
import logging
import os

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
# Set up logging
logging.basicConfig(level=level, format='%(asctime)s - %(levelname)s - %(message)s')

# Set up the logger with the script name
script_name = os.path.basename(__file__).split('.')[0]
logger = logging.getLogger(script_name)
logger.setLevel(level) 


# Suppress DEBUG messages from urllib3
logging.getLogger('urllib3').setLevel(logging.INFO)

# Suppress DEBUG messages from specific urllib3 submodules
logging.getLogger('urllib3.connectionpool').setLevel(logging.INFO)

# Get input dataset
input_dataset_name = get_input_names_for_role('input_dataset')[0]
input_dataset = dataiku.Dataset(input_dataset_name)
logger.info(f"Input dataset: {input_dataset_name}")

# Read recipe inputs as a DataFrame, if the input dataset is partitioned, then here we will only get the selected partition data.
try:
    input_dataset_df = input_dataset.get_dataframe()
    logger.info(f"Input dataset shape: {input_dataset_df.shape}")
except Exception as e:
    logger.error(f"Error reading input dataset: {e}")
    raise

# Get output folder
logger.info(f"Output folders: {get_output_names_for_role('fasta_output')}")
fasta_output = get_output_names_for_role('fasta_output')[0]
fasta_output_folder = dataiku.Folder(fasta_output)
logger.info(f"Output folder: {fasta_output_folder.get_info()}")

# Get recipe config
sequence_id_column_name = get_recipe_config().get('id_column')
sequence_column_name = get_recipe_config().get('sequence_column')
if not sequence_id_column_name or not sequence_column_name:
    logger.error("Missing id_column or sequence_column in recipe config")
    raise ValueError("id_column and sequence_column must be set in the recipe configuration")

logger.info(f"ID column: {sequence_id_column_name}, Sequence column: {sequence_column_name}")

# Get the current partition ID
partition_id = next((dataiku.dku_flow_variables[key] for key in dataiku.dku_flow_variables if "DKU_DST_" in key), None)
if not partition_id:
    logger.error("Partition_id not found in flow variables")
    raise ValueError("Partition_id not found in flow variables")
logger.info(f"Partition ID: {partition_id}")


# Clear existing partition files
try:
    fasta_output_folder.clear_partition(partition_id)
    logger.info(f"Cleared partition: {partition_id}")
except Exception as e:
    logger.error(f"Error clearing partition: {e}")
    raise RuntimeError(f"Error clearing partition: {e}")

# Get the output path for the FASTA file
partition_root_path = fasta_output_folder.get_partition_folder(partition_id)

# Ensure the necessary columns are present in the input DataFrame
if sequence_column_name not in input_dataset_df.columns or sequence_id_column_name not in input_dataset_df.columns:
    logger.error("Input DataFrame does not contain the required columns")
    raise KeyError(f"Columns {sequence_id_column_name} or {sequence_column_name} missing")

def to_fasta(df, id_column, sequence_column):
    """Convert a DataFrame to FASTA format using vectorized operations."""
    headers = df[id_column].apply(lambda x: f">{x}").values
    sequences = df[sequence_column].values
    return "\n".join(f"{header}\n{sequence}" for header, sequence in zip(headers, sequences))

def process_fasta_and_write(df, fasta_output_folder, path_upload_file, sequence_id_column_name, sequence_column_name, sample_id=None):
    """Helper function to convert DataFrame to FASTA and write to output folder."""
    
    # Convert the DataFrame to FASTA and handle errors
    try:
        fasta_data = to_fasta(df, sequence_id_column_name, sequence_column_name)
        logger.debug(f"dataframe : {df}")
        logger.info(f"FASTA data prepared for sample_id: {sample_id}" if sample_id else "FASTA data prepared for full dataset")
    except Exception as e:
        error_msg = f"Error generating FASTA data for sample_id {sample_id}: {e}" if sample_id else f"Error generating FASTA data: {e}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    # Write the FASTA data to the output folder
    try:
        with fasta_output_folder.get_writer(path_upload_file) as writer:
            writer.write(fasta_data.encode('utf-8'))
        logger.info(f"FASTA file written to: {path_upload_file}")
    except Exception as e:
        error_msg = f"Error writing FASTA file for sample_id {sample_id}: {e}" if sample_id else f"Error writing FASTA file: {e}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)


# Main logic
if 'sample_id' in input_dataset_df.columns:
    # Iterate over unique sample IDs and apply the FASTA conversion for each
    for sample_id in input_dataset_df['sample_id'].unique():
        # Filter the DataFrame for the current sample_id
        logger.info(f"processing sample_id: {sample_id}")
        sample_df = input_dataset_df[input_dataset_df['sample_id'] == sample_id]
        
        # Generate the path for the FASTA file
        path_upload_file = f"{partition_root_path}/{sample_id}/{sample_id}.fasta"
        
        # Call the helper function to process and write FASTA
        process_fasta_and_write(sample_df, fasta_output_folder, path_upload_file, sequence_id_column_name, sequence_column_name, sample_id)
else:
    # Apply the code to the entire DataFrame (no sample_id filtering, parition_id is the sample_id)
    path_upload_file = f"{partition_root_path}/{partition_id}.fasta"
    
    # Call the helper function to process and write FASTA
    process_fasta_and_write(input_dataset_df, fasta_output_folder, path_upload_file, sequence_id_column_name, sequence_column_name)
