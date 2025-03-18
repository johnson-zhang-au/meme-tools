from dataiku.customformat import Formatter, OutputFormatter, FormatExtractor
import pandas as pd

class FastaFormatter(Formatter):
    def __init__(self, config, plugin_config):
        """
        Initialize the formatter with user and plugin configuration
        """
        Formatter.__init__(self, config, plugin_config)

    def get_output_formatter(self, stream, schema):
        return FastaOutputFormatter(stream, schema)

    def get_format_extractor(self, stream, schema=None):
        return FastaFormatExtractor(stream, schema)


class FastaOutputFormatter(OutputFormatter):
    """
    Writes Dataiku rows to a FASTA file format
    """
    def __init__(self, stream, schema, config):
        """
        Initialize the formatter, use config to get export options
        :param stream: the stream to write the formatted data to
        :param schema: the schema of the rows to export
        :param config: the export options defined in fasta-format.json
        """
        OutputFormatter.__init__(self, stream)
        self.schema = schema
        self.id_column = config.get('id_column', 'ID')
        self.sequence_column = config.get('sequence_column', 'Sequence')
        self.comment_column = config.get('comment_column', None)
        self.file_extension = config.get('file_extension', '.fasta')

    def write_row(self, row):
        # Each row must contain an ID and a Sequence at minimum
        sequence_id = row.get(self.id_column, 'unknown')
        sequence = row.get(self.sequence_column, '')
        comment = row.get(self.comment_column, '') if self.comment_column else ''

        # Write FASTA entry in the form:
        # >ID COMMENT
        # SEQUENCE
        self.stream.write(f">{sequence_id} {comment}\n")
        # Split sequence into 60-character lines as per FASTA convention
        for i in range(0, len(sequence), 60):
            self.stream.write(sequence[i:i+60] + '\n')

    def write_footer(self):
        # No footer required for FASTA
        pass



class FastaFormatExtractor(FormatExtractor):
    """
    Reads a FASTA file and extracts the data into Dataiku format
    """
    def __init__(self, stream, schema=None):
        FormatExtractor.__init__(self, stream)
        self.stream = stream
        self.columns = ['ID', 'Comment', 'Sequence']

    def read_row(self):
        sequence_id = None
        sequence = []
        comment = ''
        
        for line in self.stream:
            # Decode line if it's in bytes (common in binary streams)
            if isinstance(line, bytes):
                line = line.decode('utf-8')
                
            line = line.strip()
            if line.startswith('>'):
                if sequence_id is not None:
                    # Yield previous sequence
                    return {
                        'ID': sequence_id,
                        'Comment': comment,
                        'Sequence': ''.join(sequence)
                    }
                # New sequence identifier
                parts = line[1:].split(maxsplit=1)
                sequence_id = parts[0]
                comment = parts[1] if len(parts) > 1 else ''
                sequence = []
            else:
                sequence.append(line)
        
        # Return the last sequence if any
        if sequence_id is not None:
            return {
                'ID': sequence_id,
                'Comment': comment,
                'Sequence': ''.join(sequence)
            }
        return None

    def read_schema(self):
        # This method returns the schema as the list of columns (ID, Comment, Sequence)
        return [{"name": "ID", "type": "string"},
                {"name": "Comment", "type": "string"},
                {"name": "Sequence", "type": "string"}]

