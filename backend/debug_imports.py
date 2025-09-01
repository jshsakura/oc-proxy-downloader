
import sys
import os
print("--- Starting debug ---")

# Add path for core module
backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)
project_root = os.path.dirname(backend_path)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

print("Paths set up")

# Now import from the project
try:
    from core.db import engine
    print("Imported engine from core.db")
    from core.models import Base
    print("Imported Base from core.models")

    # The line that is the likely culprit
    print("Running create_all...")
    Base.metadata.create_all(bind=engine)
    print("create_all finished.")

except Exception as e:
    print(f"AN ERROR OCCURRED: {e}")
    import traceback
    traceback.print_exc()

print("--- Debug finished ---")
