from dataiku.exporter import Exporter

class FastaExporter(Exporter):
    """
    This exporter will output the data in FASTA format
    """

    def __init__(self, config, plugin_config):
        """
        Initialize the exporter with the plugin config and user config.
        """
        self.config = config
        self.plugin_config = plugin_config
        self.id_column = config.get('id_column', 'ID')
        self.sequence_column = config.get('sequence_column', 'Sequence')
        self.comment_column = config.get('comment_column', None)
        self.f = None

    def open_to_file(self, schema, destination_file_path):
        """
        Open the file for writing in FASTA format.
        """
        self.f = open(destination_file_path, 'w')
        # Map column names to their indices for quick access
        self.column_indices = {col['name']: idx for idx, col in enumerate(schema['columns'])}


    def write_row(self, row):
        """
        Write one row of the dataset in FASTA format.
        - The FASTA format requires each entry to begin with a '>'
        followed by the identifier, then the optional comment, 
        and finally the sequence itself on the next line.
        """
        # Extract indices of columns
        id_idx = self.column_indices[self.id_column]
        sequence_idx = self.column_indices[self.sequence_column]
        comment_idx = self.column_indices.get(self.comment_column, None) if self.config.get('comment_column') != "None" else None

        # Extract values from the row
        id_value = row[id_idx]
        sequence_value = row[sequence_idx]
        comment_value = row[comment_idx] if comment_idx is not None else ""

        # Write the FASTA formatted entry
        fasta_entry = f">{id_value} {comment_value}\n{sequence_value}\n"
        self.f.write(fasta_entry)

    def close(self):
        """
        Close the file after finishing writing all the rows.
        """
        if self.f:
            self.f.close()