"""Worker process targets for load generation.

Import the targets from their modules directly; multiprocessing's spawn context
pickles them by module path, so there is nothing for this package to re-export.
"""
