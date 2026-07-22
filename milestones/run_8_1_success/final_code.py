import csv
import sys

# Initialize a dictionary to store the sum of values for each name
name_values = {}

# Open the CSV file
with open(sys.argv[1], 'r') as csvfile:
    reader = csv.DictReader(csvfile)
    # Iterate over each row in the CSV file
    for row in reader:
        # Check if the row has the required columns
        if 'name' in row and 'value' in row:
            # Check if the value is not None before converting to float
            if row['value'] is not None and row['value'] != '':
                try:
                    # Try to convert the value to float
                    value = float(row['value'])
                    # Add the value to the sum for the name
                    if row['name'] in name_values:
                        name_values[row['name']] += value
                    else:
                        name_values[row['name']] = value
                except ValueError:
                    # Handle invalid numbers
                    print(f"Invalid number: {row['value']}")

# Print the sum of values for each name
for name, value in name_values.items():
    print(f"{name},{value}")
